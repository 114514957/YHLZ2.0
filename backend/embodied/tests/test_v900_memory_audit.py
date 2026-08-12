"""
YHLZ Embodied AI V9.0 - 研究记忆与审计单元测试 (Research Memory & Audit)

覆盖:
    - ResearchMemory: 过滤集成/等级/宪法
    - ResearchAudit: 记录/报告/回放
"""
import unittest

from backend.embodied.companion.research_engine import (
    ResearchAudit,
    ResearchMemory,
)


class TestResearchMemory(unittest.TestCase):
    """研究记忆"""

    def setUp(self):
        self.memory = ResearchMemory()

    def test_save_valid(self):
        entry = self.memory.save(
            "结论", "local", level="fact",
            validated=True, constitution_ok=True,
        )
        self.assertTrue(entry["memory_id"].startswith("rm_"))
        self.assertEqual(entry["level"], "fact")

    def test_save_unvalidated_rejected(self):
        r = self.memory.save(
            "结论", "local", level="fact",
            validated=False, constitution_ok=True,
        )
        self.assertFalse(r["ok"])
        self.assertIn("未验证", r["reason"])

    def test_save_speculation_rejected(self):
        r = self.memory.save(
            "结论", "unknown", level="speculation",
            validated=True, constitution_ok=True,
        )
        self.assertFalse(r["ok"])
        self.assertIn("推测禁止", r["reason"])

    def test_save_constitution_fail_rejected(self):
        r = self.memory.save(
            "结论", "local", level="fact",
            validated=True, constitution_ok=False,
        )
        self.assertFalse(r["ok"])
        self.assertIn("宪法", r["reason"])

    def test_save_uncertainty(self):
        entry = self.memory.save(
            "结论", "local", level="inference",
            validated=True, constitution_ok=True,
            uncertainty="部分不确定",
        )
        self.assertEqual(entry["uncertainty"], "部分不确定")

    def test_by_level(self):
        self.memory.save("f1", "local", level="fact",
                         validated=True,
                         constitution_ok=True)
        self.memory.save("f2", "local", level="fact",
                         validated=True,
                         constitution_ok=True)
        self.memory.save("e1", "local", level="evidence",
                         validated=True,
                         constitution_ok=True)
        facts = self.memory.by_level("fact")
        self.assertEqual(len(facts), 2)

    def test_stats(self):
        self.memory.save("f", "local", level="fact",
                         validated=True,
                         constitution_ok=True)
        self.memory.save("i", "local", level="inference",
                         validated=True,
                         constitution_ok=True)
        stats = self.memory.stats()
        self.assertEqual(stats["record_count"], 2)
        self.assertEqual(stats["by_level"]["fact"], 1)

    def test_clear(self):
        self.memory.save("f", "local", level="fact",
                         validated=True,
                         constitution_ok=True)
        n = self.memory.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.memory.stats()[
            "record_count"], 0)


class TestResearchAudit(unittest.TestCase):
    """研究审计"""

    def setUp(self):
        self.audit = ResearchAudit()

    def test_record_structure(self):
        entry = self.audit.record(
            question="q", source="local", method="loop",
            result="r", validation={"ok": True},
        )
        for key in ("audit_id", "time", "question",
                    "source", "method", "result",
                    "validation"):
            self.assertIn(key, entry)
        self.assertTrue(entry["audit_id"].startswith("ra_"))

    def test_report_counts(self):
        self.audit.record(question="a", source="local",
                          method="loop",
                          validation={"ok": True})
        self.audit.record(question="b", source="cloud",
                          method="analysis",
                          validation={"ok": False})
        report = self.audit.report()
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["by_source"]["local"], 1)
        self.assertEqual(report["by_method"]["loop"], 1)

    def test_report_recent_order(self):
        self.audit.record(question="旧", source="local",
                          method="loop")
        self.audit.record(question="新", source="local",
                          method="loop")
        report = self.audit.report()
        self.assertEqual(report["recent"][0]["question"],
                         "新")

    def test_replay(self):
        self.audit.record(question="q", source="local",
                          method="loop",
                          validation={"ok": True})
        replay = self.audit.replay()
        self.assertEqual(replay["replay_count"], 1)
        seq = replay["sequence"][0]
        self.assertEqual(seq["question"], "q")
        self.assertTrue(seq["validation_ok"])

    def test_replay_fields(self):
        self.audit.record(question="q", source="s",
                          method="m")
        seq = self.audit.replay()["sequence"][0]
        for key in ("audit_id", "time", "question",
                    "source", "method", "validation_ok"):
            self.assertIn(key, seq)

    def test_disabled(self):
        audit = ResearchAudit(enabled=False)
        entry = audit.record(question="q", source="s",
                             method="m")
        self.assertEqual(entry, {})

    def test_stats(self):
        self.audit.record(question="q", source="s",
                          method="m")
        self.assertEqual(self.audit.stats()[
            "record_count"], 1)

    def test_clear(self):
        self.audit.record(question="q", source="s",
                          method="m")
        n = self.audit.clear()
        self.assertEqual(n, 1)
        self.assertEqual(self.audit.stats()[
            "record_count"], 0)


if __name__ == "__main__":
    unittest.main()
