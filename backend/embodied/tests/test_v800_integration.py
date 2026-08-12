"""
YHLZ Embodied AI V8.0 - 宪法引擎集成测试 (V8.0 Integration)

覆盖:
    - ConstitutionEngine 门面
    - Service API (companion_constitution_*)
    - HIL / Growth 联动
    - 五测试: Identity / Safety / Growth / Cloud Isolation / Audit
    - 向后兼容
"""
import unittest

from backend.embodied.companion.constitution import (
    ConstitutionEngine,
)
from backend.embodied.service import EmbodiedService


def setup_service(**extra):
    cfg = {
        "embodied_enabled": True,
        "companion_enabled": True,
    }
    cfg.update(extra)
    svc = EmbodiedService()
    svc.load_config(cfg)
    return svc


class TestConstitutionEngine(unittest.TestCase):
    """宪法引擎门面"""

    def setUp(self):
        self.engine = ConstitutionEngine()

    def test_review_allow(self):
        r = self.engine.review({"module": "growth",
                                "action_text": "正常行为",
                                "change": {}})
        self.assertEqual(r["decision"], "allow")
        self.assertIn("review_id", r)

    def test_review_block_identity(self):
        r = self.engine.review({"module": "growth",
                                "action_text": "修改使命",
                                "change": {"mission": "x"}})
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "identity")

    def test_review_records_ledger(self):
        self.engine.review({"module": "growth",
                            "action_text": "正常",
                            "change": {}})
        report = self.engine.ledger_report()
        self.assertEqual(report["total"], 1)

    def test_arbitrate(self):
        r = self.engine.arbitrate({
            "layers": ["expression", "identity"],
            "description": "冲突",
        })
        self.assertEqual(r["winner"], "identity")

    def test_arbitrate_records_ledger(self):
        self.engine.arbitrate({"layers": ["identity"]})
        self.assertEqual(self.engine.ledger_report()[
            "total"], 1)

    def test_validate_output(self):
        r = self.engine.validate_output("我是神")
        self.assertFalse(r["ok"])

    def test_validate_records_ledger(self):
        self.engine.validate_output("正常输出")
        self.assertEqual(self.engine.ledger_report()[
            "total"], 1)

    def test_propose_evolution(self):
        p = self.engine.propose_evolution("修改原则X", "理由")
        self.assertEqual(p["status"], "pending_review")
        self.assertFalse(p["auto_applied"])

    def test_evolution_decide(self):
        p = self.engine.propose_evolution("修改原则X")
        r = self.engine.evolution_decide(
            p["proposal_id"], "reject",
        )
        self.assertEqual(r["decision"], "reject")

    def test_principles_definition(self):
        d = self.engine.principles()
        self.assertEqual(len(d["principles"]), 4)

    def test_ledger_replay(self):
        self.engine.review({"module": "growth",
                            "action_text": "正常",
                            "change": {}})
        replay = self.engine.ledger_replay()
        self.assertEqual(replay["replay_count"], 1)

    def test_stats(self):
        self.engine.review({"module": "growth",
                            "action_text": "正常",
                            "change": {}})
        stats = self.engine.stats()
        self.assertEqual(stats["review_count"], 1)
        self.assertIn("ledger", stats)

    def test_disabled(self):
        engine = ConstitutionEngine(enabled=False)
        r = engine.review({"module": "growth",
                           "action_text": "修改使命",
                           "change": {"mission": "x"}})
        self.assertEqual(r["decision"], "allow")
        matched = [
            x for x in r["reasons"] if "停用" in x
        ]
        self.assertGreaterEqual(len(matched), 1)

    def test_clear(self):
        self.engine.review({"module": "growth",
                            "action_text": "正常",
                            "change": {}})
        n = self.engine.clear()
        self.assertGreater(n, 0)
        self.assertEqual(self.engine.stats()[
            "review_count"], 0)


