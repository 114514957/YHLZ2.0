"""
YHLZ Embodied AI V8.5 - 创造记忆与人机协同单元测试 (Memory & Collaboration)

覆盖:
    - CreativeMemory: 过滤保存/分类/统计
    - CollaborativeCreation: 人机角色分工
"""
import unittest

from backend.embodied.companion.creative_intelligence import (
    CollaborativeCreation,
    CreativeMemory,
)
from backend.embodied.companion.creative_intelligence.creative_memory import (
    MEMORY_STATUS,
    CreativeMemoryError,
)


class TestCreativeMemory(unittest.TestCase):
    """创造记忆"""

    def setUp(self):
        self.memory = CreativeMemory()

    def test_save_validated(self):
        entry = self.memory.save(
            "方案A", status="success", validated=True,
        )
        self.assertTrue(entry["memory_id"].startswith("cm_"))
        self.assertEqual(entry["status"], "success")

    def test_save_unvalidated_rejected(self):
        """Memory Filter: 未验证拒绝"""
        r = self.memory.save(
            "方案X", status="success", validated=False,
        )
        self.assertFalse(r["ok"])
        self.assertIn("未经验证", r["reason"])
        self.assertEqual(self.memory.stats()[
            "record_count"], 0)

    def test_save_failure_status(self):
        self.memory.save("失败方案", status="failure",
                         validated=True)
        self.assertEqual(self.memory.stats()[
            "by_status"]["failure"], 1)

    def test_save_falsified(self):
        self.memory.save("被证伪假设", status="falsified",
                         validated=True)
        self.assertEqual(self.memory.stats()[
            "by_status"]["falsified"], 1)

    def test_save_incomplete(self):
        self.memory.save("未完成想法", status="incomplete",
                         validated=True)
        self.assertEqual(self.memory.stats()[
            "by_status"]["incomplete"], 1)

    def test_invalid_status(self):
        with self.assertRaises(CreativeMemoryError):
            self.memory.save("x", status="bogus",
                             validated=True)

    def test_by_status(self):
        self.memory.save("成功1", status="success",
                         validated=True)
        self.memory.save("成功2", status="success",
                         validated=True)
        self.memory.save("失败1", status="failure",
                         validated=True)
        items = self.memory.by_status("success")
        self.assertEqual(len(items), 2)

    def test_by_status_invalid(self):
        with self.assertRaises(CreativeMemoryError):
            self.memory.by_status("bogus")

    def test_by_status_order(self):
        self.memory.save("旧", status="success",
                         validated=True)
        self.memory.save("新", status="success",
                         validated=True)
        items = self.memory.by_status("success")
        self.assertEqual(items[0]["content"], "新")

    def test_status_constant(self):
        self.assertEqual(MEMORY_STATUS,
                         ["success", "failure", "incomplete",
                          "falsified"])

    def test_validation_reason_recorded(self):
        entry = self.memory.save(
            "x", status="success", validated=True,
            validation_reason="验证通过",
        )
        self.assertEqual(entry["validation_reason"],
                         "验证通过")

    def test_stats(self):
        self.memory.save("a", status="success",
                         validated=True)
        self.memory.save("b", status="failure",
                         validated=True)
        stats = self.memory.stats()
        self.assertEqual(stats["record_count"], 2)
        self.assertEqual(stats["by_status"]["success"], 1)

    def test_clear(self):
        self.memory.save("a", status="success",
                         validated=True)
        n = self.memory.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.memory.stats()[
            "record_count"], 0)


class TestCollaborativeCreation(unittest.TestCase):
    """人机协同"""

    def setUp(self):
        self.cc = CollaborativeCreation()

    def test_create_structure(self):
        r = self.cc.create("人类想法", "AI分析", "目标")
        for key in ("collab_id", "combined", "human_part",
                    "ai_part", "goal", "role_division",
                    "mode"):
            self.assertIn(key, r)
        self.assertTrue(r["collab_id"].startswith("cc_"))

    def test_combined(self):
        r = self.cc.create("温暖", "一致性", "目标")
        self.assertIn("人类方向", r["combined"])
        self.assertIn("AI 扩展", r["combined"])

    def test_role_division(self):
        r = self.cc.create("a", "b")
        roles = r["role_division"]
        self.assertIn("价值判断", roles["human"])
        self.assertIn("信息整合", roles["ai"])

    def test_parts(self):
        r = self.cc.create("人类输入内容", "AI输出内容")
        self.assertEqual(r["human_part"], "人类输入内容")
        self.assertEqual(r["ai_part"], "AI输出内容")

    def test_disabled(self):
        cc = CollaborativeCreation(enabled=False)
        r = cc.create("a", "b")
        self.assertFalse(r["ok"])
        self.assertIn("停用", r["reason"])

    def test_stats(self):
        self.cc.create("a", "b")
        self.assertEqual(self.cc.stats()["collab_count"], 1)

    def test_history(self):
        self.cc.create("a", "b")
        h = self.cc.history()
        self.assertEqual(len(h), 1)
        self.assertIn("combined", h[0])

    def test_clear(self):
        self.cc.create("a", "b")
        n = self.cc.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.cc.stats()["collab_count"], 0)


if __name__ == "__main__":
    unittest.main()
