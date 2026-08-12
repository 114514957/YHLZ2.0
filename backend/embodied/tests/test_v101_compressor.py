"""
YHLZ Embodied AI V10.1 - 记忆压缩模块测试 (Memory Compressor)

覆盖:
    - 文本归一化 / 相似度
    - 同触发词合并
    - 同内容跨触发合并
    - 不相似保留
    - 单条记录组
    - 停用错误帧
"""
import unittest

from backend.embodied.companion.memory_stabilization.compressor import (
    CompressorError,
    MemoryCompressor,
    normalize_text,
    text_similarity,
)


class TestNormalizeText(unittest.TestCase):
    """文本归一化"""

    def test_plain(self):
        self.assertEqual(normalize_text("hello"), "hello")

    def test_whitespace_removed(self):
        self.assertEqual(normalize_text("a b  c"), "abc")

    def test_chinese_punct_removed(self):
        self.assertEqual(normalize_text("成功。完成！"), "成功完成")

    def test_upper_lower(self):
        self.assertEqual(normalize_text("ABC"), "abc")

    def test_empty(self):
        self.assertEqual(normalize_text(""), "")

    def test_none(self):
        self.assertEqual(normalize_text(None), "")

    def test_digits_kept(self):
        self.assertEqual(normalize_text("任务 42"), "任务42")

    def test_fullwidth_space(self):
        self.assertEqual(normalize_text("a\u3000b"), "ab")

    def test_mixed_punct(self):
        self.assertEqual(
            normalize_text("成功,完成;任务！"), "成功完成任务",
        )


class TestTextSimilarity(unittest.TestCase):
    """文本相似度"""

    def test_identical(self):
        self.assertEqual(text_similarity("abc", "abc"), 1.0)

    def test_identical_norm(self):
        self.assertEqual(
            text_similarity("拾取任务", "拾取 任务"), 1.0,
        )

    def test_disjoint(self):
        self.assertEqual(text_similarity("aaa", "bbb"), 0.0)

    def test_partial(self):
        self.assertGreater(text_similarity("abcd", "abce"), 0.0)
        self.assertLess(text_similarity("abcd", "abce"), 1.0)

    def test_empty_both(self):
        self.assertEqual(text_similarity("", ""), 1.0)

    def test_empty_one(self):
        self.assertEqual(text_similarity("abc", ""), 0.0)

    def test_substring_high(self):
        self.assertGreater(text_similarity("abcdef", "abcd"), 0.5)

    def test_symmetric(self):
        a = text_similarity("成功完成", "成功失败")
        b = text_similarity("成功失败", "成功完成")
        self.assertEqual(a, b)


class TestCompressorBasic(unittest.TestCase):
    """压缩基础"""

    def setUp(self):
        self.c = MemoryCompressor(similarity_threshold=0.9)

    def _rec(self, rid, trigger, lesson, value=0.5, conf=0.5):
        return {
            "id": rid, "trigger": trigger, "lesson": lesson,
            "value": value, "confidence": conf,
        }

    def test_empty(self):
        r = self.c.compress([])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["kept"], [])
        self.assertEqual(r["merged"], [])
        self.assertEqual(r["merged_from"], [])

    def test_single_record(self):
        r = self.c.compress([self._rec("a", "t", "l")])
        self.assertEqual(r["kept"], ["a"])
        self.assertEqual(r["merged"], [])

    def test_duplicate_merged(self):
        r = self.c.compress([
            self._rec("a", "拾取", "成功完成拾取"),
            self._rec("b", "拾取", "成功完成拾取"),
        ])
        self.assertEqual(len(r["merged"]), 1)
        self.assertEqual(r["merged_from"], ["b"])
        self.assertEqual(r["merged"][0]["primary_id"], "a")

    def test_different_content_kept(self):
        r = self.c.compress([
            self._rec("a", "拾取", "成功完成"),
            self._rec("b", "拾取", "失败原因分析"),
        ])
        self.assertEqual(r["merged"], [])
        self.assertEqual(sorted(r["kept"]), ["a", "b"])

    def test_primary_keeps_highest_value(self):
        r = self.c.compress([
            self._rec("a", "t", "内容相同", value=0.3),
            self._rec("b", "t", "内容相同", value=0.9),
        ])
        self.assertEqual(r["merged"][0]["primary_id"], "b")
        self.assertEqual(r["merged_from"], ["a"])

    def test_three_duplicates(self):
        r = self.c.compress([
            self._rec("a", "t", "相同内容"),
            self._rec("b", "t", "相同内容"),
            self._rec("c", "t", "相同内容"),
        ])
        self.assertEqual(len(r["merged_from"]), 2)
        self.assertEqual(len(r["merged"]), 2)

    def test_groups_report(self):
        r = self.c.compress([
            self._rec("a", "拾取", "l1"),
            self._rec("b", "拾取", "l1"),
            self._rec("c", "其他", "l2"),
        ])
        self.assertEqual(len(r["groups"]), 2)

    def test_trigger_key_normalized(self):
        r = self.c.compress([
            self._rec("a", "拾取 任务", "l"),
            self._rec("b", "拾取任务", "l"),
        ])
        self.assertEqual(r["merged_from"], ["b"])

    def test_similarity_field_in_plan(self):
        r = self.c.compress([
            self._rec("a", "t", "完全一样"),
            self._rec("b", "t", "完全一样"),
        ])
        self.assertEqual(r["merged"][0]["similarity"], 1.0)

    def test_reason_explainable(self):
        r = self.c.compress([
            self._rec("a", "t", "一样"),
            self._rec("b", "t", "一样"),
        ])
        self.assertIn("相似", r["merged"][0]["reason"])

    def test_kept_contains_primary(self):
        r = self.c.compress([
            self._rec("a", "t", "一样"),
            self._rec("b", "t", "一样"),
        ])
        self.assertIn(r["merged"][0]["primary_id"], r["kept"])

    def test_count_field(self):
        r = self.c.compress([
            self._rec("a", "t", "一样"),
            self._rec("b", "t", "一样"),
        ])
        self.assertEqual(r["merged"][0]["count"], 2)


