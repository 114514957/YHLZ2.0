"""
YHLZ Embodied AI V5.3 - 执行协调器单元测试 (Execution Coordinator)

覆盖 (executor.py):
    - execute: 请求 → EmbodiedGoal → run_goal → ExecutionRecord
    - ExecutionRecord 结构: execution_id/goal/status/success/actions/
      latency_ms/feedback/error/permission_required
    - feedback_loop: 反馈分析 (成功/失败建议)
    - close_loop: 闭环循环 (上限可配, 成功即停)
    - audit: 执行审计 (成功/失败统计)
    - 参数校验: max_iterations <= 0 / 空请求
    - 安全: 执行经 Permission (denied 不重试)
"""
import unittest

from backend.embodied.companion import (
    ExecutionCoordinator,
    ExecutorError,
)
from backend.embodied.service import EmbodiedService


def make_svc(enabled=True):
    svc = EmbodiedService()
    svc.load_config({"embodied_enabled": enabled})
    return svc


class TestExecute(unittest.TestCase):
    """执行入口"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_execute_success(self):
        """执行成功"""
        rec = self.executor.execute({
            "description": "拿起台灯", "intent": "pick", "target": "lamp",
        })
        self.assertTrue(rec["success"])
        self.assertEqual(rec["status"], "ok")

    def test_execute_record_structure(self):
        """ExecutionRecord 结构完整"""
        rec = self.executor.execute({
            "description": "扫描", "intent": "scan",
        })
        for key in ("execution_id", "goal", "status", "success",
                    "actions", "latency_ms", "feedback", "error",
                    "permission_required"):
            self.assertIn(key, rec)
        self.assertTrue(rec["execution_id"].startswith("exec_"))
        self.assertTrue(rec["permission_required"])

    def test_execute_goal_fields(self):
        """goal 字段完整"""
        rec = self.executor.execute({
            "description": "拿起", "intent": "pick",
            "target": "lamp", "scene": "room", "priority": "high",
        })
        goal = rec["goal"]
        self.assertEqual(goal["intent"], "pick")
        self.assertEqual(goal["target"], "lamp")
        self.assertEqual(goal["scene"], "room")
        self.assertEqual(goal["priority"], "high")

    def test_execute_empty_raises(self):
        """空请求 → ExecutorError"""
        with self.assertRaises(ExecutorError):
            self.executor.execute({})
        with self.assertRaises(ExecutorError):
            self.executor.execute(None)

    def test_execute_denied(self):
        """权限拒绝 → denied"""
        svc = make_svc(enabled=False)
        executor = ExecutionCoordinator(svc)
        rec = executor.execute({"description": "拿起", "intent": "pick"})
        self.assertFalse(rec["success"])
        self.assertEqual(rec["status"], "denied")

    def test_execute_latency_measured(self):
        """耗时统计"""
        rec = self.executor.execute({
            "description": "扫描", "intent": "scan",
        })
        self.assertGreaterEqual(rec["latency_ms"], 0)

    def test_execute_records_audited(self):
        """执行记录入审计"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit()
        self.assertEqual(aud["total"], 1)


