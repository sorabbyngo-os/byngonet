import asyncio
import logging
from .packet import ByngoPacket
from .message_types import AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE
from .node_identity import get_nodeid

log = logging.getLogger(__name__)

class ByngoRouter:
    """
    Routes AISP packets between nodes.
    Handles: dispatch, receive, forward, trust scoring.
    """
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.peers = {}
        self.trust_scores = {}
        self.handlers = {}
        self.routing_table = {}

    def register_handler(self, packet_type: str, handler):
        """Register a handler for a packet type."""
        self.handlers[packet_type] = handler
        log.info(f"Handler registered for {packet_type}")

    def add_peer(self, peer_id: str, address: str, trust: float = 0.0):
        """Add a peer node to the routing table."""
        self.peers[peer_id] = address
        self.trust_scores[peer_id] = trust
        log.info(f"Peer added: {peer_id[:8]}... trust={trust}")

    def get_trust(self, node_id: str) -> float:
        return self.trust_scores.get(node_id, 0.0)

    def update_trust(self, node_id: str, delta: float):
        """Update trust score for a node."""
        current = self.trust_scores.get(node_id, 0.0)
        self.trust_scores[node_id] = max(0.0, min(1.0, current + delta))

    async def dispatch(self, packet_type: str, target: str, payload: dict) -> ByngoPacket:
        """Create and send a packet to a target node."""
        packet = ByngoPacket(
            packet_type=packet_type,
            sender_node_id=self.node_id,
            target_node_id=target,
            payload=payload,
            zone=self._get_zone(target),
        )
        log.info(f"Dispatching {packet_type} to {target[:8]}...")
        return packet

    async def receive(self, packet: ByngoPacket) -> dict:
        """Process an incoming packet."""
        if packet.is_expired():
            log.warning(f"Dropped expired packet {packet.packet_id[:8]}")
            return {"status": "dropped", "reason": "expired"}

        if not packet.verify(self.get_trust(packet.sender_node_id).__str__()):
            log.warning(f"Dropped unverified packet from {packet.sender_node_id[:8]}")
            return {"status": "dropped", "reason": "unverified"}

        handler = self.handlers.get(packet.packet_type)
        if not handler:
            log.warning(f"No handler for {packet.packet_type}")
            return {"status": "dropped", "reason": "no_handler"}

        self.update_trust(packet.sender_node_id, 0.01)
        result = await handler(packet)
        return {"status": "processed", "result": result}

    def _get_zone(self, node_id: str) -> str:
        trust = self.get_trust(node_id)
        if trust >= 1.0:
            return "PERSONAL"
        elif trust >= 0.7:
            return "TRUSTED"
        return "PUBLIC"
