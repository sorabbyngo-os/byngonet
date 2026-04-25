"""Tests for TrustStore — persistence, scoring, zone mapping."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from protocol.trust_store import TrustStore


def make_store():
    tmp = tempfile.mktemp(suffix=".json")
    return TrustStore(path=tmp), tmp


def test_default_trust_zero():
    store, _ = make_store()
    assert store.get("unknown-node") == 0.0


def test_update_increases_trust():
    store, _ = make_store()
    store.update("node-A", 0.3)
    store.update("node-A", 0.3)
    assert abs(store.get("node-A") - 0.6) < 0.001


def test_trust_clamped_at_one():
    store, _ = make_store()
    store.update("node-A", 2.0)
    assert store.get("node-A") == 1.0


def test_trust_clamped_at_zero():
    store, _ = make_store()
    store.update("node-A", -5.0)
    assert store.get("node-A") == 0.0


def test_zone_public():
    store, _ = make_store()
    store.set("node-A", 0.3)
    assert store.zone("node-A") == "PUBLIC"


def test_zone_trusted():
    store, _ = make_store()
    store.set("node-A", 0.8)
    assert store.zone("node-A") == "TRUSTED"


def test_zone_personal():
    store, _ = make_store()
    store.set("node-A", 1.0)
    assert store.zone("node-A") == "PERSONAL"


def test_persist_and_reload():
    store, path = make_store()
    store.set("node-A", 0.75, addr="192.168.1.10:7422")
    store.save()
    store2 = TrustStore(path=path)
    assert abs(store2.get("node-A") - 0.75) < 0.001
    os.unlink(path)


def test_trusted_peers_list():
    store, _ = make_store()
    store.set("node-A", 0.9)
    store.set("node-B", 0.3)
    store.set("node-C", 0.7)
    trusted = store.trusted_peers()
    assert "node-A" in trusted
    assert "node-C" in trusted
    assert "node-B" not in trusted


def test_prune_stale():
    store, _ = make_store()
    store._store["old-node"] = {"trust": 0.9, "last_seen": time.time() - 999999, "seen_count": 1}
    store._store["new-node"] = {"trust": 0.5, "last_seen": time.time(), "seen_count": 1}
    pruned = store.prune_stale(max_age=3600)
    assert pruned == 1
    assert "new-node" in store._store
    assert "old-node" not in store._store


if __name__ == "__main__":
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
