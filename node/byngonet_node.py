import asyncio
import logging
from pathlib import Path
from ..protocol.node_identity import get_nodeid, build_node_certificate
from ..protocol.router import ByngoRouter
from ..protocol.message_types import AI_PROBE, AI_TASK, AI_RESULT, AI_KNOW
from ..node.edge_config import TIER_CONFIGS
from ..p2p.offline_sync import OfflineSync

log = logging.getLogger(__name__)

class ByngonetNode:
    """
    A Byngonet node. Manages identity, routing, and mesh participation.
    Runs on every Sorabbyngo device from T1 servers to T3 edge devices.
    """
    def __init__(self, tier: str = "T1_X86"):
        self.node_id = get_nodeid()
        self.tier = tier
        self.config = TIER_CONFIGS.get(tier, TIER_CONFIGS["T3_ARM32"])
        self.certificate = build_node_certificate(
            self.node_id,
            ["AI_TASK", "AI_RESULT", "AI_KNOW", "AI_SYNC", "AI_PROBE"]
        )
        self.router = ByngoRouter(self.node_id)
        self.sync = OfflineSync(self.node_id)
        self.is_running = False
        self._register_handlers()
        log.info(f"ByngonetNode initialized: {self.node_id[:16]}... tier={tier}")

    def _register_handlers(self):
        self.router.register_handler(AI_PROBE, self._handle_probe)
        self.router.register_handler(AI_TASK, self._handle_task)
        self.router.register_handler(AI_RESULT, self._handle_result)
        self.router.register_handler(AI_KNOW, self._handle_know)

    async def _handle_probe(self, packet) -> dict:
        """Respond to probe with our certificate."""
        log.info(f"Probe from {packet.sender_node_id[:8]}")
        return {"certificate": self.certificate, "tier": self.tier}

    async def _handle_task(self, packet) -> dict:
        """Receive an AI task for local inference."""
        log.info(f"AI task received from {packet.sender_node_id[:8]}")
        return {"status": "queued", "node_id": self.node_id}

    async def _handle_result(self, packet) -> dict:
        """Receive result from remote inference."""
        log.info(f"AI result from {packet.sender_node_id[:8]}")
        return {"status": "received"}

    async def _handle_know(self, packet) -> dict:
        """Receive a knowledge update."""
        self.sync.queue_update("AI_KNOW", packet.payload)
        return {"status": "queued"}

    async def start(self):
        self.is_running = True
        log.info(f"Byngonet node started — {self.node_id[:16]}...")
        while self.is_running:
            await asyncio.sleep(1)

    def stop(self):
        self.is_running = False
        log.info("Byngonet node stopped.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    node = ByngonetNode(tier="T1_X86")
    asyncio.run(node.start())
