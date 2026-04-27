"""
ByngoNet -- Test Suite
Tests: AISP packets, signing, trust store, offline sync, vector clocks,
       transport zone enforcement, router, node identity, edge config.
All offline -- no real UDP sockets required.
"""
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def node_id():
    return hashlib.sha256(b"test-node").hexdigest()[:32]


@pytest.fixture
def keypair(node_id):
    from protocol.signing import derive_keypair
    return derive_keypair(node_id, "test-secret")


# ============================================================================
# Message Types
# ============================================================================

class TestMessageTypes:

    def test_packet_types_defined(self):
        from protocol.message_types import (
            AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE, PACKET_TYPES
        )
        assert AI_TASK   == "AI_TASK"
        assert AI_PROBE  == "AI_PROBE"
        assert len(PACKET_TYPES) == 5

    def test_security_zones(self):
        from protocol.message_types import SECURITY_ZONES, AI_PROBE, AI_TASK
        assert SECURITY_ZONES["PUBLIC"]["min_trust"] == 0.0
        assert AI_PROBE in SECURITY_ZONES["PUBLIC"]["allowed"]
        assert AI_TASK  not in SECURITY_ZONES["PUBLIC"]["allowed"]
        assert SECURITY_ZONES["TRUSTED"]["min_trust"] == 0.7
        assert AI_TASK in SECURITY_ZONES["TRUSTED"]["allowed"]


# ============================================================================
# AISP Packet
# ============================================================================

class TestByngoPacket:

    @pytest.fixture
    def packet(self, node_id):
        from protocol.packet import ByngoPacket
        from protocol.message_types import AI_PROBE
        return ByngoPacket(
            packet_type    = AI_PROBE,
            sender_node_id = node_id,
            target_node_id = "broadcast",
            payload        = {"node_id": node_id},
            zone           = "PUBLIC",
        )

    def test_packet_creation(self, packet, node_id):
        assert packet.packet_type    == "AI_PROBE"
        assert packet.sender_node_id == node_id
        assert packet.zone           == "PUBLIC"
        assert packet.hop_count      == 0
        assert packet.packet_id      != ""

    def test_to_bytes_and_back(self, packet):
        raw      = packet.to_bytes()
        restored = packet.__class__.from_bytes(raw)
        assert restored.packet_id      == packet.packet_id
        assert restored.packet_type    == packet.packet_type
        assert restored.sender_node_id == packet.sender_node_id
        assert restored.zone           == packet.zone

    def test_not_expired(self, packet):
        assert packet.is_expired() is False

    def test_expired_packet(self, node_id):
        from protocol.packet import ByngoPacket
        p = ByngoPacket(
            packet_type    = "AI_PROBE",
            sender_node_id = node_id,
            ttl            = 0,
        )
        time.sleep(0.01)
        assert p.is_expired() is True

    def test_is_allowed_in_zone_public(self, packet):
        assert packet.is_allowed_in_zone(0.0) is True   # AI_PROBE at trust 0

    def test_is_not_allowed_task_in_public(self, node_id):
        from protocol.packet import ByngoPacket
        p = ByngoPacket(
            packet_type    = "AI_TASK",
            sender_node_id = node_id,
            zone           = "PUBLIC",
        )
        assert p.is_allowed_in_zone(0.0) is False

    def test_sign_content_deterministic(self, packet):
        c1 = packet._sign_content()
        c2 = packet._sign_content()
        assert c1 == c2

    def test_repr(self, packet):
        r = repr(packet)
        assert "AI_PROBE" in r
        assert "PUBLIC"   in r

    def test_sign_and_verify(self, packet, keypair):
        priv, pub = keypair
        packet.sign(priv)
        assert packet.signature != ""
        assert packet.verify(pub) is True

    def test_verify_wrong_key_fails(self, packet, keypair, node_id):
        from protocol.signing import derive_keypair
        priv, pub   = keypair
        _, wrong_pub = derive_keypair("other-node", "other-secret")
        packet.sign(priv)
        assert packet.verify(wrong_pub) is False

    def test_verify_empty_signature_fails(self, packet, keypair):
        _, pub = keypair
        packet.signature = ""
        assert packet.verify(pub) is False


# ============================================================================
# Signing
# ============================================================================

