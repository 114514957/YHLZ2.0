"""
YHLZ Embodied AI V6.4 - 经验来源与多模态对象单元测试 (Provenance & Multimodal)

覆盖 (experience/):
    - Provenance: 来源链结构/校验/批准方
    - MultimodalExperience: 统一对象/模态/来源/校验
    - PerceptionStatsSnapshot: 收集/恢复/兼容
"""
import unittest

from backend.embodied.companion.experience import (
    APPROVERS,
    EXPERIENCE_SOURCES,
    MODALITIES,
    MultimodalError,
    MultimodalExperience,
    Provenance,
    ProvenanceError,
)
from backend.embodied.companion.perception import (
    PerceptionStatsSnapshot,
)


def make_prov(**over):
    p = {
        "origin": "vision",
        "source_event": "pe_1",
        "verification_score": 0.9,
        "reflection_reason": "综合评估通过",
        "approved_by": "memory_gate",
    }
    p.update(over)
    return p


class TestProvenance(unittest.TestCase):
    """经验来源链"""

    def test_create(self):
        p = Provenance.create(**make_prov())
        self.assertTrue(p.provenance_id.startswith("prov_"))
        self.assertEqual(p.origin, "vision")

    def test_to_dict(self):
        p = Provenance.create(**make_prov())
        d = p.to_dict()
        for key in ("provenance_id", "origin", "source_event",
                    "verification_score", "reflection_reason",
                    "approved_by", "timestamp"):
            self.assertIn(key, d)

    def test_validate_ok(self):
        p = Provenance.create(**make_prov())
        ok, reason = p.validate()
        self.assertTrue(ok)

    def test_empty_origin_invalid(self):
        p = Provenance(**{**make_prov(), "origin": ""})
        ok, reason = p.validate()
        self.assertFalse(ok)
        self.assertIn("origin", reason)

    def test_bad_score_invalid(self):
        p = Provenance(**{**make_prov(), "verification_score": 1.5})
        ok, reason = p.validate()
        self.assertFalse(ok)

    def test_bad_approver_invalid(self):
        p = Provenance(**{**make_prov(), "approved_by": "hacker"})
        ok, reason = p.validate()
        self.assertFalse(ok)

    def test_create_invalid_raises(self):
        with self.assertRaises(ProvenanceError):
            Provenance.create(**{**make_prov(), "origin": ""})

    def test_approvers_whitelist(self):
        for a in ("memory_gate", "reflection", "user", "system"):
            self.assertIn(a, APPROVERS)

    def test_timestamp(self):
        p = Provenance.create(**make_prov())
        self.assertGreater(p.timestamp, 0.0)

    def test_source_event_kept(self):
        p = Provenance.create(**make_prov())
        self.assertEqual(p.source_event, "pe_1")


