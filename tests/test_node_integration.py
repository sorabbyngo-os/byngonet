"""
Integration tests for ByngonetNode and SentinelBridge.
Tests that don't require a live kernel NodeID or NATS connection.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Patch NodeID to avoid kernel dependency in tests
os.environ.setdefault("SORABBYNGO_NODE_ID", "test-node-deadbeef1234567890abcdef12345678")
os.environ.setdefault("BYNGONET_SECRET", "test-secret")
os.environ.setdefault("BYNGONET_TIER", "T1_X86")

from protocol.packet import ByngoPacket
from protocol.message_types import AI_PROBE, AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC
from protocol.signing import derive_keypair, sign, verify
from protocol.trust_store import TrustStore
from p2p.offline_sync import OfflineSync, VectorClock
from node.edge_config import TIER_CONFIGS

# ---- Packet tests ----

def test_packet_sign_verify():
    priv, pub = derive_keypair("test-node", "test-secret")
    packet = ByngoPacket(
        packet_type    = AI_PROBE,
        sender_node_id = "test-node",
        target_node_id = "peer-node",
        payload        = {"hello": "world"},
        zone           = "PUBLIC",
    )
    packet.sign(priv)
    assert packet.signature != ""
    assert packet.verify(pub)

def test_packet_serialization():
    packet = ByngoPacket(
        packet_type    = AI_TASK,
        sender_node_id = "node-A",
        target_node_id = "node-B",
        payload        = {"prompt": "hello", "model": "phi4-mini"},
        zone           = "TRUSTED",
    )
    data     = packet.to_bytes()
    restored = ByngoPacket.from_bytes(data)
    assert restored.packet_type    == AI_TASK
    assert restored.sender_node_id == "node-A"
    assert restored.payload["prompt"] == "hello"

def test_packet_expiry():
    packet = ByngoPacket(ttl=1)
    assert not packet.is_expired()
    packet.timestamp -= 5
    assert packet.is_expired()

def test_zone_enforcement():
    packet = ByngoPacket(
        packet_type = AI_TASK,
        zone        = "PUBLIC",
    )
    # AI_TASK not allowed in PUBLIC zone
    assert not packet.is_allowed_in_zone(0.0)
    # AI_PROBE allowed in PUBLIC zone
    packet.packet_type = AI_PROBE
    assert packet.is_allowed_in_zone(0.0)

# ---- Signing tests ----

def test_ed25519_sign_verify():
    priv, pub = derive_keypair("my-node", "my-secret")
    content   = "test-content-string"
    sig       = sign(content, priv)
    assert sig != ""
    assert verify(content, sig, pub)

def test_ed25519_wrong_key_fails():
    priv, pub   = derive_keypair("node-A", "secret-A")
    _, wrong_pub = derive_keypair("node-B", "secret-B")
    sig = sign("content", priv)
    assert not verify("content", sig, wrong_pub)

def test_deterministic_keypair():
    priv1, pub1 = derive_keypair("same-node", "same-secret")
    priv2, pub2 = derive_keypair("same-node", "same-secret")
    assert priv1 == priv2
    assert pub1  == pub2

# ---- Tier config tests ----

def test_all_tiers_defined():
    for tier in ["T1_X86", "T1_ARM64", "T2_ARM64", "T3_ARM32"]:
        assert tier in TIER_CONFIGS
        cfg = TIER_CONFIGS[tier]
        assert "max_concurrent_tasks" in cfg
        assert "model_tier" in cfg
        assert "allowed_types" in cfg

def test_tier_task_limits():
    assert TIER_CONFIGS["T1_X86"]["max_concurrent_tasks"]  == 8
    assert TIER_CONFIGS["T3_ARM32"]["max_concurrent_tasks"] == 1

def test_edge_tier_restricted():
    edge = TIER_CONFIGS["T3_ARM32"]
    assert AI_TASK not in edge["allowed_types"]
    assert AI_PROBE in edge["allowed_types"]

# ---- OfflineSync + VectorClock integration ----

def test_offline_queue_flush_order():
    sync = OfflineSync("node-test")
    sync.queue_update(AI_KNOW, {"seq": 1, "data": "first"})
    sync.queue_update(AI_KNOW, {"seq": 2, "data": "second"})
    sync.queue_update(AI_SYNC, {"seq": 3, "data": "third"})
    assert sync.stats()["queued"] == 3

    class MockTransport:
        def __init__(self): self.sent = []
        async def broadcast(self, pkt): self.sent.append(pkt)

    transport = MockTransport()
    sent = asyncio.run(sync.flush(transport))
    assert sent == 3
    assert sync.stats()["queued"] == 0

def test_vector_clock_causal_order():
    vc = VectorClock("node-A")
    c1 = vc.tick()
    c2 = vc.tick()
    c3 = vc.tick()
    assert vc.happens_before(c1, c2)
    assert vc.happens_before(c2, c3)
    assert vc.happens_before(c1, c3)
    assert not vc.happens_before(c3, c1)

# ---- TrustStore integration ----

def test_trust_zone_progression():
    import tempfile
    path  = tempfile.mktemp(suffix=".json")
    store = TrustStore(path=path)

    # Start in PUBLIC
    assert store.zone("node-X") == "PUBLIC"

    # Build to TRUSTED
    store.update("node-X", 0.7)
    assert store.zone("node-X") == "TRUSTED"

    # Reach PERSONAL
    store.update("node-X", 0.3)
    assert store.zone("node-X") == "PERSONAL"

    # Save and reload
    store.save()
    store2 = TrustStore(path=path)
    assert store2.zone("node-X") == "PERSONAL"
    os.unlink(path)

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
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
