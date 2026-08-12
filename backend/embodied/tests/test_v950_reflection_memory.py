"""
YHLZ Embodied AI V9.5 - 反思循环与认知记忆审计单元测试 (Reflection & Memory)

覆盖:
    - ReflectionLoop: 反思/宪法检查/更新
    - CognitionMemory: 分类保存/验证过滤
    - CognitionAudit: 记录/回放
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.companion.meta_cognition import (
    CognitionAudit,
    CognitionMemory,
    ReflectionLoop,
)
from backend.embodied.companion.meta_cognition.cognition_memory import (
    MEMORY_CATEGORIES,
    CognitionMemoryError,
)


class TestReflectionLoop(unittest.TestCase):
    """认知反思"""

    def setUp(self):
        self.loop = ReflectionLoop(
            constitution=ConstitutionEngine(),
        )

    def test_reflect_structure(self):
        r = self.loop.reflect("经验", "分析", "优化方法")
        for key in ("reflection_id", "experience",
                    "analysis", "reflection", "proposal",
                    "constitution_ok", "validation", "update",
                    "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["reflection_id"].startswith("rf_"))

    def test_ok_adjustment(self):
        r = self.loop.reflect("经验", "分析", "优化记忆检索")
        self.assertTrue(r["validation"]["ok"])
        self.assertTrue(r["update"])

    def test_constitution_block(self):
        r = self.loop.reflect("经验", "分析", "修改使命")
        self.assertFalse(r["validation"]["ok"])
        self.assertFalse(r["constitution_ok"])

    def test_empty_adjustment(self):
        r = self.loop.reflect("经验", "分析", "")
        self.assertFalse(r["validation"]["ok"])
        self.assertIn("为空", r["validation"]["reason"])

    def test_proposal_method_level(self):
        r = self.loop.reflect("经验", "分析", "优化方法")
        self.assertTrue(r["proposal"]["method_level"])
        self.assertFalse(r["proposal"]["principle_level"])

    def test_reflection_text(self):
        r = self.loop.reflect("经验X", "分析Y")
        self.assertIn("经验X", r["reflection"])
        self.assertIn("分析Y", r["reflection"])

    def test_no_constitution_engine(self):
        loop = ReflectionLoop()
        r = loop.reflect("经验", "分析", "优化方法")
        self.assertTrue(r["constitution_ok"])

    def test_stats(self):
        self.loop.reflect("经验", "分析", "优化方法")
        self.loop.reflect("经验", "分析", "修改使命")
        stats = self.loop.stats()
        self.assertEqual(stats["reflection_count"], 2)
        self.assertEqual(stats["update_count"], 1)

    def test_history(self):
        self.loop.reflect("经验", "分析", "优化")
        h = self.loop.history()
        self.assertEqual(len(h), 1)
        self.assertIn("reflection", h[0])

    def test_disabled(self):
        loop = ReflectionLoop(enabled=False)
        r = loop.reflect("经验", "分析", "优化")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_clear(self):
        self.loop.reflect("经验", "分析", "优化")
        n = self.loop.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.loop.stats()[
            "reflection_count"], 0)


class TestCognitionMemory(unittest.TestCase):
    """认知记忆"""

    def setUp(self):
        self.memory = CognitionMemory()

    def test_save_validated(self):
        entry = self.memory.save(
            "认知经验", "cognitive_experience",
            validated=True,
        )
        self.assertTrue(entry["memory_id"].startswith("cog_"))
        self.assertEqual(entry["category"],
                         "cognitive_experience")

    def test_save_unvalidated_rejected(self):
        r = self.memory.save("经验", validated=False)
        self.assertFalse(r["ok"])
        self.assertIn("未验证", r["reason"])

    def test_save_all_categories(self):
        for cat in MEMORY_CATEGORIES:
            entry = self.memory.save(
                f"内容_{cat}", cat, validated=True,
            )
            self.assertEqual(entry["category"], cat)

    def test_invalid_category(self):
        with self.assertRaises(CognitionMemoryError):
            self.memory.save("x", "bogus", validated=True)

    def test_by_category(self):
        self.memory.save("e1", "cognitive_experience",
                         validated=True)
        self.memory.save("e2", "cognitive_experience",
                         validated=True)
        self.memory.save("err", "error_case",
                         validated=True)
        items = self.memory.by_category(
            "cognitive_experience")
        self.assertEqual(len(items), 2)

    def test_stats(self):
        self.memory.save("a", "cognitive_experience",
                         validated=True)
        self.memory.save("b", "error_case", validated=True)
        stats = self.memory.stats()
        self.assertEqual(stats["record_count"], 2)
        self.assertEqual(stats["by_category"][
            "error_case"], 1)

    def test_categories_constant(self):
        self.assertEqual(MEMORY_CATEGORIES,
                         ["cognitive_experience",
                          "error_case",
                          "optimization_strategy"])

    def test_clear(self):
        self.memory.save("a", validated=True)
        n = self.memory.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.memory.stats()[
            "record_count"], 0)


class TestCognitionAudit(unittest.TestCase):
    """认知审计"""

    def setUp(self):
        self.audit = CognitionAudit()

    def test_record_structure(self):
        entry = self.audit.record(
            task="t", evaluation="e", error="err",
            adjustment="adj",
        )
        for key in ("audit_id", "time", "task",
                    "evaluation", "error", "adjustment"):
            self.assertIn(key, entry)
        self.assertTrue(entry["audit_id"].startswith("mc_"))

    def test_report(self):
        self.audit.record(task="a", error="memory_error")
        self.audit.record(task="b", error="memory_error")
        report = self.audit.report()
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["by_error"][
            "memory_error"], 2)

    def test_replay(self):
        self.audit.record(task="a", evaluation="0.8")
        replay = self.audit.replay()
        self.assertEqual(replay["replay_count"], 1)
        seq = replay["sequence"][0]
        self.assertEqual(seq["task"], "a")

    def test_disabled(self):
        audit = CognitionAudit(enabled=False)
        entry = audit.record(task="a")
        self.assertEqual(entry, {})

    def test_stats(self):
        self.audit.record(task="a")
        self.assertEqual(self.audit.stats()[
            "record_count"], 1)

    def test_clear(self):
        self.audit.record(task="a")
        n = self.audit.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.audit.stats()[
            "record_count"], 0)


if __name__ == "__main__":
    unittest.main()
