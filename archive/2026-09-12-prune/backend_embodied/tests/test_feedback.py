"""
YHLZ Embodied AI V4.0 - 反馈系统单元测试

覆盖:
    - 添加 / 查询 (按 action_id / 结果过滤)
    - 统计指标 (成功率 / 失败率 / 平均耗时)
    - 边界: 上限 / 非法参数
    - 清空
"""
import unittest

from backend.embodied.feedback import FeedbackStore, FeedbackStoreError
from backend.embodied.schema import Feedback, FeedbackResult


class TestFeedbackStoreAdd(unittest.TestCase):

    def setUp(self):
        self.store = FeedbackStore(max_entries=10)

    def test_add_and_count(self):
        self.store.add(Feedback.create(action_id="a1", result="success"))
        self.assertEqual(self.store.count(), 1)

    def test_add_none_raises(self):
        with self.assertRaises(FeedbackStoreError):
            self.store.add(None)  # type: ignore[arg-type]

    def test_invalid_max_entries(self):
        with self.assertRaises(FeedbackStoreError):
            FeedbackStore(max_entries=0)
        with self.assertRaises(FeedbackStoreError):
            FeedbackStore(max_entries=-1)

    def test_max_entries_cap(self):
        store = FeedbackStore(max_entries=3)
        for i in range(5):
            store.add(Feedback.create(action_id=f"a{i}"))
        self.assertEqual(store.count(), 3)
        self.assertIsNone(store.get("a0"))
        self.assertIsNotNone(store.get("a4"))


class TestFeedbackStoreQuery(unittest.TestCase):

    def setUp(self):
        self.store = FeedbackStore()
        self.store.add(Feedback.create(action_id="a1", result="success", latency_ms=1.0))
        self.store.add(Feedback.create(action_id="a2", result="failure", error="boom"))
        self.store.add(Feedback.create(action_id="a3", result="success", latency_ms=3.0))

    def test_get_by_action_id(self):
        f = self.store.get("a2")
        self.assertEqual(f.result, "failure")
        self.assertEqual(f.error, "boom")

    def test_get_missing(self):
        self.assertIsNone(self.store.get("missing"))

    def test_query_latest_first(self):
        entries = self.store.query()
        self.assertEqual([e.action_id for e in entries], ["a3", "a2", "a1"])

    def test_query_filter_result(self):
        entries = self.store.query(result="success")
        self.assertEqual([e.action_id for e in entries], ["a3", "a1"])

    def test_query_limit(self):
        entries = self.store.query(limit=2)
        self.assertEqual(len(entries), 2)

    def test_query_dicts(self):
        d = self.store.query_dicts(result="failure")
        self.assertEqual(d[0]["action_id"], "a2")


class TestFeedbackStoreStats(unittest.TestCase):

    def test_empty_stats(self):
        stats = FeedbackStore().stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["success_rate"], 0.0)
        self.assertEqual(stats["avg_latency_ms"], 0.0)

    def test_stats_all_success(self):
        store = FeedbackStore()
        store.add(Feedback.create(result="success", latency_ms=2.0))
        store.add(Feedback.create(result="success", latency_ms=4.0))
        stats = store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["success_count"], 2)
        self.assertEqual(stats["success_rate"], 1.0)
        self.assertEqual(stats["failure_count"], 0)
        self.assertEqual(stats["avg_latency_ms"], 3.0)

    def test_stats_mixed(self):
        store = FeedbackStore()
        store.add(Feedback.create(result="success", latency_ms=1.0))
        store.add(Feedback.create(result="failure", latency_ms=2.0))
        store.add(Feedback.create(result="partial", latency_ms=3.0))
        store.add(Feedback.create(result="no_change", latency_ms=4.0))
        stats = store.stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["success_rate"], 0.25)
        self.assertEqual(stats["failure_rate"], 0.25)
        self.assertEqual(stats["partial_count"], 1)
        self.assertEqual(stats["no_change_count"], 1)
        self.assertEqual(stats["avg_latency_ms"], 2.5)

    def test_clear(self):
        store = FeedbackStore()
        store.add(Feedback.create(result="success"))
        n = store.clear()
        self.assertEqual(n, 1)
        self.assertEqual(store.count(), 0)

    def test_max_entries_property(self):
        store = FeedbackStore(max_entries=77)
        self.assertEqual(store.max_entries, 77)


if __name__ == "__main__":
    unittest.main()
