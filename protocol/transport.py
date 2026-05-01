"""
Byngonet — AISP Transport Layer
UDP-based mesh transport for AI Intelligence Sharing Protocol packets.

Each node listens on UDP port 7422.
Packets are JSON-encoded ByngoPackets with HMAC-SHA256 signatures.
Post-quantum BSP signatures are planned for Phase 6.
"""
import asyncio
import json
import logging
import os
import socket
import time
from typing import Callable, Dict, Optional

from .packet import ByngoPacket
from .trust_store import TrustStore
from .message_types import SECURITY_ZONES, AI_PROBE

log = logging.getLogger("byngonet.transport")

BYNGONET_PORT     = int(os.environ.get("BYNGONET_PORT", 7422))
BYNGONET_MCAST    = "239.255.74.22"   # multicast group for peer discovery
MAX_PACKET_SIZE   = 65535
HEARTBEAT_INTERVAL = 30               # seconds between peer heartbeats
PEER_TIMEOUT       = 120              # seconds before peer considered dead


class ByngoTransport:
    """
    UDP transport for AISP packets.
    Handles:
      - Unicast packet send/receive
      - Multicast peer discovery
      - Peer liveness tracking
      - Zone enforcement before forwarding
    """

    def __init__(
        self,
        node_id: str,
        private_key: str,
        port: int = BYNGONET_PORT,
        bind_addr: str = "0.0.0.0",
    ):
        self.node_id     = node_id
        self.private_key = private_key
        self.port        = port
        self.bind_addr   = bind_addr
        self._running    = False

        # peer_id → {"addr": str, "last_seen": float, "trust": float}
        self._peers: Dict[str, dict] = {}

        # packet_type → handler coroutine
        self._handlers: Dict[str, Callable] = {}

        # Dedup cache — prevent replay attacks
        self._seen_packets: set = set()
        self._seen_max = 10000
        self._trust_store = TrustStore()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        log.info(
            "ByngoTransport starting — node=%s port=%d",
            self.node_id[:16], self.port,
        )
        await asyncio.gather(
            self._listen_loop(),
            self._discovery_loop(),
            self._heartbeat_loop(),
            self._peer_cleanup_loop(),
        )

    def stop(self):
        self._running = False

    # ── Handler registration ──────────────────────────────────────────────────

    def on(self, packet_type: str, handler: Callable):
        self._handlers[packet_type] = handler
        log.debug("Handler registered: %s", packet_type)

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send(self, packet: ByngoPacket, addr: str) -> bool:
        """Send a packet to a specific address:port."""
        # Zone enforcement
        zone_cfg = SECURITY_ZONES.get(packet.zone, SECURITY_ZONES["PUBLIC"])
        if packet.packet_type not in zone_cfg["allowed"]:
            log.warning(
                "Zone %s does not allow %s — dropped",
                packet.zone, packet.packet_type,
            )
            return False

        packet.sign(self.private_key)
        data = packet.to_bytes()

        try:
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            host, port = addr.split(":") if ":" in addr else (addr, self.port)
            await loop.run_in_executor(
                None, lambda: sock.sendto(data, (host, int(port)))
            )
            sock.close()
            log.debug("Sent %s → %s (%d bytes)", packet.packet_type, addr, len(data))
            return True
        except Exception as e:
            log.error("Send error to %s: %s", addr, e)
            return False

    async def broadcast(self, packet: ByngoPacket):
        """Send packet to all known peers."""
        for peer_id, info in list(self._peers.items()):
            if peer_id != self.node_id:
                packet.target_node_id = peer_id
                await self.send(packet, info["addr"])

    async def multicast_probe(self):
        """Send AI_PROBE to multicast group for peer discovery."""
        packet = ByngoPacket(
            packet_type    = AI_PROBE,
            sender_node_id = self.node_id,
            target_node_id = "broadcast",
            payload        = {
                "node_id": self.node_id,
                "port":    self.port,
                "ts":      time.time(),
            },
            zone = "PUBLIC",
        )
        packet.sign(self.private_key)
        data = packet.to_bytes()

        try:
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            await loop.run_in_executor(
                None, lambda: sock.sendto(data, (BYNGONET_MCAST, self.port))
            )
            sock.close()
        except Exception as e:
            log.debug("Multicast probe error: %s", e)

    # ── Receive ───────────────────────────────────────────────────────────────

    async def _listen_loop(self):
        """Main UDP receive loop."""
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Join multicast group for peer discovery
        try:
            mcast_req = socket.inet_aton(BYNGONET_MCAST) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcast_req)
        except Exception as e:
            log.debug("Multicast join failed (unicast only): %s", e)

        try:
            sock.bind((self.bind_addr, self.port))
        except OSError as e:
            log.error("Cannot bind to port %d: %s", self.port, e)
            return

        sock.setblocking(False)
        log.info("Listening on UDP %s:%d", self.bind_addr, self.port)

        while self._running:
            try:
                data, addr = await loop.run_in_executor(
                    None, lambda: self._recv_with_timeout(sock)
                )
                if data:
                    asyncio.create_task(self._handle_raw(data, addr))
            except Exception:
                await asyncio.sleep(0.1)

        sock.close()

    def _recv_with_timeout(self, sock, timeout: float = 1.0):
        import select
        ready = select.select([sock], [], [], timeout)
        if ready[0]:
            return sock.recvfrom(MAX_PACKET_SIZE)
        return None, None

    async def _handle_raw(self, data: bytes, addr):
        """Deserialize, validate and dispatch a received packet."""
        try:
            packet = ByngoPacket.from_bytes(data)
        except Exception as e:
            log.debug("Malformed packet from %s: %s", addr, e)
            return

        # Replay protection
        if packet.packet_id in self._seen_packets:
            return
        self._seen_packets.add(packet.packet_id)
        if len(self._seen_packets) > self._seen_max:
            self._seen_packets.clear()

        # Expiry check
        if packet.is_expired():
            log.debug("Expired packet from %s", packet.sender_node_id[:8])
            return

        # Zone check
        src_trust = self._get_trust(packet.sender_node_id)
        zone_cfg  = SECURITY_ZONES.get(packet.zone, SECURITY_ZONES["PUBLIC"])
        if src_trust < zone_cfg["min_trust"] and packet.packet_type != AI_PROBE:
            log.warning(
                "Zone violation from %s: trust=%.2f required=%.2f",
                packet.sender_node_id[:8], src_trust, zone_cfg["min_trust"],
            )
            return

        # Update peer last_seen
        sender = packet.sender_node_id
        if sender not in self._peers:
            src_addr = f"{addr[0]}:{addr[1]}"
            self._peers[sender] = {"addr": src_addr, "last_seen": time.time(), "trust": 0.1}
            log.info("New peer: %s @ %s", sender[:16], src_addr)
        else:
            self._peers[sender]["last_seen"] = time.time()

        # Dispatch to handler
        handler = self._handlers.get(packet.packet_type)
        if handler:
            try:
                result = await handler(packet)
                # If result is a packet, send it back
                if isinstance(result, ByngoPacket):
                    await self.send(result, f"{addr[0]}:{addr[1]}")
            except Exception as e:
                log.error("Handler error for %s: %s", packet.packet_type, e)
        else:
            log.debug("No handler for %s", packet.packet_type)

    # ── Discovery loop ────────────────────────────────────────────────────────

    async def _discovery_loop(self):
        """Periodic multicast probe for peer discovery."""
        while self._running:
            await self.multicast_probe()
            await asyncio.sleep(60)

    # ── Heartbeat loop ────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        """Send AI_PROBE heartbeat to all known peers."""
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._peers:
                packet = ByngoPacket(
                    packet_type    = AI_PROBE,
                    sender_node_id = self.node_id,
                    target_node_id = "broadcast",
                    payload        = {"node_id": self.node_id, "ts": time.time()},
                    zone           = "PUBLIC",
                )
                await self.broadcast(packet)
                log.debug("Heartbeat sent to %d peers", len(self._peers))

    # ── Peer cleanup ──────────────────────────────────────────────────────────

    async def _peer_cleanup_loop(self):
        """Remove peers that haven't been seen recently."""
        while self._running:
            await asyncio.sleep(60)
            now  = time.time()
            dead = [
                pid for pid, info in self._peers.items()
                if now - info["last_seen"] > PEER_TIMEOUT
            ]
            for pid in dead:
                log.info("Peer timed out: %s", pid[:16])
                del self._peers[pid]

    # ── Trust ─────────────────────────────────────────────────────────────────

    def _get_trust(self, node_id: str) -> float:
        return self._peers.get(node_id, {}).get("trust", 0.0)

    def update_trust(self, node_id: str, delta: float):
        if node_id in self._peers:
            current = self._peers[node_id]["trust"]
            self._peers[node_id]["trust"] = max(0.0, min(1.0, current + delta))

    def peers(self) -> dict:
        return dict(self._peers)
