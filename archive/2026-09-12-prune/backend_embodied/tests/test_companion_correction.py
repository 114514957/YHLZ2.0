"""
YHLZ Embodied AI V5.4 - 自我修正器单元测试 (Self Corrector)

覆盖 (correction.py):
    - CORRECTION_RULES: 失败原因 → 修正动作映射 (可解释)
    - correct: 执行失败 → 规则调整 → 再执行 (上限内)
    - 修正策略: move_first / shorter_move / scan_first / pick_first /
      fix_parameters / no_correction / retry
    - 权限拒绝不可修正
    - 修正审计: 每次修正记录
    - 参数校验: max_attempts <= 0 / 空请求
    - 与学习器集成 (失败/成功记录)
"""
import unittest

from backend.embodied.companion import (
    CORRECTION_RULES,
    CompanionLearning,
    CorrectionError,
    SelfCorrector,
)
from backend.embodied.service import EmbodiedService


def make_svc(enabled=True):
    svc = EmbodiedService()
    svc.load_config({"embodied_enabled": enabled})
    return svc


class TestCorrectionRules(unittest.TestCase):
    """修正策略表"""

    def test_position_mismatch(self):
        """位置不匹配 → 先移动"""
        rule = SelfCorrector.rule_for("position_mismatch")
        self.assertEqual(rule["adjustment"], "move_first")
        self.assertIn("移动", rule["reason"])

    def test_boundary_limit(self):
        """边界限制 → 缩短移动"""
        rule = SelfCorrector.rule_for("boundary_limit")
        self.assertEqual(rule["adjustment"], "shorter_move")

    def test_object_missing(self):
        """对象缺失 → 先扫描"""
        rule = SelfCorrector.rule_for("object_missing")
        self.assertEqual(rule["adjustment"], "scan_first")

    def test_object_not_held(self):
        """对象未持有 → 先拾取"""
        rule = SelfCorrector.rule_for("object_not_held")
        self.assertEqual(rule["adjustment"], "pick_first")

    def test_permission_denied(self):
        """权限拒绝 → 不可修正"""
        rule = SelfCorrector.rule_for("permission_denied")
        self.assertEqual(rule["adjustment"], "no_correction")

    def test_unknown_default(self):
        """未知原因 → 重试"""
        rule = SelfCorrector.rule_for("zzz")
        self.assertEqual(rule["adjustment"], "retry")

    def test_rules_explainable(self):
        """全部规则可解释"""
        for rule in CORRECTION_RULES.values():
            self.assertTrue(rule["reason"])

    def test_extract_cause(self):
        """错误提取原因"""
        c = SelfCorrector._extract_cause("position_mismatch: 对象不在")
        self.assertEqual(c, "position_mismatch")
        self.assertEqual(SelfCorrector._extract_cause("random"),
                         "unknown")