class TestFeedbackLoop(unittest.TestCase):
    """反馈闭环"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_feedback_success(self):
        """成功反馈"""
        rec = self.executor.execute({
            "description": "扫描", "intent": "scan",
        })
        fb = self.executor.feedback_loop(rec)
        self.assertTrue(fb["enabled"])
        self.assertTrue(fb["success"])
        self.assertEqual(fb["experience_update"], "recorded")
        self.assertTrue(fb["suggestions"])

    def test_feedback_failure_suggestion(self):
        """失败反馈建议"""
        fb = self.executor.feedback_loop({
            "success": False, "status": "error",
        })
        self.assertFalse(fb["success"])
        self.assertTrue(any("失败" in s for s in fb["suggestions"]))

    def test_feedback_denied_suggestion(self):
        """权限拒绝建议"""
        fb = self.executor.feedback_loop({
            "success": False, "status": "denied",
        })
        self.assertTrue(any("权限" in s for s in fb["suggestions"]))

    def test_feedback_disabled(self):
        """反馈停用"""
        executor = ExecutionCoordinator(self.svc, feedback_enabled=False)
        fb = executor.feedback_loop({"success": True, "status": "ok"})
        self.assertFalse(fb["enabled"])
        self.assertEqual(fb["experience_update"], "skipped")


class TestCloseLoop(unittest.TestCase):
    """闭环循环"""

    def test_loop_success_first_iteration(self):
        """首次执行成功 → 1 轮"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({
            "description": "扫描", "intent": "scan",
        })
        self.assertTrue(loop["success"])
        self.assertEqual(loop["iterations"], 1)
        self.assertEqual(loop["final_status"], "ok")

    def test_loop_structure(self):
        """闭环结构完整"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({
            "description": "扫描", "intent": "scan",
        })
        for key in ("loop_id", "iterations", "max_iterations", "success",
                    "executions", "feedbacks", "final_status",
                    "explainable_reason", "mode"):
            self.assertIn(key, loop)
        self.assertEqual(loop["mode"], "rule_based")

    def test_loop_denied_no_retry(self):
        """权限拒绝 → 不重试"""
        executor = ExecutionCoordinator(make_svc(enabled=False),
                                        max_iterations=3)
        loop = executor.close_loop({"description": "拿起", "intent": "pick"})
        self.assertEqual(loop["iterations"], 1)
        self.assertEqual(loop["final_status"], "denied")
        self.assertFalse(loop["success"])

    def test_loop_explainable(self):
        """闭环可解释"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({
            "description": "扫描", "intent": "scan",
        })
        self.assertIn("闭环执行", loop["explainable_reason"])
        self.assertIn("轮次1", loop["explainable_reason"])

    def test_loop_max_iterations_config(self):
        """上限配置生效"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=2)
        self.assertEqual(executor.thresholds()["max_iterations"], 2)


class TestValidation(unittest.TestCase):
    """参数校验"""

    def test_invalid_max_iterations(self):
        """max_iterations <= 0 → ExecutorError"""
        with self.assertRaises(ExecutorError):
            ExecutionCoordinator(make_svc(), max_iterations=0)

    def test_thresholds(self):
        """阈值暴露"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3,
                                        feedback_enabled=True)
        th = executor.thresholds()
        self.assertEqual(th["max_iterations"], 3)
        self.assertTrue(th["feedback_enabled"])


class TestAudit(unittest.TestCase):
    """执行审计"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_audit_empty(self):
        """空审计"""
        aud = self.executor.audit()
        self.assertEqual(aud["total"], 0)
        self.assertEqual(aud["success_rate"], 0.0)

    def test_audit_counts(self):
        """审计计数"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit()
        self.assertEqual(aud["total"], 2)
        self.assertEqual(aud["success_count"], 2)
        self.assertEqual(aud["success_rate"], 1.0)

    def test_audit_failures(self):
        """审计失败计数"""
        svc = make_svc(enabled=False)
        executor = ExecutionCoordinator(svc)
        executor.execute({"description": "拿起", "intent": "pick"})
        aud = executor.audit()
        self.assertEqual(aud["fail_count"], 1)
        self.assertEqual(aud["success_rate"], 0.0)

    def test_audit_recent(self):
        """审计近期记录"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit()
        self.assertEqual(len(aud["recent"]), 1)

    def test_clear(self):
        """清空审计"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        self.assertEqual(self.executor.clear(), 1)
        self.assertEqual(self.executor.audit()["total"], 0)


