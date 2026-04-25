"""
Byngonet — Trust Store
Persists peer trust scores across restarts.
Scores reset to 0 on every restart without this —
a node that took weeks to earn TRUSTED zone loses it instantly.
"""
import json
import logging
import os
import time

log = logging.getLogger("byngonet.trust_store")

TRUST_FILE = os.path.expanduser("~/.sorabbyngo/byngonet/trust.json")
MAX_AGE    = 60 * 60 * 24 * 30  # 30 days — drop stale peers


class TrustStore:
    """
    Persistent trust score storage for Byngonet peers.
    Backed by a JSON file on disk.
    Thread-safe via explicit save/load.
    """

    def __init__(self, path: str = TRUST_FILE):
        self.path   = path
        self._store: dict[str, dict] = {}
        self._load()

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(self.path):
            log.debug("TrustStore: no existing store at %s", self.path)
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            # Drop stale entries
            now    = time.time()
            pruned = {
                k: v for k, v in data.items()
                if now - v.get("last_seen", 0) < MAX_AGE
            }
            self._store = pruned
            log.info("TrustStore: loaded %d peers (%d pruned)",
                     len(pruned), len(data) - len(pruned))
        except Exception as e:
            log.error("TrustStore: load error: %s", e)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            with open(self.path, "w") as f:
                json.dump(self._store, f, indent=2)
            log.debug("TrustStore: saved %d peers", len(self._store))
        except Exception as e:
            log.error("TrustStore: save error: %s", e)

    # ── Trust operations ──────────────────────────────────────────────────────

    def get(self, node_id: str) -> float:
        return self._store.get(node_id, {}).get("trust", 0.0)

    def update(self, node_id: str, delta: float, addr: str = "") -> float:
        entry   = self._store.get(node_id, {"trust": 0.0, "addr": addr, "seen_count": 0})
        current = entry["trust"]
        updated = max(0.0, min(1.0, current + delta))
        self._store[node_id] = {
            "trust":      updated,
            "addr":       addr or entry.get("addr", ""),
            "last_seen":  time.time(),
            "seen_count": entry.get("seen_count", 0) + 1,
        }
        return updated

    def set(self, node_id: str, trust: float, addr: str = ""):
        self._store[node_id] = {
            "trust":     max(0.0, min(1.0, trust)),
            "addr":      addr,
            "last_seen": time.time(),
            "seen_count": self._store.get(node_id, {}).get("seen_count", 0),
        }

    def zone(self, node_id: str) -> str:
        trust = self.get(node_id)
        if trust >= 1.0:
            return "PERSONAL"
        elif trust >= 0.7:
            return "TRUSTED"
        return "PUBLIC"

    def all_peers(self) -> dict:
        return dict(self._store)

    def peer_count(self) -> int:
        return len(self._store)

    def trusted_peers(self) -> list[str]:
        return [nid for nid, v in self._store.items() if v["trust"] >= 0.7]

    def prune_stale(self, max_age: int = MAX_AGE) -> int:
        now    = time.time()
        before = len(self._store)
        self._store = {
            k: v for k, v in self._store.items()
            if now - v.get("last_seen", 0) < max_age
        }
        pruned = before - len(self._store)
        if pruned:
            log.info("TrustStore: pruned %d stale peers", pruned)
        return pruned

    def __repr__(self):
        return f"TrustStore(peers={len(self._store)}, path={self.path})"