class TestSigning:

    def test_derive_keypair_deterministic(self, node_id):
        from protocol.signing import derive_keypair
        priv1, pub1 = derive_keypair(node_id, "secret")
        priv2, pub2 = derive_keypair(node_id, "secret")
        assert priv1 == priv2
        assert pub1  == pub2

    def test_different_secrets_give_different_keys(self, node_id):
        from protocol.signing import derive_keypair
        _, pub1 = derive_keypair(node_id, "secret1")
        _, pub2 = derive_keypair(node_id, "secret2")
        assert pub1 != pub2

    def test_sign_and_verify_roundtrip(self, keypair):
        from protocol.signing import sign, verify
        priv, pub  = keypair
        content    = "test-content-to-sign"
        signature  = sign(content, priv)
        assert verify(content, signature, pub) is True

    def test_verify_wrong_content_fails(self, keypair):
        from protocol.signing import sign, verify
        priv, pub = keypair
        sig       = sign("original", priv)
        assert verify("tampered", sig, pub) is False

    def test_verify_empty_sig_returns_false(self, keypair):
        from protocol.signing import verify
        _, pub = keypair
        assert verify("content", "", pub) is False

    def test_sign_returns_hex_string(self, keypair):
        from protocol.signing import sign
        priv, _ = keypair
        sig     = sign("test", priv)
        assert isinstance(sig, str)
        assert len(sig) > 0


# ============================================================================
# Trust Store
# ============================================================================

class TestTrustStore:

    @pytest.fixture
    def store(self, tmp_dir):
        from protocol.trust_store import TrustStore
        return TrustStore(path=str(tmp_dir / "trust.json"))

    def test_get_unknown_node(self, store):
        assert store.get("unknown-node") == 0.0

    def test_update_increases_trust(self, store):
        updated = store.update("node-abc", 0.3)
        assert updated == pytest.approx(0.3)

    def test_update_capped_at_1(self, store):
        store.update("node-abc", 0.9)
        updated = store.update("node-abc", 0.5)
        assert updated == pytest.approx(1.0)

    def test_update_not_below_0(self, store):
        updated = store.update("node-abc", -2.0)
        assert updated == pytest.approx(0.0)

    def test_set_and_get(self, store):
        store.set("node-xyz", 0.85)
        assert store.get("node-xyz") == pytest.approx(0.85)

    def test_zone_public(self, store):
        store.set("low-trust", 0.3)
        assert store.zone("low-trust") == "PUBLIC"

    def test_zone_trusted(self, store):
        store.set("medium-trust", 0.75)
        assert store.zone("medium-trust") == "TRUSTED"

    def test_zone_personal(self, store):
        store.set("high-trust", 1.0)
        assert store.zone("high-trust") == "PERSONAL"

    def test_trusted_peers(self, store):
        store.set("trusted-1", 0.8)
        store.set("trusted-2", 0.9)
        store.set("public-1",  0.3)
        trusted = store.trusted_peers()
        assert "trusted-1" in trusted
        assert "trusted-2" in trusted
        assert "public-1"  not in trusted

    def test_peer_count(self, store):
        store.set("a", 0.5)
        store.set("b", 0.6)
        assert store.peer_count() == 2

    def test_all_peers(self, store):
        store.set("a", 0.5)
        store.set("b", 0.7)
        peers = store.all_peers()
        assert "a" in peers
        assert "b" in peers

    def test_save_and_reload(self, tmp_dir):
        from protocol.trust_store import TrustStore
        path = str(tmp_dir / "trust.json")
        s1 = TrustStore(path=path)
        s1.set("persistent-node", 0.88, addr="192.168.1.10:7422")
        s1.save()

        s2 = TrustStore(path=path)
        assert s2.get("persistent-node") == pytest.approx(0.88)

    def test_prune_stale(self, tmp_dir):
        from protocol.trust_store import TrustStore
        store = TrustStore(path=str(tmp_dir / "trust.json"))
        store._store["stale-node"] = {
            "trust":     0.5,
            "addr":      "",
            "last_seen": time.time() - 999999,
            "seen_count": 1,
        }
        store._store["fresh-node"] = {
            "trust":     0.7,
            "addr":      "",
            "last_seen": time.time(),
            "seen_count": 1,
        }
        pruned = store.prune_stale(max_age=3600)
        assert pruned == 1
        assert "stale-node" not in store._store
        assert "fresh-node" in store._store

    def test_repr(self, store):
        assert "TrustStore" in repr(store)


# ============================================================================
# Offline Sync / Vector Clock
# ============================================================================

