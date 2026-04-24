"""
Byngonet Node — Full implementation
Manages identity, transport, routing, and mesh participation.
Runs on every Sorabbyngo device from T1 servers to T3 edge devices.
"""
import asyncio
import hashlib
import logging
import os

from protocol.node_identity import get_nodeid, build_node_certificate
from protocol.router import ByngoRouter
from protocol.transport import ByngoTransport
from protocol.packet import ByngoPacket
from protocol.message_types import AI_PROBE, AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC
from node.edge_config import TIER_CONFIGS
from p2p.offline_sync import OfflineSync

log = logging.getLogger("byngonet.node")

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


class ByngonetNode:
    """
    A full Byngonet node.
    Combines transport (UDP/AISP), routing, and offline sync.
    """

    def __init__(self, tier: str = "T1_X86"):
        self.node_id     = get_nodeid()
        self.tier        = tier
        self.config      = TIER_CONFIGS.get(tier, TIER_CONFIGS["T3_ARM32"])
        self.private_key = self._derive_private_key()
        self.certificate = build_node_certificate(
            self.node_id,
            list(self.config.get("allowed_types",
                 [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]))
        )

        self.router    = ByngoRouter(self.node_id)
        self.transport = ByngoTransport(
            node_id     = self.node_id,
            private_key = self.private_key,
            port        = int(os.environ.get("BYNGONET_PORT", 7422)),
        )
        self.sync       = OfflineSync(self.node_id)
        self.is_running = False

        self._wire_handlers()
        log.info(
            "ByngonetNode ready — node=%s tier=%s",
            self.node_id[:16], tier,
        )

    def _derive_private_key(self) -> str:
        """Derive a deterministic private key from NodeID."""
        secret = os.environ.get("BYNGONET_SECRET", "sorabbyngo-default-secret")
        return hashlib.sha256(f"{self.node_id}{secret}".encode()).hexdigest()

    def _wire_handlers(self):
        """Register all packet type handlers on the transport."""
        self.transport.on(AI_PROBE,  self._handle_probe)
        self.transport.on(AI_TASK,   self._handle_task)
        self.transport.on(AI_RESULT, self._handle_result)
        self.transport.on(AI_KNOW,   self._handle_know)
        self.transport.on(AI_SYNC,   self._handle_sync)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_probe(self, packet: ByngoPacket) -> ByngoPacket:
        """Respond to probe with our certificate."""
        log.info("AI_PROBE from %s", packet.sender_node_id[:16])
        self.transport.update_trust(packet.sender_node_id, 0.1)
        return ByngoPacket(
            packet_type    = AI_RESULT,
            sender_node_id = self.node_id,
            target_node_id = packet.sender_node_id,
            payload        = {
                "certificate": self.certificate,
                "tier":        self.tier,
                "node_id":     self.node_id,
            },
            zone = "PUBLIC",
        )

    async def _handle_task(self, packet: ByngoPacket) -> ByngoPacket:
        """Receive AI task — dispatch to local Ollama or queue."""
        log.info(
            "AI_TASK from %s: %s",
            packet.sender_node_id[:16],
            packet.payload.get("task_type", "unknown"),
        )
        self.transport.update_trust(packet.sender_node_id, 0.01)

        # Check capacity
        max_tasks = self.config.get("max_concurrent_tasks", 1)
        result = await self._run_inference(packet.payload)

        return ByngoPacket(
            packet_type    = AI_RESULT,
            sender_node_id = self.node_id,
            target_node_id = packet.sender_node_id,
            payload        = {
                "task_id":  packet.packet_id,
                "result":   result,
                "node_id":  self.node_id,
                "tier":     self.tier,
            },
            zone = packet.zone,
        )

    async def _handle_result(self, packet: ByngoPacket):
        """Receive result from remote inference — publish to NATS."""
        log.info("AI_RESULT from %s", packet.sender_node_id[:16])
        self.transport.update_trust(packet.sender_node_id, 0.02)
        await self._publish_nats(
            "byngonet.task.result",
            {
                "task_id":   packet.payload.get("task_id"),
                "result":    packet.payload.get("result"),
                "from_node": packet.sender_node_id,
                "tier":      packet.payload.get("tier"),
            }
        )
        return None

    async def _handle_know(self, packet: ByngoPacket):
        """Receive knowledge update — store and rebroadcast if needed."""
        accepted = self.sync.receive_sync(packet)
        if accepted:
            log.info(
                "AI_KNOW from %s: %s",
                packet.sender_node_id[:16],
                packet.payload.get("update_type", "unknown"),
            )
            self.transport.update_trust(packet.sender_node_id, 0.01)
            # Rebroadcast to rest of mesh (TTL-limited)
            if packet.hop_count < 3:
                packet.hop_count += 1
                await self.transport.broadcast(packet)
        return None

    async def _handle_sync(self, packet: ByngoPacket):
        """Receive model sync packet — store locally."""
        accepted = self.sync.receive_sync(packet)
        if accepted:
            log.info("AI_SYNC from %s", packet.sender_node_id[:16])
        return None

    # ── Inference dispatch ────────────────────────────────────────────────────

    async def _run_inference(self, task: dict) -> dict:
        """Run local inference for a mesh-dispatched task."""
        import urllib.request
        import json as _json

        model   = task.get("model", "phi4-mini")
        prompt  = task.get("prompt", "")
        options = task.get("options", {"temperature": 0.3, "num_predict": 256})

        payload = _json.dumps({
            "model":   model,
            "prompt":  prompt,
            "stream":  False,
            "options": options,
        }).encode()

        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            loop = asyncio.get_event_loop()
            def _post():
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.read().decode()
            raw    = await loop.run_in_executor(None, _post)
            result = _json.loads(raw)
            return {"response": result.get("response", ""), "model": model, "status": "ok"}
        except Exception as e:
            log.error("Inference error: %s", e)
            return {"response": "", "model": model, "status": "error", "error": str(e)}

    # ── NATS publishing ───────────────────────────────────────────────────────

    async def _publish_nats(self, subject: str, data: dict):
        try:
            import nats
            nc = await nats.connect(NATS_URL)
            import json as _json
            await nc.publish(subject, _json.dumps(data).encode())
            await nc.close()
        except Exception as e:
            log.debug("NATS publish error: %s", e)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self.is_running = True
        self.sync.mark_connected(self.transport)

        log.info(
            "╔══════════════════════════════════════╗\n"
            "║  Byngonet Node Online                ║\n"
            "╚══════════════════════════════════════╝\n"
            "  NodeID : %s...\n"
            "  Tier   : %s\n"
            "  Port   : %d",
            self.node_id[:16], self.tier,
            int(os.environ.get("BYNGONET_PORT", 7422)),
        )

        # Flush any offline-queued updates
        await self.sync.flush(self.transport)

        await self.transport.start()

    def stop(self):
        self.is_running = False
        self.sync.mark_disconnected()
        self.transport.stop()
        log.info("Byngonet node stopped.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    import sys
    tier = sys.argv[1] if len(sys.argv) > 1 else "T1_X86"
    node = ByngonetNode(tier=tier)
    asyncio.run(node.start())
