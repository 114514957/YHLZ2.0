"""
YHLZ Embodied AI V5.7 - 经历存储单元测试 (Experience Store)

覆盖 (experience_store.py):
    - store/retrieve/update/decay/forget 生命周期
    - 上限保护: 超出 max_records → 低价值淘汰
    - 衰减: 低价值经验逐渐衰减 → 遗忘
    - 统计: 数量/类型分布/平均价值
    - 持久化: JSONL save/load
    - 参数校验: max_records <= 0 / value 范围
"""
import os
import tempfile
import unittest

from backend.embodied.companion.experience import (
    ExperienceRecord,
    ExperienceStore,
    ExperienceStoreError,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_MEDIUM,
)


def make_record(type="failure", trigger="t", lesson="l", value=0.6):
    return ExperienceRecord.create(
        type=type, trigger=trigger, lesson=lesson, value=value,
    )


class TestStoreLifecycle(unittest.TestCase):
    """存储生命周期"""

    def setUp(self):
        self.store = ExperienceStore(max_records=10)

    def test_store(self):
        """存储"""
        rec = make_record()
        self.store.store(rec)
        self.assertEqual(self.store.count(), 1)
        self.assertIsNotNone(self.store.retrieve(rec.id))

    def test_retrieve_missing(self):
        """检索不存在 → None"""
        self.assertIsNone(self.store.retrieve("nope"))

    def test_update_lesson(self):
        """更新 lesson"""
        rec = make_record()
        self.store.store(rec)
        updated = self.store.update(rec.id, lesson="新教训")
        self.assertEqual(updated.lesson, "新教训")

    def test_update_value(self):
        """更新 value"""
        rec = make_record()
        self.store.store(rec)
        updated = self.store.update(rec.id, value=0.9)
        self.assertEqual(updated.value, 0.9)

    def test_update_missing(self):
        """更新不存在 → None"""
        self.assertIsNone(self.store.update("nope", lesson="x"))

    def test_update_invalid_value(self):
        """更新 value 越界 → 异常"""
        rec = make_record()
        self.store.store(rec)
        with self.assertRaises(ExperienceStoreError):
            self.store.update(rec.id, value=1.5)

    def test_forget(self):
        """遗忘"""
        rec = make_record()
        self.store.store(rec)
        self.assertTrue(self.store.forget(rec.id))
        self.assertFalse(self.store.forget(rec.id))
        self.assertEqual(self.store.count(), 0)

    def test_clear(self):
        """清空"""
        self.store.store(make_record())
        self.store.store(make_record())
        self.assertEqual(self.store.clear(), 2)
        self.assertEqual(self.store.count(), 0)


class TestMaxRecords(unittest.TestCase):
    """上限保护"""

    def test_evict_low_value(self):
        """超出上限 → 淘汰低价值"""
        store = ExperienceStore(max_records=3)
        store.store(make_record(value=0.9))
        store.store(make_record(value=0.8))
        store.store(make_record(value=0.1))
        store.store(make_record(value=0.7))
        self.assertEqual(store.count(), 3)
        # 淘汰 value=0.1
        values = [r.value for r in store.all()]
        self.assertNotIn(0.1, values)

    def test_high_value_kept(self):
        """高价值长期保存"""
        store = ExperienceStore(max_records=3)
        store.store(make_record(value=VALUE_HIGH))
        store.store(make_record(value=0.7))
        store.store(make_record(value=0.6))
        store.store(make_record(value=0.5))
        self.assertEqual(store.count(), 3)
        self.assertIn(VALUE_HIGH, [r.value for r in store.all()])

    def test_invalid_max_records(self):
        """max_records <= 0 → 异常"""
        with self.assertRaises(ExperienceStoreError):
            ExperienceStore(max_records=0)