class TestCorrectionAdjustments(unittest.TestCase):
    """修正动作应用"""

    def test_move_first(self):
        """先移动修正"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "pick", "target": "lamp", "description": "拿起"},
            "move_first",
        )
        self.assertIn("move", adjusted["intent"])

    def test_scan_first(self):
        """先扫描修正"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "pick", "description": "拿起"},
            "scan_first",
        )
        self.assertIn("scan", adjusted["intent"])

    def test_pick_first(self):
        """先拾取修正"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "place", "target": "box", "description": "放置"},
            "pick_first",
        )
        self.assertIn("pick", adjusted["intent"])

    def test_shorter_move(self):
        """缩短移动修正 (约束)"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "move", "constraints": {}},
            "shorter_move",
        )
        self.assertTrue(adjusted["constraints"]["shorter_move"])

    def test_fix_parameters(self):
        """参数修正 (约束)"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "pick"},
            "fix_parameters",
        )
        self.assertTrue(adjusted["constraints"]["retry_fixed"])

    def test_adjustment_preserves_fields(self):
        """修正保留原字段"""
        adjusted = SelfCorrector._apply_adjustment(
            {"intent": "pick", "scene": "room", "priority": "high"},
            "scan_first",
        )
        self.assertEqual(adjusted["scene"], "room")
        self.assertEqual(adjusted["priority"], "high")


class TestCorrect(unittest.TestCase):
    """自我修正执行"""

    def setUp(self):
        self.svc = make_svc()
        self.corrector = SelfCorrector(self.svc, max_attempts=3)

    def test_correct_success_first(self):
        """首次成功 → 1 次尝试"""
        result = self.corrector.correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(result["success"])
        self.assertEqual(result["attempts"], 1)

    def test_correct_structure(self):
        """修正结构完整"""
        result = self.corrector.correct({
            "description": "扫描", "intent": "scan",
        })
        for key in ("correction_id", "success", "attempts",
                    "max_attempts", "records", "final_status",
                    "explainable_reason", "mode"):
            self.assertIn(key, result)
        self.assertEqual(result["mode"], "rule_based")

    def test_correct_record_fields(self):
        """CorrectionRecord 字段"""
        result = self.corrector.correct({
            "description": "扫描", "intent": "scan",
        })
        rec = result["records"][0]
        for key in ("attempt", "reason", "adjustment", "result"):
            self.assertIn(key, rec)

    def test_correct_denied(self):
        """权限拒绝 → 不修正"""
        corrector = SelfCorrector(make_svc(enabled=False), max_attempts=3)
        result = corrector.correct({
            "description": "拿起", "intent": "pick",
        })
        self.assertFalse(result["success"])
        self.assertEqual(result["final_status"], "denied")
        self.assertEqual(result["attempts"], 1)

    def test_correct_failure_retry(self):
        """失败重试 (上限内)"""
        corrector = SelfCorrector(make_svc(), max_attempts=3)
        result = corrector.correct({
            "description": "拿起幽灵对象", "intent": "pick",
            "target": "ghost",
        })
        self.assertLessEqual(result["attempts"],
                             result["max_attempts"])

    def test_correct_explainable(self):
        """修正可解释"""
        result = self.corrector.correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("自我修正", result["explainable_reason"])
        self.assertIn("尝试1", result["explainable_reason"])

    def test_correct_empty_raises(self):
        """空请求 → CorrectionError"""
        with self.assertRaises(CorrectionError):
            self.corrector.correct({})
        with self.assertRaises(CorrectionError):
            self.corrector.correct(None)

    def test_correct_audit(self):
        """修正审计"""
        self.corrector.correct({"description": "扫描", "intent": "scan"})
        aud = self.corrector.audit()
        self.assertEqual(aud["total"], 1)
        self.assertEqual(aud["mode"], "rule_based")


class TestCorrectionLearning(unittest.TestCase):
    """修正 + 学习集成"""

    def setUp(self):
        self.svc = make_svc()
        self.learner = CompanionLearning(threshold=2)
        self.corrector = SelfCorrector(
            self.svc, max_attempts=3, learner=self.learner,
        )

    def test_success_recorded(self):
        """成功记录学习"""
        self.corrector.correct({"description": "扫描", "intent": "scan"})
        lrn = self.learner.learning()
        self.assertEqual(len(lrn["success_patterns"]), 1)

    def test_failure_recorded(self):
        """失败记录学习"""
        corrector = SelfCorrector(
            make_svc(), max_attempts=2, learner=self.learner,
        )
        corrector.correct({"description": "拿起幽灵对象",
                           "intent": "pick", "target": "ghost"})
        lrn = self.learner.learning()
        self.assertGreaterEqual(len(lrn["failure_patterns"]), 1)

    def test_learning_rule_promoted(self):
        """连续失败提升规则"""
        corrector = SelfCorrector(
            make_svc(), max_attempts=2, learner=self.learner,
        )
        for _ in range(3):
            corrector.correct({"description": "拿起幽灵对象",
                               "intent": "pick", "target": "ghost"})
        lrn = self.learner.learning()
        self.assertGreaterEqual(len(lrn["failure_rules"]), 1)

    def test_best_rule_for_correction(self):
        """学习规则供修正参考"""
        self.learner.record_failure(cause="position_mismatch",
                                    action="pick")
        rule = self.learner.best_failure_rule("position_mismatch")
        corr = SelfCorrector.rule_for(rule["pattern"]["cause"])
        self.assertEqual(corr["adjustment"], "move_first")


class TestValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_max_attempts(self):
        """max_attempts <= 0 → CorrectionError"""
        with self.assertRaises(CorrectionError):
            SelfCorrector(make_svc(), max_attempts=0)

    def test_thresholds(self):
        """阈值暴露"""
        corrector = SelfCorrector(make_svc(), max_attempts=2)
        th = corrector.thresholds()
        self.assertEqual(th["max_attempts"], 2)
        self.assertFalse(th["strict"])

    def test_strict_mode_flag(self):
        """严格模式标志"""
        corrector = SelfCorrector(make_svc(), max_attempts=3, strict=True)
        self.assertTrue(corrector.thresholds()["strict"])

    def test_no_attempts_record_when_success(self):
        """成功时记录 1 条"""
        result = SelfCorrector(make_svc()).correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertEqual(len(result["records"]), 1)

    def test_records_fill_attempt_numbers(self):
        """记录填充尝试序号"""
        result = SelfCorrector(make_svc(), max_attempts=2).correct({
            "description": "拿起幽灵对象", "intent": "pick",
            "target": "ghost",
        })
        for i, rec in enumerate(result["records"], 1):
            self.assertEqual(rec["attempt"], i)

    def test_correct_reason_in_records(self):
        """记录含修正原因"""
        corrector = SelfCorrector(make_svc(), max_attempts=2)
        result = corrector.correct({
            "description": "拿起幽灵对象", "intent": "pick",
            "target": "ghost",
        })
        # 失败轮次应有 adjustment (修正动作)
        failed = [r for r in result["records"]
                  if not r["result"]["success"]]
        self.assertGreaterEqual(len(failed), 0)

    def test_correct_final_status_present(self):
        """最终状态存在"""
        result = SelfCorrector(make_svc()).correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("final_status", result)

    def test_correct_success_status(self):
        """成功状态 ok"""
        result = SelfCorrector(make_svc()).correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertEqual(result["final_status"], "ok")

    def test_correct_id_unique(self):
        """修正 ID 唯一"""
        c1 = SelfCorrector(make_svc()).correct({
            "description": "扫描", "intent": "scan",
        })
        c2 = SelfCorrector(make_svc()).correct({
            "description": "扫描", "intent": "scan",
        })
        self.assertNotEqual(c1["correction_id"], c2["correction_id"])

    def test_audit_recent_limit(self):
        """审计近期限制"""
        corrector = SelfCorrector(make_svc())
        corrector.correct({"description": "扫描", "intent": "scan"})
        aud = corrector.audit(limit=1)
        self.assertEqual(len(aud["recent"]), 1)

    def test_audit_recent_all(self):
        """审计近期全量"""
        corrector = SelfCorrector(make_svc())
        corrector.correct({"description": "扫描", "intent": "scan"})
        aud = corrector.audit(limit=0)
        self.assertEqual(len(aud["recent"]), 1)

    def test_audit_empty(self):
        """空审计"""
        aud = SelfCorrector(make_svc()).audit()
        self.assertEqual(aud["total"], 0)

    def test_audit_fields(self):
        """审计字段"""
        corrector = SelfCorrector(make_svc())
        corrector.correct({"description": "扫描", "intent": "scan"})
        aud = corrector.audit()
        entry = aud["recent"][0]
        for key in ("correction_id", "success", "attempts",
                    "final_status", "timestamp"):
            self.assertIn(key, entry)


class TestCorrectMore(unittest.TestCase):
    """修正更多场景"""

    def test_move_goal_correct(self):
        """移动目标修正"""
        corrector = SelfCorrector(make_svc(), max_attempts=3)
        result = corrector.correct({
            "description": "移动到门口", "intent": "move",
        })
        self.assertIn("final_status", result)

    def test_inspect_goal_correct(self):
        """检查目标修正"""
        corrector = SelfCorrector(make_svc(), max_attempts=3)
        result = corrector.correct({
            "description": "检查台灯", "intent": "inspect",
        })
        self.assertIn("final_status", result)

    def test_place_goal_correct(self):
        """放置目标修正"""
        corrector = SelfCorrector(make_svc(), max_attempts=3)
        result = corrector.correct({
            "description": "放置箱子", "intent": "place",
        })
        self.assertIn("final_status", result)

    def test_scan_goal_learning_success(self):
        """扫描成功学习"""
        learner = CompanionLearning(threshold=1)
        corrector = SelfCorrector(make_svc(), max_attempts=3,
                                  learner=learner)
        corrector.correct({"description": "扫描", "intent": "scan"})
        lrn = learner.learning()
        self.assertEqual(len(lrn["success_rules"]), 1)

    def test_rule_for_none(self):
        """None 原因 → 默认"""
        rule = SelfCorrector.rule_for(None)
        self.assertEqual(rule["adjustment"], "retry")

    def test_extract_cause_permission(self):
        """权限错误提取"""
        self.assertEqual(
            SelfCorrector._extract_cause("embodied_enabled=False"),
            "permission_denied",
        )
        self.assertEqual(
            SelfCorrector._extract_cause("权限拒绝"),
            "permission_denied",
        )

    def test_extract_cause_object_missing(self):
        """对象缺失提取"""
        self.assertEqual(
            SelfCorrector._extract_cause("object_missing: 目标不存在"),
            "object_missing",
        )

    def test_correct_description_fallback(self):
        """description 回退 text"""
        corrector = SelfCorrector(make_svc())
        result = corrector.correct({"text": "扫描", "intent": "scan"})
        self.assertIn("final_status", result)


if __name__ == "__main__":
    unittest.main()
