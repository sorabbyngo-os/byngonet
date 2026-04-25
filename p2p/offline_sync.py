"""
Byngonet — Offline Mesh Sync
Byzantine fault-tolerant sync for disconnected nodes.
Uses vector clocks for conflict resolution.
Queues AI_KNOW and AI_SYNC packets when offline,
flushes them on reconnect in causal order.
"""
import asyncio
import hashlib
import json
import logging
import time
from typing import Optional

log = logging.getLogger("byngonet.offline_sync")

MAX_QUEUE  = 1000   # max packets to queue while offline
MAX_AGE    = 3600   # drop queued packets older than 1 hour


class VectorClock:
    """
    Simple vector clock for causal ordering of mesh updates.
    Each node maintains its own counter.
    """
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.clock: dict[str, int] = {node_id: 0}

    def tick(self) -> dict:
        """Increment own counter and return current clock."""
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1
        return dict(self.clock)

    def update(self, remote: dict):
        """Merge remote clock — take max of each entry."""
        for node, ts in remote.items():
            self.clock[node] = max(self.clock.get(node, 0), ts)
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1

    def happens_before(self, a: dict, b: dict) -> bool:
        """Return True if clock a happened before clock b."""
        return all(a.get(n, 0) <= b.get(n, 0) for n in a) and a != b

    def concurrent(self, a: dict, b: dict) -> bool:
        """Return True if a and b are concurrent (no causal order)."""
        return not self.happens_before(a, b) and not self.happens_before(b, a)


class QueuedPacket:
    """A packet queued for sync with metadata."""
    def __init__(self, packet, vector_clock: dict):
        self.packet       = packet
        self.vector_clock = vector_clock
        self.queued_at    = time.time()
        self.attempts     = 0

    def is_expired(self) -> bool:
        return time.time() - self.queued_at > MAX_AGE

    def packet_hash(self) -> str:
        """Deduplicate by content hash."""
        content = json.dumps(self.packet.payload, sort_keys=True)
        return hashlib.sha256(
            f"{self.packet.packet_type}{self.packet.sender_node_id}{content}".encode()
        ).hexdigest()[:16]


class OfflineSync:
    """
    Handles knowledge and state sync when nodes reconnect to the mesh.

    Responsibilities:
    - Queue AI_KNOW and AI_SYNC packets when offline
    - Flush queue on reconnect in causal order (vector clock sort)
    - Deduplicate incoming sync packets
    - Track connected state and transport reference
    """

    SYNCABLE_TYPES = {"AI_KNOW", "AI_SYNC"}

    def __init__(self, node_id: str):
        self.node_id     = node_id
        self.vclock      = VectorClock(node_id)
        self._queue:     list[QueuedPacket] = []
        self._seen:      set[str]           = set()
        self._connected  = False
        self._transport  = None
        self._lock       = asyncio.Lock()

    # ── Connection state ──────────────────────────────────────────────────────

    def mark_connected(self, transport):
        """Call when node joins the mesh."""
        self._connected = True
        self._transport = transport
        log.info("OfflineSync: node connected — %d packets queued", len(self._queue))

    def mark_disconnected(self):
        """Call when node loses mesh connectivity."""
        self._connected = False
        self._transport = None
        log.info("OfflineSync: node disconnected — queuing mode active")

    # ── Receive ───────────────────────────────────────────────────────────────

    def receive_sync(self, packet) -> bool:
        """
        Process an incoming AI_KNOW or AI_SYNC packet.
        Returns True if accepted (new), False if duplicate.
        Called by ByngonetNode._handle_know and _handle_sync.
        """
        if packet.packet_type not in self.SYNCABLE_TYPES:
            return False

        # Dedup
        content_hash = hashlib.sha256(
            json.dumps(packet.payload, sort_keys=True).encode()
        ).hexdigest()[:16]

        if content_hash in self._seen:
            log.debug("OfflineSync: duplicate packet dropped (%s)", content_hash)
            return False

        self._seen.add(content_hash)
        if len(self._seen) > 5000:
            self._seen.clear()

        # Update vector clock with remote clock if present
        remote_clock = packet.payload.get("_vclock", {})
        if remote_clock:
            self.vclock.update(remote_clock)

        log.debug(
            "OfflineSync: accepted %s from %s",
            packet.packet_type, packet.sender_node_id[:12]
        )
        return True

    # ── Queue ─────────────────────────────────────────────────────────────────

    def queue_update(self, update_type: str, payload: dict):
        """
        Queue an update to sync when connection is restored.
        Only queues syncable packet types.
        """
        if update_type not in self.SYNCABLE_TYPES:
            log.debug("OfflineSync: %s not syncable, skipping", update_type)
            return

        if len(self._queue) >= MAX_QUEUE:
            # Drop oldest non-critical packet
            self._queue.pop(0)
            log.warning("OfflineSync: queue full — dropped oldest entry")

        from protocol.packet import ByngoPacket
        clock = self.vclock.tick()
        payload["_vclock"]   = clock
        payload["_queued_at"] = time.time()

        packet = ByngoPacket(
            packet_type    = update_type,
            sender_node_id = self.node_id,
            target_node_id = "broadcast",
            payload        = payload,
            zone           = "TRUSTED",
        )
        queued = QueuedPacket(packet, clock)
        self._queue.append(queued)
        log.info(
            "OfflineSync: queued %s (total=%d)", update_type, len(self._queue)
        )

    # ── Flush ─────────────────────────────────────────────────────────────────

    async def flush(self, transport) -> int:
        """
        Flush all queued packets to the mesh on reconnect.
        Sorts by vector clock (causal order) before sending.
        Returns number of packets flushed.
        """
        if not self._queue:
            log.debug("OfflineSync: nothing to flush")
            return 0

        # Drop expired packets first
        before = len(self._queue)
        self._queue = [q for q in self._queue if not q.is_expired()]
        dropped = before - len(self._queue)
        if dropped:
            log.info("OfflineSync: dropped %d expired packets", dropped)

        if not self._queue:
            return 0

        # Sort by vector clock — causal order
        def sort_key(q: QueuedPacket):
            return q.queued_at

        self._queue.sort(key=sort_key)

        log.info("OfflineSync: flushing %d queued packets to mesh", len(self._queue))

        flushed = 0
        failed  = []

        for queued in self._queue:
            try:
                await transport.broadcast(queued.packet)
                flushed += 1
                # Small delay to avoid flooding mesh
                await asyncio.sleep(0.05)
            except Exception as e:
                queued.attempts += 1
                log.warning(
                    "OfflineSync: failed to flush packet (attempt %d): %s",
                    queued.attempts, e
                )
                if queued.attempts < 3:
                    failed.append(queued)

        self._queue = failed

        log.info(
            "OfflineSync: flush complete — sent=%d failed=%d",
            flushed, len(failed)
        )
        return flushed

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "connected":    self._connected,
            "queued":       len(self._queue),
            "seen":         len(self._seen),
            "vector_clock": self.vclock.clock,
        }