class TestMultimodalExperience(unittest.TestCase):
    """多模态经验对象"""

    def test_create(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"],
            meaning="屏幕任务清单", confidence=0.9,
            impact="任务参考", provenance=make_prov(),
        )
        self.assertTrue(e.experience_id.startswith("mexp_"))

    def test_to_dict_structure(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"],
            meaning="m", confidence=0.9, impact="i",
            provenance=make_prov(),
        )
        d = e.to_dict()
        for key in ("id", "source", "modalities", "meaning",
                    "confidence", "impact", "provenance",
                    "timestamp"):
            self.assertIn(key, d)

    def test_validate_ok(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision"],
            meaning="m", confidence=0.9,
            provenance=make_prov(),
        )
        ok, reason = e.validate()
        self.assertTrue(ok)

    def test_no_provenance_invalid(self):
        e = MultimodalExperience(
            source="vision", modalities=["vision"],
            meaning="m", confidence=0.9,
        )
        ok, reason = e.validate()
        self.assertFalse(ok)
        self.assertIn("provenance", reason)

    def test_bad_source_invalid(self):
        e = MultimodalExperience(
            source="hacker", modalities=["vision"],
            meaning="m", confidence=0.9, provenance=make_prov(),
        )
        ok, reason = e.validate()
        self.assertFalse(ok)

    def test_empty_modalities_invalid(self):
        e = MultimodalExperience(
            source="vision", modalities=[], meaning="m",
            confidence=0.9, provenance=make_prov(),
        )
        ok, reason = e.validate()
        self.assertFalse(ok)

    def test_bad_modality_invalid(self):
        e = MultimodalExperience(
            source="vision", modalities=["smell"], meaning="m",
            confidence=0.9, provenance=make_prov(),
        )
        ok, reason = e.validate()
        self.assertFalse(ok)

    def test_bad_confidence_invalid(self):
        e = MultimodalExperience(
            source="vision", modalities=["vision"], meaning="m",
            confidence=1.5, provenance=make_prov(),
        )
        ok, reason = e.validate()
        self.assertFalse(ok)

    def test_create_invalid_raises(self):
        with self.assertRaises(MultimodalError):
            MultimodalExperience.create(
                source="vision", modalities=[], meaning="m",
                confidence=0.9, provenance=make_prov(),
            )

    def test_modalities_whitelist(self):
        for m in ("vision", "audio", "text", "interaction"):
            self.assertIn(m, MODALITIES)

    def test_sources_whitelist(self):
        for s in ("vision", "audio", "text", "interaction",
                  "creative", "reflection", "memory_gate"):
            self.assertIn(s, EXPERIENCE_SOURCES)

    def test_audio_experience(self):
        e = MultimodalExperience.create(
            source="audio", modalities=["audio"],
            meaning="语音指令", confidence=0.8,
            provenance=make_prov(origin="audio"),
        )
        self.assertEqual(e.source, "audio")

    def test_text_experience(self):
        e = MultimodalExperience.create(
            source="text", modalities=["text"],
            meaning="用户文本", confidence=0.9,
            provenance=make_prov(origin="text"),
        )
        ok, reason = e.validate()
        self.assertTrue(ok)

    def test_interaction_experience(self):
        e = MultimodalExperience.create(
            source="interaction", modalities=["interaction"],
            meaning="互动记录", confidence=0.7,
            provenance=make_prov(origin="interaction"),
        )
        ok, reason = e.validate()
        self.assertTrue(ok)

    def test_multi_modality(self):
        e = MultimodalExperience.create(
            source="vision", modalities=["vision", "text"],
            meaning="图文信息", confidence=0.85,
            provenance=make_prov(),
        )
        self.assertEqual(len(e.modalities), 2)


class TestPerceptionStatsSnapshot(unittest.TestCase):
    """感知统计快照"""

    def setUp(self):
        self.snap = PerceptionStatsSnapshot()

    def test_collect_structure(self):
        data = self.snap.collect(
            perception_stats={"event_count": 5,
                              "memory_candidate_count": 2,
                              "verification": {"approved": 1}},
            gate_stats={"candidate_count": 2,
                        "approved_count": 1,
                        "rejected_count": 1},
            evaluator_stats={"evaluated_count": 3,
                             "avg_reflection_score": 0.7},
            counterfactual_stats={"check_count": 2,
                                  "fails_count": 1},
        )
        for key in ("mode", "collected_at", "perception",
                    "memory_gate", "reflection", "counterfactual"):
            self.assertIn(key, data)

    def test_collect_counts(self):
        data = self.snap.collect(
            perception_stats={"event_count": 5},
            gate_stats={"approved_count": 2},
        )
        self.assertEqual(data["perception"]["event_count"], 5)
        self.assertEqual(data["memory_gate"]["approved_count"], 2)

    def test_collect_empty_defaults(self):
        data = self.snap.collect()
        self.assertEqual(data["perception"]["event_count"], 0)
        self.assertEqual(data["memory_gate"]["candidate_count"], 0)

    def test_disabled_collect(self):
        s = PerceptionStatsSnapshot(enabled=False)
        data = s.collect()
        self.assertEqual(data, {"enabled": False})

    def test_restore_ok(self):
        ok, reason = self.snap.restore({"perception": {}})
        self.assertTrue(ok)

    def test_restore_none_compat(self):
        """旧快照无该域 → 兼容跳过"""
        ok, reason = self.snap.restore(None)
        self.assertTrue(ok)
        self.assertIn("旧快照", reason)

    def test_stats(self):
        st = self.snap.stats()
        self.assertEqual(st["mode"], "rule_based")
        self.assertEqual(st["save_count"], 0)

    def test_mark_saved(self):
        self.snap.mark_saved()
        self.snap.mark_saved()
        st = self.snap.stats()
        self.assertEqual(st["save_count"], 2)

    def test_restore_count(self):
        self.snap.restore({})
        self.snap.restore(None)
        st = self.snap.stats()
        self.assertEqual(st["restore_count"], 2)

    def test_clear(self):
        self.snap.mark_saved()
        self.snap.restore({})
        n = self.snap.clear()
        self.assertEqual(n, 2)
        self.assertEqual(self.snap.stats()["save_count"], 0)


if __name__ == "__main__":
    unittest.main()