class TestVectorClock:

    def test_tick_increments_own(self):
        from p2p.offline_sync import VectorClock
        vc = VectorClock("node-a")
        clock1 = vc.tick()
        clock2 = vc.tick()
        assert clock2["node-a"] == 2

    def test_update_merges_max(self):
        from p2p.offline_sync import VectorClock
        vc = VectorClock("node-a")
        vc.update({"node-b": 5, "node-a": 1})
        assert vc.clock["node-b"] == 5

    def test_happens_before(self):
        from p2p.offline_sync import VectorClock
        vc = VectorClock("node-a")
        a = {"node-a": 1, "node-b": 0}
        b = {"node-a": 2, "node-b": 0}
        assert vc.happens_before(a, b) is True
        assert vc.happens_before(b, a) is False

    def test_concurrent(self):
        from p2p.offline_sync import VectorClock
        vc = VectorClock("node-a")
        a = {"node-a": 2, "node-b": 1}
        b = {"node-a": 1, "node-b": 2}
        assert vc.concurrent(a, b) is True


class TestOfflineSync:

    @pytest.fixture
    def sync(self, node_id):
        from p2p.offline_sync import OfflineSync
        return OfflineSync(node_id)

    def test_initial_state(self, sync):
        stats = sync.stats()
        assert stats["connected"] is False
        assert stats["queued"]    == 0

    def test_receive_sync_accepted(self, sync, node_id):
        from protocol.packet import ByngoPacket
        p = ByngoPacket(
            packet_type    = "AI_KNOW",
            sender_node_id = node_id,
            payload        = {"update_type": "model_weights", "data": "abc"},
        )
        assert sync.receive_sync(p) is True

    def test_receive_sync_duplicate_rejected(self, sync, node_id):
        from protocol.packet import ByngoPacket
        p = ByngoPacket(
            packet_type    = "AI_KNOW",
            sender_node_id = node_id,
            payload        = {"update_type": "model_weights", "data": "abc"},
        )
        sync.receive_sync(p)
        # Same payload -- should be rejected as duplicate
        p2 = ByngoPacket(
            packet_type    = "AI_KNOW",
            sender_node_id = node_id,
            payload        = {"update_type": "model_weights", "data": "abc"},
        )
        assert sync.receive_sync(p2) is False

    def test_receive_non_syncable_rejected(self, sync, node_id):
        from protocol.packet import ByngoPacket
        p = ByngoPacket(
            packet_type    = "AI_PROBE",
            sender_node_id = node_id,
            payload        = {},
        )
        assert sync.receive_sync(p) is False

    def test_queue_update(self, sync):
        sync.queue_update("AI_KNOW", {"update_type": "test", "data": "x"})
        assert sync.stats()["queued"] == 1

    def test_queue_non_syncable_ignored(self, sync):
        sync.queue_update("AI_PROBE", {"data": "x"})
        assert sync.stats()["queued"] == 0

    def test_queue_max_drops_oldest(self, sync):
        from p2p.offline_sync import MAX_QUEUE
        for i in range(MAX_QUEUE + 5):
            sync.queue_update("AI_KNOW", {"update_type": "test", "seq": i})
        assert sync.stats()["queued"] == MAX_QUEUE

    @pytest.mark.asyncio
    async def test_flush_sends_queued(self, sync):
        sync.queue_update("AI_KNOW", {"update_type": "test", "data": "flush_me"})
        mock_transport = AsyncMock()
        flushed = await sync.flush(mock_transport)
        assert flushed == 1
        mock_transport.broadcast.assert_called_once()
        assert sync.stats()["queued"] == 0

    @pytest.mark.asyncio
    async def test_flush_empty(self, sync):
        mock_transport = AsyncMock()
        flushed = await sync.flush(mock_transport)
        assert flushed == 0
        mock_transport.broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_drops_expired(self, sync):
        from p2p.offline_sync import QueuedPacket
        from protocol.packet import ByngoPacket
        # Manually add an expired packet
        p = ByngoPacket(packet_type="AI_KNOW", sender_node_id="test", payload={})
        qp = QueuedPacket(p, {})
        qp.queued_at = time.time() - 7200   # 2 hours ago -- expired
        sync._queue.append(qp)

        mock_transport = AsyncMock()
        flushed = await sync.flush(mock_transport)
        assert flushed == 0   # dropped, not sent

    def test_mark_connected(self, sync):
        mock_transport = MagicMock()
        sync.mark_connected(mock_transport)
        assert sync.stats()["connected"] is True

    def test_mark_disconnected(self, sync):
        mock_transport = MagicMock()
        sync.mark_connected(mock_transport)
        sync.mark_disconnected()
        assert sync.stats()["connected"] is False


# ============================================================================
# Router
# ============================================================================

