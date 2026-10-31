"""S5 弹幕线测试：事件模型 / 事件库去重 / 选题调度 / 本地回放（stdlib unittest）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.connector_replay import ReplayConnector  # noqa: E402
from backend.live.event_store import EventStore  # noqa: E402
from backend.live.events import LiveEvent  # noqa: E402
from backend.live.scheduler import TopicScheduler  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def chat(event_id: str, text: str, sender: str = "u1", **extra) -> LiveEvent:
    data = {"event_id": event_id, "room_id": "r1", "kind": "chat",
            "sender_id": sender, "display_name": sender, "text": text}
    data.update(extra)
    return LiveEvent.from_dict(data)


class TestEvents(unittest.TestCase):
    def test_weak_id_generation(self):
        event = LiveEvent(event_id="", room_id="r1", sender_id="u1",
                          source_ts=123, text="你好", id_quality="weak")
        self.assertTrue(event.event_id.startswith("weak:"))
        self.assertEqual(event.dedup_key, f"bilibili:r1:{event.event_id}")

    def test_bad_kind_rejected(self):
        with self.assertRaises(ValueError):
            chat("e1", "hi", kind="unknown")


class TestEventStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"
        self.clock = FakeClock()
        self.store = EventStore(path=self.path, hot_capacity=2, time_fn=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_native_duplicate_dropped(self):
        event = chat("e1", "你好")
        first = self.store.ingest(event)
        second = self.store.ingest(event)
        self.assertTrue(first["accepted"])
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(self.store.summary()["counters"]["dup_dropped"], 1)
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_weak_short_window(self):
        event = LiveEvent(event_id="", room_id="r1", sender_id="u1", source_ts=1,
                          text="刷屏", id_quality="weak")
        first = self.store.ingest(event)
        second = self.store.ingest(event)
        self.assertTrue(first["accepted"])
        self.assertFalse(second["accepted"])
        self.clock.advance(11)
        third = self.store.ingest(event)
        self.assertTrue(third["accepted"])

    def test_hot_queue_bounded(self):
        for i in range(5):
            self.store.ingest(chat(f"e{i}", f"消息{i}", sender=f"u{i}"))
        self.assertEqual(len(self.store.recent_raw(10)), 2)
        self.assertEqual(self.store.recent_raw(1)[0]["text"], "消息4")


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.sched = TopicScheduler(time_fn=self.clock)

    def test_basic_pick(self):
        self.sched.offer(chat("e1", "元亨在吗"))
        turn = self.sched.pick()
        self.assertEqual(turn["kind"], "reply")
        self.assertEqual(turn["topic_text"], "元亨在吗")
        self.assertIsNone(self.sched.pick())

    def test_owner_priority_first(self):
        self.sched.offer(chat("e1", "普通问题"))
        self.clock.advance(0.5)
        owner = chat("e2", "元亨，自检", sender="owner", priority="owner")
        self.sched.offer(owner)
        turn = self.sched.pick()
        self.assertEqual(turn["priority"], "owner")
        self.assertEqual(turn["topic_text"], "元亨，自检")

    def test_aggregation_same_question(self):
        self.sched.offer(chat("e1", "你是真人吗", sender="u1"))
        self.clock.advance(0.3)
        self.sched.offer(chat("e2", "你是真人吗？", sender="u2"))
        self.assertEqual(self.sched.counters["coalesced"], 1)
        turn = self.sched.pick()
        self.assertEqual(turn["source_count"], 2)

    def test_ttl_expiry(self):
        sched = TopicScheduler(time_fn=self.clock, ttl_s=30, cold_idle_s=300)
        sched.offer(chat("e1", "会过期的消息"))
        self.clock.advance(31)
        self.assertIsNone(sched.pick())
        self.assertEqual(sched.counters["expired"], 1)

    def test_capacity_drop(self):
        sched = TopicScheduler(time_fn=self.clock, capacity=2, ttl_s=300)
        sched.offer(chat("e1", "一", sender="u1"))
        sched.offer(chat("e2", "二", sender="u2"))
        sched.offer(chat("e3", "三", sender="u3"))
        self.assertEqual(sched.counters["dropped_capacity"], 1)
        self.assertEqual(sched.summary()["pending"], 2)

    def test_cold_topic_rate_limited(self):
        self.sched.offer(chat("e1", "一句话"))
        self.clock.advance(31)
        first = self.sched.pick()
        self.assertEqual(first["kind"], "cold")
        self.assertIsNone(self.sched.pick())
        self.clock.advance(91)
        second = self.sched.pick()
        self.assertEqual(second["kind"], "cold")

    def test_turn_sources_capped(self):
        for i in range(5):
            self.clock.advance(0.1)
            self.sched.offer(chat(f"e{i}", "同一人连发", sender="u1"))
        turn = self.sched.pick()
        self.assertLessEqual(turn["source_count"], 3)


class TestReplay(unittest.TestCase):
    def test_replay_report_and_duplicates(self):
        self.clock = FakeClock()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = EventStore(path=Path(tmp.name) / "e.jsonl", time_fn=self.clock)
        sched = TopicScheduler(time_fn=self.clock, ttl_s=300)
        connector = ReplayConnector(store, sched, speed=1.0,
                                    pick_interval_ms=100, sleep_fn=lambda s: None)
        items = [
            {"offset_ms": 0, "event": {"event_id": "d1", "room_id": "r1",
                                       "sender_id": "u1", "display_name": "A",
                                       "text": "第一条"}},
            {"offset_ms": 500, "event": {"event_id": "d1", "room_id": "r1",
                                         "sender_id": "u1", "display_name": "A",
                                         "text": "第一条"}},
            {"offset_ms": 1500, "event": {"event_id": "d2", "room_id": "r1",
                                          "sender_id": "u2", "display_name": "B",
                                          "text": "第二条"}},
        ]
        report = connector.run(items)
        self.assertEqual(len(report["events"]), 3)
        self.assertEqual(report["dropped_dup"], 1)
        self.assertGreaterEqual(len(report["turns"]), 1)
        self.assertEqual(report["store"]["counters"]["received"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