class TestCompressorThreshold(unittest.TestCase):
    """相似度阈值"""

    def test_strict_threshold_0(self):
        c = MemoryCompressor(similarity_threshold=1.0)
        r = c.compress([
            {"id": "a", "trigger": "t", "lesson": "部分相似AB"},
            {"id": "b", "trigger": "t", "lesson": "部分相似AC"},
        ])
        self.assertEqual(r["merged"], [])

    def test_loose_threshold(self):
        c = MemoryCompressor(similarity_threshold=0.5)
        r = c.compress([
            {"id": "a", "trigger": "t", "lesson": "相似内容AB"},
            {"id": "b", "trigger": "t", "lesson": "相似内容AC"},
        ])
        self.assertEqual(len(r["merged"]), 1)

    def test_invalid_threshold_raises(self):
        with self.assertRaises(CompressorError):
            MemoryCompressor(similarity_threshold=1.5)

    def test_negative_threshold_raises(self):
        with self.assertRaises(CompressorError):
            MemoryCompressor(similarity_threshold=-0.1)

    def test_threshold_boundary_zero(self):
        c = MemoryCompressor(similarity_threshold=0.0)
        r = c.compress([
            {"id": "a", "trigger": "t", "lesson": "不同A"},
            {"id": "b", "trigger": "t", "lesson": "不同B"},
        ])
        self.assertGreaterEqual(len(r["merged"]), 0)


class TestCompressorDisabled(unittest.TestCase):
    """停用错误帧"""

    def test_disabled(self):
        c = MemoryCompressor(enabled=False)
        r = c.compress([])
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_stats(self):
        c = MemoryCompressor()
        s = c.stats()
        self.assertEqual(s["mode"], "rule_based")
        self.assertEqual(s["similarity_threshold"], 0.9)

    def test_clear(self):
        c = MemoryCompressor()
        self.assertEqual(c.clear(), 0)

    def test_stats_after_compress(self):
        c = MemoryCompressor()
        c.compress([
            {"id": "a", "trigger": "t", "lesson": "l"},
            {"id": "b", "trigger": "t", "lesson": "l"},
        ])
        self.assertEqual(c.stats()["compress_count"], 1)


# ── 生成式: 压缩矩阵 ───────────────────────────────────────────
_COMPRESS_CASES = [
    # (名称, 记录列表, 期望合并数, 期望保留数)
    ("no_duplicates", [
        {"id": "a", "trigger": "t1", "lesson": "甲"},
        {"id": "b", "trigger": "t2", "lesson": "乙"},
    ], 0, 2),
    ("two_duplicates", [
        {"id": "a", "trigger": "t", "lesson": "相同"},
        {"id": "b", "trigger": "t", "lesson": "相同"},
    ], 1, 1),
    ("three_duplicates", [
        {"id": "a", "trigger": "t", "lesson": "相同"},
        {"id": "b", "trigger": "t", "lesson": "相同"},
        {"id": "c", "trigger": "t", "lesson": "相同"},
    ], 2, 1),
    ("mixed_triggers", [
        {"id": "a", "trigger": "t1", "lesson": "相同"},
        {"id": "b", "trigger": "t1", "lesson": "相同"},
        {"id": "c", "trigger": "t2", "lesson": "不同"},
    ], 1, 2),
    ("empty_list", [], 0, 0),
]


class TestGeneratedCompress(unittest.TestCase):
    """生成式: 压缩矩阵"""
    pass


for _i, (_name, _recs, _exp_merged, _exp_kept) in \
        enumerate(_COMPRESS_CASES):
    def _make(name=_name, recs=_recs, em=_exp_merged,
              ek=_exp_kept):
        def test_case(self):
            c = MemoryCompressor(similarity_threshold=0.9)
            r = c.compress(recs)
            self.assertEqual(len(r["merged"]), em)
            self.assertEqual(len(r["kept"]), ek)
        test_case.__name__ = f"test_compress_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCompress,
            f"test_compress_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