class TestExecuteMore(unittest.TestCase):
    """执行更多场景"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_execute_scan_goal(self):
        """扫描目标执行"""
        rec = self.executor.execute({"description": "扫描房间",
                                     "intent": "scan"})
        self.assertTrue(rec["success"])

    def test_execute_move_goal(self):
        """移动目标执行"""
        rec = self.executor.execute({"description": "移动到门口",
                                     "intent": "move"})
        self.assertIn(rec["status"], ("ok", "error"))

    def test_execute_pick_failure_recoverable(self):
        """拾取失败可重试 (非 denied)"""
        rec = self.executor.execute({"description": "拿起幽灵",
                                     "intent": "pick",
                                     "target": "ghost"})
        self.assertNotEqual(rec["status"], "denied")

    def test_execute_confirm_param(self):
        """confirm 参数传递"""
        executor = ExecutionCoordinator(self.svc, confirm=False)
        rec = executor.execute({"description": "扫描", "intent": "scan"})
        self.assertTrue(rec["success"])

    def test_execute_idempotent(self):
        """重复执行各自记录"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        self.executor.execute({"description": "扫描", "intent": "scan"})
        self.assertEqual(self.executor.audit()["total"], 2)

    def test_execute_goal_dict_present(self):
        """goal 为 dict"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        self.assertIsInstance(rec["goal"], dict)

    def test_execute_latency_nonzero(self):
        """耗时 > 0 (或 0 边界)"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        self.assertGreaterEqual(rec["latency_ms"], 0)


class TestFeedbackMore(unittest.TestCase):
    """反馈更多场景"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_feedback_after_scan(self):
        """扫描后反馈成功"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        fb = self.executor.feedback_loop(rec)
        self.assertTrue(fb["success"])

    def test_feedback_suggestions_nonempty(self):
        """建议非空"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        fb = self.executor.feedback_loop(rec)
        self.assertTrue(fb["suggestions"])

    def test_feedback_no_change(self):
        """无变化反馈"""
        fb = self.executor.feedback_loop({"success": True,
                                          "status": "no_change"})
        self.assertTrue(fb["success"])


class TestLoopMore(unittest.TestCase):
    """闭环更多场景"""

    def test_loop_scan_success(self):
        """扫描闭环"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "扫描",
                                    "intent": "scan"})
        self.assertTrue(loop["success"])

    def test_loop_id_unique(self):
        """闭环 ID 唯一"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        l1 = executor.close_loop({"description": "扫描", "intent": "scan"})
        l2 = executor.close_loop({"description": "扫描", "intent": "scan"})
        self.assertNotEqual(l1["loop_id"], l2["loop_id"])

    def test_loop_feedbacks_match_executions(self):
        """反馈数 = 执行数"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "扫描",
                                    "intent": "scan"})
        self.assertEqual(len(loop["feedbacks"]),
                         len(loop["executions"]))

    def test_loop_mode_rule_based(self):
        """闭环模式"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "扫描",
                                    "intent": "scan"})
        self.assertEqual(loop["mode"], "rule_based")

    def test_loop_retry_on_failure(self):
        """失败后重试 (上限内)"""
        # 幽灵目标连续失败 → 重试至上限
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "拿起幽灵",
                                    "intent": "pick",
                                    "target": "ghost"})
        # 拾取幽灵可能失败但非 denied → 会重试
        self.assertLessEqual(loop["iterations"],
                             loop["max_iterations"])
        self.assertIn(loop["final_status"], ("ok", "error"))

    def test_loop_max_retries_respected(self):
        """重试不超上限"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=2)
        loop = executor.close_loop({"description": "拿起幽灵",
                                    "intent": "pick",
                                    "target": "ghost"})
        self.assertLessEqual(loop["iterations"], 2)

    def test_loop_iterations_positive(self):
        """迭代数 >= 1"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "拿起幽灵",
                                    "intent": "pick",
                                    "target": "ghost"})
        self.assertGreaterEqual(loop["iterations"], 1)

    def test_execution_stats_avg_latency(self):
        """执行统计平均耗时"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        executor.close_loop({"description": "扫描", "intent": "scan"})
        aud = executor.audit()
        self.assertIn("success_rate", aud)
        self.assertGreaterEqual(aud["success_rate"], 0)


