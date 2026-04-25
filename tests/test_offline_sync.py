"""Tests for OfflineSync — queue, flush, dedup, vector clock."""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from p2p.offline_sync import OfflineSync, VectorClock
from protocol.packet import ByngoPacket
from protocol.message_types import AI_KNOW, AI_SYNC, AI_TASK


def test_vector_clock_tick():
    vc = VectorClock("node-A")
    c1 = vc.tick()
    c2 = vc.tick()
    assert c2["node-A"] == 2
    assert c1["node-A"] == 1

def test_vector_clock_merge():
    vc = VectorClock("node-A")
    vc.tick()
    remote = {"node-B": 5, "node-C": 2}
    vc.update(remote)
    assert vc.clock["node-B"] == 5
    assert vc.clock["node-A"] == 2

def test_happens_before():
    vc = VectorClock("node-A")
    a = {"node-A": 1, "node-B": 0}
    b = {"node-A": 2, "node-B": 1}
    assert vc.happens_before(a, b)
    assert not vc.happens_before(b, a)

def test_concurrent():
    vc = VectorClock("node-A")
    a = {"node-A": 2, "node-B": 1}
    b = {"node-A": 1, "node-B": 2}
    assert vc.concurrent(a, b)

def test_queue_and_stats():
    sync = OfflineSync("node-test")
    sync.queue_update(AI_KNOW, {"update_type": "model_update", "data": "x"})
    sync.queue_update(AI_SYNC, {"update_type": "weight_sync", "data": "y"})
    stats = sync.stats()
    assert stats["queued"] == 2
    assert not stats["connected"]

def test_non_syncable_not_queued():
    sync = OfflineSync("node-test")
    sync.queue_update(AI_TASK, {"prompt": "hello"})
    assert sync.stats()["queued"] == 0

def test_receive_sync_dedup():
    sync = OfflineSync("node-test")
    packet = ByngoPacket(
        packet_type="AI_KNOW",
        sender_node_id="node-sender",
        payload={"update_type": "test", "data": "abc"},
    )
    assert sync.receive_sync(packet) == True
    assert sync.receive_sync(packet) == False

def test_receive_non_syncable():
    sync = OfflineSync("node-test")
    packet = ByngoPacket(
        packet_type="AI_TASK",
        sender_node_id="node-sender",
        payload={"prompt": "hello"},
    )
    assert sync.receive_sync(packet) == False

class MockTransport:
    def __init__(self):
        self.sent = []
    async def broadcast(self, packet):
        self.sent.append(packet)

def test_flush_sends_packets():
    sync = OfflineSync("node-test")
    sync.queue_update(AI_KNOW, {"update_type": "knowledge", "data": "val1"})
    sync.queue_update(AI_SYNC, {"update_type": "weights",   "data": "val2"})
    transport = MockTransport()
    sent = asyncio.run(sync.flush(transport))
    assert sent == 2
    assert len(transport.sent) == 2
    assert sync.stats()["queued"] == 0

def test_flush_empty():
    sync = OfflineSync("node-test")
    transport = MockTransport()
    sent = asyncio.run(sync.flush(transport))
    assert sent == 0

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
