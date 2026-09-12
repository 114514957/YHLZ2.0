"""
YHLZ Embodied AI V10.1 - 记忆冲突检测模块测试 (Memory Conflict Detector)

覆盖:
    - 同触发正反结论标记
    - 无冲突 / 单条 / 空列表
    - 中性立场不误报
    - 停用错误帧 / 统计
"""
import unittest

from backend.embodied.companion.memory_stabilization.conflict_detector import (
    MemoryConflictDetector,
)


def _rec(rid, trigger, lesson, result=""):
    return {
        "id": rid, "trigger": trigger, "lesson": lesson,
        "result": result,
    }


class TestConflictBasic(unittest.TestCase):
    """冲突检测基础"""

    def setUp(self):
        self.d = MemoryConflictDetector()

    def test_empty(self):
        r = self.d.detect([])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["conflicts"], [])

    def test_single_record(self):
        r = self.d.detect([_rec("a", "拾取", "成功完成")])
        self.assertEqual(r["conflicts"], [])

    def test_same_stance_no_conflict(self):
        r = self.d.detect([
            _rec("a", "拾取", "成功完成"),
            _rec("b", "拾取", "成功且顺利"),
        ])
        self.assertEqual(r["conflicts"], [])

    def test_contradiction_detected(self):
        r = self.d.detect([
            _rec("a", "拾取", "成功完成拾取"),
            _rec("b", "拾取", "失败无法拾取"),
        ])
        self.assertEqual(len(r["conflicts"]), 1)
        c = r["conflicts"][0]
        self.assertEqual(c["conflict_type"], "contradiction")
        self.assertEqual(sorted(c["record_ids"]), ["a", "b"])

    def test_contradiction_two_vs_one(self):
        r = self.d.detect([
            _rec("a", "t", "成功完成"),
            _rec("b", "t", "成功执行"),
            _rec("c", "t", "失败告终"),
        ])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertIn("2 条", r["conflicts"][0]["detail"])
        self.assertIn("1 条", r["conflicts"][0]["detail"])

    def test_trigger_field(self):
        r = self.d.detect([
            _rec("a", "任务A", "成功"),
            _rec("b", "任务A", "失败"),
        ])
        self.assertEqual(r["conflicts"][0]["trigger"], "任务A")

    def test_reason_explainable(self):
        r = self.d.detect([
            _rec("a", "t", "成功"),
            _rec("b", "t", "失败"),
        ])
        self.assertIn("不自动删除", r["conflicts"][0]["reason"])

    def test_conflict_id_present(self):
        r = self.d.detect([
            _rec("a", "t", "成功"),
            _rec("b", "t", "失败"),
        ])
        self.assertTrue(r["conflicts"][0]["conflict_id"])

    def test_different_triggers_no_conflict(self):
        r = self.d.detect([
            _rec("a", "任务A", "成功"),
            _rec("b", "任务B", "失败"),
        ])
        self.assertEqual(r["conflicts"], [])

    def test_trigger_norm_matches(self):
        r = self.d.detect([
            _rec("a", "拾取 任务", "成功"),
            _rec("b", "拾取任务", "失败"),
        ])
        self.assertEqual(len(r["conflicts"]), 1)


class TestConflictStance(unittest.TestCase):
    """立场判定细则"""

    def setUp(self):
        self.d = MemoryConflictDetector()

    def test_positive_signal(self):
        self.assertEqual(self.d._stance(_rec("a", "t", "成功")), 1)

    def test_negative_signal(self):
        self.assertEqual(self.d._stance(_rec("a", "t", "失败")), -1)

    def test_neutral_no_signal(self):
        self.assertEqual(self.d._stance(_rec("a", "t", "普通记录")), 0)

    def test_empty_text(self):
        self.assertEqual(self.d._stance(_rec("a", "t", "")), 0)

    def test_english_positive(self):
        self.assertEqual(
            self.d._stance(_rec("a", "t", "task success")), 1,
        )

    def test_english_negative(self):
        self.assertEqual(
            self.d._stance(_rec("a", "t", "task failed")), -1,
        )

    def test_mixed_more_positive(self):
        self.assertEqual(
            self.d._stance(_rec("a", "t", "失败后改进成功完成")), 1,
        )

    def test_mixed_more_negative(self):
        self.assertEqual(
            self.d._stance(_rec("a", "t", "成功但被失败阻断无效")), -1,
        )

    def test_result_field_stance(self):
        self.assertEqual(
            self.d._stance(_rec("a", "t", "", result="失败")), -1,
        )


class TestConflictDisabled(unittest.TestCase):
    """停用与统计"""

    def test_disabled(self):
        d = MemoryConflictDetector(enabled=False)
        r = d.detect([])
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_stats(self):
        d = MemoryConflictDetector()
        s = d.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["detect_count"], 0)

    def test_stats_after_detect(self):
        d = MemoryConflictDetector()
        d.detect([])
        self.assertEqual(d.stats()["detect_count"], 1)

    def test_clear(self):
        d = MemoryConflictDetector()
        d.detect([])
        d.detect([])
        self.assertEqual(d.clear(), 2)


# ── 生成式: 冲突矩阵 ───────────────────────────────────────────
_CONFLICT_CASES = [
    # (名称, 记录列表, 期望冲突数)
    ("pos_neg", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "失败"},
    ], 1),
    ("all_pos", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "完成"},
    ], 0),
    ("all_neg", [
        {"id": "a", "trigger": "t", "lesson": "失败"},
        {"id": "b", "trigger": "t", "lesson": "无效"},
    ], 0),
    ("neutral_only", [
        {"id": "a", "trigger": "t", "lesson": "普通"},
        {"id": "b", "trigger": "t", "lesson": "日常"},
    ], 0),
    ("one_pos_one_neutral", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "日常"},
    ], 0),
    ("english_mixed", [
        {"id": "a", "trigger": "t", "lesson": "works fine"},
        {"id": "b", "trigger": "t", "lesson": "broken"},
    ], 1),
    ("three_way", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
        {"id": "b", "trigger": "t", "lesson": "成功"},
        {"id": "c", "trigger": "t", "lesson": "失败"},
    ], 1),
    ("single", [
        {"id": "a", "trigger": "t", "lesson": "成功"},
    ], 0),
]


class TestGeneratedConflicts(unittest.TestCase):
    """生成式: 冲突矩阵"""
    pass


for _i, (_name, _recs, _exp) in enumerate(_CONFLICT_CASES):
    def _make(name=_name, recs=_recs, exp=_exp):
        def test_case(self):
            d = MemoryConflictDetector()
            r = d.detect(recs)
            self.assertEqual(len(r["conflicts"]), exp)
        test_case.__name__ = f"test_conflict_{name}_{_i}"
        return test_case
    setattr(TestGeneratedConflicts,
            f"test_conflict_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
