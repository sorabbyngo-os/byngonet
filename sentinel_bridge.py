"""
Byngonet — Sentinel Bridge
Publishes mesh events to NATS so the Sorabbyngo Sentinel
daemon can monitor the mesh and escalate threats.

Publishes to:
  sorabbyngo.byngonet.peer         — peer join/leave events
  sorabbyngo.byngonet.trust        — trust score changes
  sorabbyngo.byngonet.status       — node health heartbeat
  sorabbyngo.cyberwall.alert       — security anomalies

Subscribes to:
  sorabbyngo.sentinel.command      — operator commands
  sorabbyngo.byngonet.command      — mesh-level commands
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("byngonet.sentinel_bridge")

NATS_URL      = os.environ.get("NATS_URL", "nats://localhost:4222")
HEARTBEAT_INT = 30  # seconds

class SentinelBridge:
    """
    Bridges the Byngonet mesh to the Sorabbyngo Sentinel daemon via NATS.
    Runs as a background coroutine alongside the main node.
    """

    def __init__(self, node):
        self._node    = node
        self._nc      = None
        self._running = False

    async def start(self):
        self._running = True
        await asyncio.gather(
            self._connect_loop(),
            self._heartbeat_loop(),
        )

    def stop(self):
        self._running = False

    async def _connect_loop(self):
        while self._running:
            try:
                await self._connect()
                await self._subscribe()
                log.info("Sentinel bridge connected to NATS")
                # Wait until disconnected
                while self._running and self._nc and not self._nc.is_closed:
                    await asyncio.sleep(5)
            except Exception as e:
                log.warning("Sentinel bridge NATS error: %s — retrying in 10s", e)
                await asyncio.sleep(10)

    async def _connect(self):
        try:
            import nats
            self._nc = await nats.connect(
                NATS_URL,
                name=f"byngonet-{self._node.node_id[:8]}",
                reconnect_time_wait=5,
                max_reconnect_attempts=-1,
            )
        except ImportError:
            log.warning("nats-py not installed — sentinel bridge disabled")
            self._running = False

    async def _subscribe(self):
        if not self._nc:
            return
        await self._nc.subscribe(
            "sorabbyngo.sentinel.command",
            cb=self._on_sentinel_command,
        )
        await self._nc.subscribe(
            "sorabbyngo.byngonet.command",
            cb=self._on_mesh_command,
        )

    async def _on_sentinel_command(self, msg):
        try:
            data = json.loads(msg.data.decode())
            cmd  = data.get("command", "")
            log.info("Sentinel command: %s", cmd)

            if cmd == "status":
                await self._publish_status()
            elif cmd == "peers":
                await self._publish_peers()
            elif cmd == "trust_scores":
                await self._publish_trust_scores()
        except Exception as e:
            log.error("Sentinel command error: %s", e)

    async def _on_mesh_command(self, msg):
        try:
            data = json.loads(msg.data.decode())
            cmd  = data.get("command", "")
            log.info("Mesh command: %s", cmd)

            if cmd == "probe":
                await self._node.transport.multicast_probe()
            elif cmd == "flush_sync":
                sent = await self._node.sync.flush(self._node.transport)
                log.info("Mesh flush: %d packets sent", sent)
            elif cmd == "set_trust":
                node_id = data.get("node_id")
                trust   = float(data.get("trust", 0.0))
                if node_id:
                    self._node.transport.update_trust(node_id, trust)
                    log.info("Trust updated: %s → %.2f", node_id[:12], trust)
        except Exception as e:
            log.error("Mesh command error: %s", e)

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(HEARTBEAT_INT)
            await self._publish_status()

    async def _publish_status(self):
        if not self._nc:
            return
        try:
            peers      = self._node.transport._peers
            sync_stats = self._node.sync.stats()
            await self._publish("sorabbyngo.byngonet.status", {
                "service":      "byngonet",
                "node_id":      self._node.node_id,
                "tier":         self._node.tier,
                "peer_count":   len(peers),
                "queued_sync":  sync_stats["queued"],
                "connected":    sync_stats["connected"],
                "vector_clock": sync_stats["vector_clock"],
                "timestamp":    time.time(),
            })
            # Also send sentinel heartbeat
            await self._publish(
                f"sorabbyngo.byngonet.heartbeat",
                {"service": "byngonet", "node_id": self._node.node_id,
                 "timestamp": time.time()}
            )
        except Exception as e:
            log.debug("Status publish error: %s", e)

    async def _publish_peers(self):
        if not self._nc:
            return
        peers = self._node.transport._peers
        await self._publish("sorabbyngo.byngonet.peers", {
            "node_id": self._node.node_id,
            "peers":   [
                {"node_id": nid, **info}
                for nid, info in peers.items()
            ],
            "timestamp": time.time(),
        })

    async def _publish_trust_scores(self):
        if not self._nc:
            return
        peers = self._node.transport._peers
        await self._publish("sorabbyngo.byngonet.trust", {
            "node_id": self._node.node_id,
            "scores":  {
                nid: info.get("trust", 0.0)
                for nid, info in peers.items()
            },
            "timestamp": time.time(),
        })

    async def publish_alert(self, level: str, threat_type: str,
                            description: str, data: dict = None):
        """Publish a security alert to Cyberwall via NATS."""
        await self._publish("sorabbyngo.cyberwall.alert", {
            "level":       level,
            "threat_type": threat_type,
            "description": description,
            "source":      "byngonet",
            "node_id":     self._node.node_id,
            "data":        data or {},
            "timestamp":   time.time(),
        })

    async def _publish(self, subject: str, data: dict):
        if not self._nc or self._nc.is_closed:
            return
        try:
            await self._nc.publish(subject, json.dumps(data).encode())
        except Exception as e:
            log.debug("Publish error [%s]: %s", subject, e)