class TestServiceAPI(unittest.TestCase):
    """Service API"""

    def setUp(self):
        self.svc = setup_service()

    def test_constitution_review_api(self):
        r = self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        self.assertEqual(r["decision"], "allow")

    def test_constitution_arbitrate_api(self):
        r = self.svc.companion_constitution_arbitrate({
            "layers": ["growth", "safety"],
        })
        self.assertEqual(r["winner"], "safety")

    def test_constitution_validate_api(self):
        r = self.svc.companion_constitution_validate_output(
            "我是神",
        )
        self.assertFalse(r["ok"])

    def test_constitution_principles_api(self):
        r = self.svc.companion_constitution_principles()
        self.assertEqual(len(r["principles"]), 4)

    def test_constitution_ledger_api(self):
        self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        r = self.svc.companion_constitution_ledger()
        self.assertGreaterEqual(r["total"], 1)

    def test_constitution_evolution_api(self):
        p = self.svc.companion_constitution_propose_evolution(
            "修改原则X", "测试",
        )
        r = self.svc.companion_constitution_evolution_decide(
            p["proposal_id"], "approve",
        )
        self.assertFalse(r["auto_applied"])

    def test_constitution_stats_api(self):
        self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        stats = self.svc.companion_constitution_stats()
        self.assertEqual(stats["review_count"], 1)

    def test_service_property(self):
        engine = self.svc.companion_constitution_engine
        self.assertIsNotNone(engine)
        self.assertTrue(engine.stats()["enabled"])

    def test_config_disabled(self):
        svc = setup_service(
            companion_constitution_enabled=False,
        )
        r = svc.companion_constitution_review({
            "module": "test",
            "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        self.assertEqual(r["decision"], "allow")


class TestHybridLinkage(unittest.TestCase):
    """HIL 联动"""

    def setUp(self):
        self.svc = setup_service()

    def test_hybrid_execute_has_constitution(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "设计"},
        )
        self.assertIn("constitution", r)
        self.assertEqual(
            r["constitution"]["review"]["decision"], "allow")
        self.assertIn("validation",
                      r["constitution"])

    def test_hybrid_constitution_validation(self):
        r = self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        validation = r["constitution"]["validation"]
        self.assertIn("knowledge_type", validation)

    def test_hybrid_link_disabled(self):
        svc = setup_service(
            companion_constitution_hybrid_link=False,
        )
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        self.assertNotIn("constitution", r)

    def test_hybrid_review_in_ledger(self):
        self.svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "x"},
        )
        report = self.svc.companion_constitution_ledger()
        self.assertGreaterEqual(report["total"], 1)


class TestGrowthLinkage(unittest.TestCase):
    """Growth 联动"""

    def setUp(self):
        self.svc = setup_service()
        mgr = self.svc.companion_experience
        for _ in range(4):
            mgr.store_from_event(
                success=True, trigger="生成工程Prompt",
                source="v800_test", action="a",
                result="成功",
            )
        for _ in range(3):
            mgr.store_from_event(
                success=False, trigger="拾取物体",
                source="v800_test", action="a",
                result="位置不匹配",
            )

    def test_growth_cycle_has_reviews(self):
        r = self.svc.companion_growth_cycle_run(
            trigger="manual",
        )
        self.assertIn("constitution_reviews", r)
        self.assertGreaterEqual(
            len(r["constitution_reviews"]), 1)

    def test_growth_review_allow(self):
        r = self.svc.companion_growth_cycle_run(
            trigger="manual",
        )
        for review in r["constitution_reviews"]:
            self.assertEqual(review["decision"], "allow")

    def test_growth_link_disabled(self):
        svc = setup_service(
            companion_constitution_growth_link=False,
        )
        mgr = svc.companion_experience
        for _ in range(4):
            mgr.store_from_event(
                success=True, trigger="生成工程Prompt",
                source="v800_test", action="a",
                result="成功",
            )
        r = svc.companion_growth_cycle_run(trigger="manual")
        self.assertNotIn("constitution_reviews", r)


