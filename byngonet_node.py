#!/usr/bin/env python3
"""
byngonet_node.py — Sorabbyngo Byngonet Node
Mesh identity registration + NATS presence

Boot sequence:
1. Read NodeID from HAL (/proc/sorabbyngo/nodeid)
2. Derive mesh identity
3. Generate/load Ed25519 node keypair
4. Sign registration payload
5. Publish to sorabbyngo.byngonet.mesh.register
6. Subscribe to mesh events
7. Maintain heartbeat
"""

import os
import sys
import json
import time
import socket
import threading
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[BYNGONET] %(asctime)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("byngonet.node")

sys.path.insert(0, os.path.dirname(__file__))
from node_identity import HALIdentity

NATS_HOST      = "127.0.0.1"
NATS_PORT      = 4222
HEARTBEAT_SECS = 30


class ByngonetNode:
    def __init__(self):
        self.identity = HALIdentity()
        self._sock    = None
        self._lock    = threading.Lock()
        self._buf     = ""
        self._running = False

    def start(self):
        log.info("Byngonet node starting...")
        log.info(f"Mesh ID  : {self.identity.mesh_id}")
        log.info(f"Hostname : {self.identity.hostname}")
        log.info(f"Kernel   : {self.identity.kernel}")
        log.info(f"Sealed   : {self.identity.sealed}")

        # Save identity to disk
        self.identity.save()

        # Connect to NATS
        self._connect()
        self._running = True

        # Register on mesh
        self._register()

        # Heartbeat thread
        t = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t.start()

        # Subscribe to mesh events
        self._subscribe()

        log.info("Byngonet node active on mesh")

        # Block on listen
        self._listen()

    def _connect(self):
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((NATS_HOST, NATS_PORT))
                s.recv(1024)  # INFO
                s.sendall(b'CONNECT {"verbose":false}\r\n')
                s.settimeout(None)
                self._sock = s
                log.info("Connected to NATS")
                return
            except Exception as e:
                log.warning(f"NATS unavailable: {e} — retrying in 5s")
                time.sleep(5)

    def _publish(self, subject: str, payload: dict):
        msg  = json.dumps(payload)
        data = f"PUB {subject} {len(msg)}\r\n{msg}\r\n".encode()
        with self._lock:
            try:
                self._sock.sendall(data)
            except Exception:
                self._connect()
                self._sock.sendall(data)

    def _subscribe(self):
        subjects = [
            "sorabbyngo.byngonet.mesh.>",
            "sorabbyngo.byngonet.trust.>",
        ]
        for i, subject in enumerate(subjects):
            self._sock.sendall(f"SUB {subject} {i+10}\r\n".encode())
            log.info(f"Subscribed: {subject}")

    def _register(self):
        """
        Sign and publish node registration to mesh.
        Other nodes validate this to establish trust.
        """
        payload = self.identity.to_dict()

        # Sign the registration payload
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature     = self.identity.sign(payload_bytes)
        if signature:
            payload["signature"] = signature

        payload["event"]   = "register"
        payload["version"] = "0.2"

        self._publish("sorabbyngo.byngonet.mesh.register", payload)
        log.info(f"Registered on mesh (sealed={self.identity.sealed})")

    def _heartbeat_loop(self):
        """Publish presence every 30s so mesh knows node is alive"""
        while self._running:
            time.sleep(HEARTBEAT_SECS)
            payload = {
                "event":     "heartbeat",
                "mesh_id":   self.identity.mesh_id,
                "hostname":  self.identity.hostname,
                "sealed":    self.identity.sealed,
                "timestamp": time.time(),
            }
            self._publish("sorabbyngo.byngonet.mesh.heartbeat", payload)
            log.info(f"Heartbeat sent (mesh_id={self.identity.mesh_id[:12]}...)")

    def _listen(self):
        while self._running:
            try:
                chunk = self._sock.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    self._connect()
                    self._register()
                    continue
                self._buf += chunk
                self._buf  = self._process(self._buf)
            except Exception:
                self._connect()
                self._register()

    def _process(self, buf: str) -> str:
        while "\r\n" in buf:
            line, buf = buf.split("\r\n", 1)
            if line.startswith("MSG "):
                parts = line.split()
                if len(parts) >= 4:
                    subject = parts[1]
                    nbytes  = int(parts[3])
                    if len(buf) >= nbytes:
                        payload_raw = buf[:nbytes]
                        buf = buf[nbytes:].lstrip("\r\n")
                        self._on_mesh_event(subject, payload_raw)
        return buf

    def _on_mesh_event(self, subject: str, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        event   = data.get("event", "unknown")
        mesh_id = data.get("mesh_id", "unknown")[:12]
        sealed  = data.get("sealed", False)

        if event == "register":
            log.info(f"Peer registered: {mesh_id}... sealed={sealed}")
        elif event == "heartbeat":
            log.info(f"Peer heartbeat: {mesh_id}...")
        else:
            log.info(f"Mesh event [{subject}]: {event}")


if __name__ == "__main__":
    node = ByngonetNode()
    try:
        node.start()
    except KeyboardInterrupt:
        log.info("Byngonet node shutting down.")