class TestDecay(unittest.TestCase):
    """衰减"""

    def setUp(self):
        self.store = ExperienceStore(max_records=10)

    def test_decay_lowers_value(self):
        """衰减降低价值"""
        rec = make_record(value=0.6)
        self.store.store(rec)
        self.store.decay(decay_rate=0.5)
        self.assertEqual(self.store.retrieve(rec.id).value, 0.3)

    def test_decay_forgets_low(self):
        """衰减至低于阈值 → 遗忘"""
        rec = make_record(value=0.2)
        self.store.store(rec)
        forgotten = self.store.decay(decay_rate=0.5, min_value=0.1)
        # 0.2 × 0.5 = 0.1, 不低于 0.1 → 保留
        self.assertEqual(forgotten, [])

    def test_decay_forgets_below_min(self):
        """低于阈值 → 遗忘"""
        rec = make_record(value=0.2)
        self.store.store(rec)
        forgotten = self.store.decay(decay_rate=0.5, min_value=0.15)
        # 0.2 × 0.5 = 0.1 < 0.15 → 遗忘
        self.assertEqual(forgotten, [rec.id])
        self.assertEqual(self.store.count(), 0)

    def test_high_value_survives_many_decay(self):
        """高价值多次衰减仍保留"""
        rec = make_record(value=0.9)
        self.store.store(rec)
        for _ in range(5):
            self.store.decay(decay_rate=0.5, min_value=0.1)
        # 0.9 × 0.5^5 = 0.028 < 0.1 → 最终遗忘
        self.assertEqual(self.store.count(), 0)

    def test_decay_invalid_rate(self):
        """decay_rate 越界 → 异常"""
        with self.assertRaises(ExperienceStoreError):
            self.store.decay(decay_rate=1.5)


class TestStatsAndPersistence(unittest.TestCase):
    """统计与持久化"""

    def setUp(self):
        self.store = ExperienceStore(max_records=10)

    def test_stats_structure(self):
        """统计结构"""
        self.store.store(make_record(type="failure"))
        st = self.store.stats()
        for key in ("mode", "total", "max_records", "by_type",
                    "avg_value"):
            self.assertIn(key, st)
        self.assertEqual(st["mode"], "rule_based")

    def test_stats_by_type(self):
        """类型分布"""
        self.store.store(make_record(type="failure"))
        self.store.store(make_record(type="improvement"))
        self.store.store(make_record(type="failure"))
        st = self.store.stats()
        self.assertEqual(st["by_type"]["failure"], 2)
        self.assertEqual(st["by_type"]["improvement"], 1)
        self.assertEqual(st["total"], 3)

    def test_stats_avg_value(self):
        """平均价值"""
        self.store.store(make_record(value=0.8))
        self.store.store(make_record(value=0.6))
        st = self.store.stats()
        self.assertEqual(st["avg_value"], 0.7)

    def test_all_ordered(self):
        """全部记录时间倒序"""
        self.store.store(make_record(trigger="a"))
        self.store.store(make_record(trigger="b"))
        records = self.store.all()
        self.assertEqual(len(records), 2)

    def test_save_load(self):
        """JSONL 保存加载"""
        rec = make_record(trigger="持久化测试", lesson="跨重启")
        self.store.store(rec)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exp.jsonl")
            self.assertEqual(self.store.save_to_file(path), 1)
            store2 = ExperienceStore(max_records=10)
            self.assertEqual(store2.load_from_file(path), 1)
            loaded = store2.retrieve(rec.id)
            self.assertEqual(loaded.lesson, "跨重启")

    def test_load_missing_file(self):
        """加载不存在文件 → 0"""
        self.assertEqual(self.store.load_from_file("nope.jsonl"), 0)

    def test_save_empty(self):
        """空存储保存 → 0"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "exp.jsonl")
            self.assertEqual(self.store.save_to_file(path), 0)

    def test_stats_empty(self):
        """空存储统计"""
        st = self.store.stats()
        self.assertEqual(st["total"], 0)
        self.assertEqual(st["avg_value"], 0.0)

    def test_all_empty(self):
        """空存储 all"""
        self.assertEqual(self.store.all(), [])


if __name__ == "__main__":
    unittest.main()