class TestFiveTests(unittest.TestCase):
    """规格五测试"""

    def setUp(self):
        self.svc = setup_service()

    def test_identity_test(self):
        """Identity Test: 身份不可被低级模块修改"""
        r = self.svc.companion_constitution_review({
            "module": "expression",
            "action_text": "修改人格",
            "change": {"base_personality": "x"},
        })
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "identity")

    def test_safety_test(self):
        """Safety Test: 危险行为阻断"""
        r = self.svc.companion_constitution_review({
            "module": "growth",
            "action_text": "绕过安全检查",
            "change": {},
        })
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "safety")

    def test_growth_test(self):
        """Growth Test: 成长需要审批"""
        svc = setup_service()
        applier = svc.companion_growth_engine["applier"]
        self.assertFalse(applier._auto_apply)
        r = svc.companion_growth_apply(
            proposal={"id": "gp_x",
                      "type": "skill_improvement",
                      "description": "改进"},
            evaluation={"approved": False},
        )
        self.assertEqual(r["status"], "blocked")

    def test_cloud_isolation_test(self):
        """Cloud Isolation Test: 云端权限隔离"""
        r = self.svc.companion_constitution_review({
            "module": "hybrid",
            "action_text": "分析结果",
            "change": {},
            "cloud_result": {
                "provider": "cloud",
                "content": "建议修改权限设置",
                "temporary": True,
            },
        })
        self.assertEqual(r["decision"], "block")
        self.assertEqual(r["priority"], "intelligence")

    def test_audit_test(self):
        """Audit Test: 治理过程完整记录"""
        self.svc.companion_constitution_review({
            "module": "test", "action_text": "正常",
            "change": {},
        })
        self.svc.companion_constitution_arbitrate({
            "layers": ["identity"],
        })
        report = self.svc.companion_constitution_ledger(
            limit=0,
        )
        self.assertGreaterEqual(report["total"], 2)
        self.assertIn("test", report["by_module"])
        self.assertIn("constitution",
                      report["by_module"])


class TestCompatibility(unittest.TestCase):
    """向后兼容"""

    def setUp(self):
        self.svc = setup_service()

    def test_version_800(self):
        self.assertEqual(
            self.svc.report()["version"], "9.5.0")

    def test_old_presence_api(self):
        r = self.svc.companion_presence_update("success")
        self.assertEqual(r["expression"], "高兴")

    def test_old_hybrid_api(self):
        r = self.svc.companion_hybrid_route(
            {"type": "identity_query"},
        )
        self.assertEqual(r["route"], "LOCAL")

    def test_old_growth_api(self):
        r = self.svc.companion_growth_stats()
        self.assertIn("proposal", r)

    def test_old_emotion_api(self):
        r = self.svc.companion_emotion()
        self.assertIn("positivity", r)

    def test_handle_still_works(self):
        r = self.svc.companion.handle({"text": "hi"})
        self.assertIn("personality", r)

    def test_companion_status_version(self):
        r = self.svc.companion.status()
        self.assertEqual(r["version"], "9.5.0")


class TestFullFlow(unittest.TestCase):
    """端到端治理流"""

    def test_constitution_full_flow(self):
        svc = setup_service()
        # 1. 云端任务经宪法
        r = svc.companion_hybrid_execute(
            {"type": "creative_exploration"},
            {"prompt": "设计"},
        )
        self.assertEqual(
            r["constitution"]["review"]["decision"], "allow")
        # 2. 成长闭环经宪法
        r = svc.companion_growth_cycle_run(trigger="manual")
        self.assertIn("constitution_reviews", r)
        # 3. 身份防护
        r = svc.companion_constitution_review({
            "module": "test",
            "action_text": "修改使命",
            "change": {"mission": "x"},
        })
        self.assertEqual(r["decision"], "block")
        # 4. 演化建议 (永不自动)
        p = svc.companion_constitution_propose_evolution(
            "修改治理原则", "测试",
        )
        self.assertFalse(p["auto_applied"])
        # 5. 总账完整
        report = svc.companion_constitution_ledger()
        self.assertGreaterEqual(report["total"], 2)


if __name__ == "__main__":
    unittest.main()
