# Offline Mesh Sync
# Byzantine fault-tolerant sync for disconnected nodes

import logging
log = logging.getLogger(__name__)

class OfflineSync:
    """
    Handles knowledge and state sync when nodes reconnect to mesh.
    Uses vector clocks for conflict resolution.
    Phase 5 — full implementation pending.
    """

    def __init__(self, nodeid: str):
        self.nodeid = nodeid
        self.pending_sync = []

    def queue_update(self, update_type: str, payload: dict):
        """Queue an update to sync when connection is restored."""
        self.pending_sync.append({"type": update_type, "payload": payload})
        log.info(f"Queued {update_type} for sync. Queue size: {len(self.pending_sync)}")

    def flush(self, connection):
        """Flush queued updates to mesh when reconnected."""
        log.info(f"Flushing {len(self.pending_sync)} queued updates to mesh.")
        # TODO Phase 5: implement AISP AI_SYNC packet transmission
        self.pending_sync.clear()