class TestByngoRouter:

    @pytest.fixture
    def router(self, node_id):
        from protocol.router import ByngoRouter
        return ByngoRouter(node_id)

    def test_add_peer(self, router):
        router.add_peer("peer-abc", "192.168.1.5:7422", trust=0.5)
        assert "peer-abc" in router.peers
        assert router.get_trust("peer-abc") == 0.5

    def test_update_trust(self, router):
        router.add_peer("peer-abc", "192.168.1.5:7422", trust=0.5)
        router.update_trust("peer-abc", 0.2)
        assert router.get_trust("peer-abc") == pytest.approx(0.7)

    def test_trust_capped_at_1(self, router):
        router.add_peer("peer-abc", "192.168.1.5:7422", trust=0.9)
        router.update_trust("peer-abc", 0.5)
        assert router.get_trust("peer-abc") == pytest.approx(1.0)

    def test_trust_not_below_0(self, router):
        router.add_peer("peer-abc", "192.168.1.5:7422", trust=0.1)
        router.update_trust("peer-abc", -1.0)
        assert router.get_trust("peer-abc") == pytest.approx(0.0)

    def test_zone_public(self, router):
        router.add_peer("low", "1.2.3.4:7422", trust=0.3)
        assert router._get_zone("low") == "PUBLIC"

    def test_zone_trusted(self, router):
        router.add_peer("med", "1.2.3.4:7422", trust=0.75)
        assert router._get_zone("med") == "TRUSTED"

    def test_zone_personal(self, router):
        router.add_peer("high", "1.2.3.4:7422", trust=1.0)
        assert router._get_zone("high") == "PERSONAL"

    def test_register_handler(self, router):
        handler = AsyncMock()
        router.register_handler("AI_TASK", handler)
        assert router.handlers["AI_TASK"] is handler

    @pytest.mark.asyncio
    async def test_dispatch_creates_packet(self, router, node_id):
        router.add_peer("target-node", "1.2.3.4:7422", trust=0.0)
        packet = await router.dispatch("AI_PROBE", "target-node", {"key": "val"})
        assert packet.packet_type    == "AI_PROBE"
        assert packet.sender_node_id == node_id
        assert packet.target_node_id == "target-node"


# ============================================================================
# Node Identity
# ============================================================================

class TestNodeIdentity:

    def test_get_nodeid_missing_raises(self):
        from protocol.node_identity import get_nodeid
        with patch("builtins.open", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="NodeID driver not loaded"):
                get_nodeid()

    def test_get_nodeid_reads_file(self):
        from protocol.node_identity import get_nodeid
        with patch("builtins.open", MagicMock(return_value=MagicMock(
            __enter__=lambda s: MagicMock(read=lambda: "test-node-id\n"),
            __exit__=MagicMock(return_value=False),
        ))):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", return_value="test-node-id"):
                    nodeid = get_nodeid()
        assert nodeid == "test-node-id"

    def test_build_node_certificate(self):
        from protocol.node_identity import build_node_certificate
        from protocol.message_types import AI_PROBE, AI_TASK
        cert = build_node_certificate("node-abc", [AI_PROBE, AI_TASK])
        assert cert["node_id"]         == "node-abc"
        assert AI_PROBE in cert["capabilities"]
        assert "fingerprint" in cert
        assert cert["trust_score"]     == 0.0


# ============================================================================
# Edge Config
# ============================================================================

class TestEdgeConfig:

    def test_tier_configs_defined(self):
        from node.edge_config import TIER_CONFIGS
        assert "T1_X86"   in TIER_CONFIGS
        assert "T1_ARM64" in TIER_CONFIGS
        assert "T2_ARM64" in TIER_CONFIGS
        assert "T3_ARM32" in TIER_CONFIGS

    def test_t1_x86_max_tasks(self):
        from node.edge_config import TIER_CONFIGS
        assert TIER_CONFIGS["T1_X86"]["max_concurrent_tasks"] == 8

    def test_t3_arm32_limited(self):
        from node.edge_config import TIER_CONFIGS
        t3 = TIER_CONFIGS["T3_ARM32"]
        assert t3["max_concurrent_tasks"] == 1
        assert t3["default_zone"]         == "PUBLIC"

    def test_t1_allows_all_packet_types(self):
        from node.edge_config import TIER_CONFIGS
        from protocol.message_types import AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE
        allowed = TIER_CONFIGS["T1_X86"]["allowed_types"]
        for pt in [AI_TASK, AI_RESULT, AI_KNOW, AI_SYNC, AI_PROBE]:
            assert pt in allowed

    def test_t3_limited_packet_types(self):
        from node.edge_config import TIER_CONFIGS
        from protocol.message_types import AI_TASK
        allowed = TIER_CONFIGS["T3_ARM32"]["allowed_types"]
        assert AI_TASK not in allowed