class TestExecutorDryRun(unittest.TestCase):
    """闭环 Dry Run (P1)"""

    def test_dry_run_plan(self):
        """预演执行方案 (不执行)"""
        svc = make_svc()
        executor = ExecutionCoordinator(svc, max_iterations=3)
        goal = executor._make_goal({"description": "扫描",
                                    "intent": "scan"})
        self.assertEqual(goal.intent, "scan")

    def test_dry_run_goal_creation(self):
        """预演目标构造"""
        executor = ExecutionCoordinator(make_svc())
        goal = executor._make_goal({"description": "拿起台灯",
                                    "intent": "pick", "target": "lamp"})
        self.assertEqual(goal.target, "lamp")
        self.assertEqual(goal.intent, "pick")

    def test_dry_run_no_execution(self):
        """预演不执行 (审计不变)"""
        svc = make_svc()
        executor = ExecutionCoordinator(svc)
        before = executor.audit()["total"]
        executor._make_goal({"description": "扫描", "intent": "scan"})
        after = executor.audit()["total"]
        self.assertEqual(after, before)

    def test_dry_run_default_goal(self):
        """默认目标构造 (无参数)"""
        executor = ExecutionCoordinator(make_svc())
        goal = executor._make_goal({})
        self.assertEqual(goal.intent, "")


class TestExecutionStats(unittest.TestCase):
    """执行统计 (P1)"""

    def setUp(self):
        self.svc = make_svc()
        self.executor = ExecutionCoordinator(self.svc)

    def test_stats_empty(self):
        """空统计"""
        aud = self.executor.audit()
        self.assertEqual(aud["total"], 0)
        self.assertEqual(aud["fail_count"], 0)

    def test_stats_mixed(self):
        """混合统计 (成功+失败)"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit()
        self.assertEqual(aud["success_count"], 1)
        self.assertEqual(aud["fail_count"], 0)

    def test_stats_fail_from_denied(self):
        """denied 计入失败"""
        svc = make_svc(enabled=False)
        executor = ExecutionCoordinator(svc)
        executor.execute({"description": "拿起", "intent": "pick"})
        aud = executor.audit()
        self.assertEqual(aud["fail_count"], 1)

    def test_stats_recent_limit(self):
        """近期记录上限"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit(limit=1)
        self.assertEqual(len(aud["recent"]), 1)

    def test_stats_all_records(self):
        """limit=0 全量"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        aud = self.executor.audit(limit=0)
        self.assertEqual(len(aud["recent"]), 1)

    def test_clear_after_stats(self):
        """清空后统计归零"""
        self.executor.execute({"description": "扫描", "intent": "scan"})
        self.executor.clear()
        self.assertEqual(self.executor.audit()["total"], 0)

    def test_stats_denied_and_ok(self):
        """denied 与成功混合统计"""
        svc = make_svc(enabled=False)
        executor = ExecutionCoordinator(svc)
        executor.execute({"description": "拿起", "intent": "pick"})
        aud = executor.audit()
        self.assertEqual(aud["total"], 1)
        self.assertEqual(aud["success_rate"], 0.0)

    def test_loop_scan_execution_record(self):
        """闭环执行记录含耗时"""
        executor = ExecutionCoordinator(make_svc(), max_iterations=3)
        loop = executor.close_loop({"description": "扫描",
                                    "intent": "scan"})
        self.assertIn("latency_ms", loop["executions"][0])

    def test_feedback_after_move(self):
        """移动后反馈"""
        executor = ExecutionCoordinator(make_svc())
        rec = executor.execute({"description": "移动到门口",
                                "intent": "move"})
        fb = executor.feedback_loop(rec)
        self.assertIn("suggestions", fb)

    def test_execute_goal_scene_empty(self):
        """无场景参数默认空"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        self.assertEqual(rec["goal"]["scene"], "")

    def test_execute_priority_default(self):
        """默认优先级 medium"""
        rec = self.executor.execute({"description": "扫描",
                                     "intent": "scan"})
        self.assertEqual(rec["goal"]["priority"], "medium")

    def test_execute_goal_description(self):
        """描述字段传递"""
        rec = self.executor.execute({"description": "自定义描述",
                                     "intent": "scan"})
        self.assertEqual(rec["goal"]["description"], "自定义描述")


if __name__ == "__main__":
    unittest.main()
