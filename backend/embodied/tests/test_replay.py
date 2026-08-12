"""
YHLZ Embodied AI V4.3 - 目标回放系统单元测试 (Goal Replay)

覆盖:
    - GoalStep: to_dict/from_dict / is_failure / failure_positions
    - GoalTrace: replay_dict / replay_text / export_text / 序列化往返
    - GoalTraceStore: add/get/get_by_trace_id/all/stats/save/load/clear
    - Service 集成: run_goal 自动记录轨迹 → replay_goal / compare_goals /
      export_goal_trace
    - 异常路径: 轨迹不存在 / 格式不支持
"""
import json
import os
import tempfile
import unittest

from backend.embodied.replay import (
    GoalReplayError,
    GoalStep,
    GoalTrace,
    GoalTraceStore,
)
from backend.embodied.schema import EmbodiedGoal
from backend.embodied.service import EmbodiedService, EmbodiedServiceError


def _make_trace(goal_id="g-1", success=True, steps=None) -> GoalTrace:
    trace = GoalTrace(
        goal_id=goal_id,
        goal={"description": "测试目标", "constraints": {"max_steps": 5}},
        plan=[{"action_type": "scan"}],
        steps=steps or [
            GoalStep(
                step_index=1,
                action={"action_type": "scan", "target": ""},
                feedback={"result": "success", "environment_change": {}},
                observed_state={"objects": [], "location": {"x": 0.0, "y": 0.0}},
                result="ok",
                timestamp=100.0,
            )
        ],
        final_state={"objects": []},
        final_status="ok",
        success=success,
        failures=0,
        iterations=1,
        environment="mock",
        started_at=0.0,
        ended_at=10.0,
        duration_ms=5.5,
    )
    return trace


class TestGoalStep(unittest.TestCase):

    def test_is_failure_success(self):
        s = GoalStep(step_index=1, feedback={"result": "success"})
        self.assertFalse(s.is_failure)

    def test_is_failure_failure(self):
        s = GoalStep(step_index=2, feedback={"result": "failure"})
        self.assertTrue(s.is_failure)

    def test_is_failure_no_feedback(self):
        self.assertFalse(GoalStep().is_failure)

    def test_to_dict_fields(self):
        d = GoalStep(step_index=3, action={"a": 1}).to_dict()
        self.assertEqual(d["step_index"], 3)
        self.assertEqual(d["action"], {"a": 1})
        self.assertIsNone(d["feedback"])
        self.assertEqual(d["result"], "")

    def test_from_dict_roundtrip(self):
        s = GoalStep(
            step_index=2,
            action={"action_type": "pick", "target": "lamp"},
            feedback={"result": "failure", "cause": "x"},
            observed_state={"objects": [1]},
            result="error",
            timestamp=9.5,
        )
        r = GoalStep.from_dict(s.to_dict())
        self.assertEqual(r.step_index, 2)
        self.assertEqual(r.action, s.action)
        self.assertEqual(r.feedback, s.feedback)
        self.assertEqual(r.observed_state, s.observed_state)
        self.assertEqual(r.result, "error")
        self.assertEqual(r.timestamp, 9.5)

    def test_from_dict_empty(self):
        r = GoalStep.from_dict({})
        self.assertEqual(r.step_index, 0)
        self.assertEqual(r.action, {})

    def test_from_dict_none_feedback(self):
        r = GoalStep.from_dict({"step_index": 1})
        self.assertIsNone(r.feedback)

    def test_from_dict_none_action(self):
        r = GoalStep.from_dict({"action": None})
        self.assertEqual(r.action, {})


class TestGoalTrace(unittest.TestCase):

    def test_step_count(self):
        trace = _make_trace(steps=[GoalStep(step_index=1), GoalStep(step_index=2)])
        self.assertEqual(trace.step_count, 2)

    def test_failure_positions_empty(self):
        trace = _make_trace()
        self.assertEqual(trace.failure_positions, [])

    def test_failure_positions(self):
        trace = _make_trace(steps=[
            GoalStep(step_index=1, feedback={"result": "success"}),
            GoalStep(step_index=2, feedback={"result": "failure"}),
            GoalStep(step_index=3, feedback={"result": "failure"}),
        ])
        self.assertEqual(trace.failure_positions, [2, 3])

    def test_to_dict_roundtrip(self):
        trace = _make_trace(steps=[
            GoalStep(step_index=1, feedback={"result": "failure"}),
        ])
        r = GoalTrace.from_dict(trace.to_dict())
        self.assertEqual(r.goal_id, "g-1")
        self.assertEqual(r.success, True)
        self.assertEqual(r.step_count, 1)
        self.assertTrue(r.steps[0].is_failure)
        self.assertEqual(r.duration_ms, 5.5)

    def test_from_dict_missing_keys(self):
        r = GoalTrace.from_dict({"goal_id": "x"})
        self.assertEqual(r.goal, {})
        self.assertEqual(r.plan, [])
        self.assertEqual(r.steps, [])

    def test_replay_dict_structure(self):
        trace = _make_trace()
        d = trace.replay_dict()
        self.assertEqual(d["goal_id"], "g-1")
        self.assertEqual(d["environment"], "mock")
        self.assertEqual(len(d["steps"]), 1)
        step = d["steps"][0]
        self.assertIn("observe", step)
        self.assertIn("action", step)
        self.assertIn("feedback", step)
        self.assertEqual(d["final_status"], "ok")
        self.assertTrue(d["success"])
        self.assertIsNotNone(d["final_state"])

    def test_replay_text_contains_steps(self):
        text = _make_trace().replay_text()
        self.assertIn("目标回放: g-1", text)
        self.assertIn("Step 1:", text)
        self.assertIn("Observe:", text)
        self.assertIn("Action:", text)
        self.assertIn("Feedback:", text)
        self.assertIn("最终结果:", text)

    def test_replay_text_success_flag(self):
        text = _make_trace(success=False).replay_text()
        self.assertIn("success=False", text)

    def test_export_text_header(self):
        text = _make_trace().export_text()
        self.assertIn("YHLZ Embodied Goal Trace Export", text)
        self.assertIn("trace_id:", text)
        self.assertIn("event_timeline:", text)

    def test_export_text_steps(self):
        text = _make_trace().export_text()
        self.assertIn("Step 1:", text)
        self.assertIn('"action_type": "scan"', text)

    def test_failure_positions_in_export(self):
        trace = _make_trace(steps=[
            GoalStep(step_index=1, feedback={"result": "success"}),
            GoalStep(step_index=2, feedback={"result": "failure"}),
        ])
        text = trace.export_text()
        self.assertIn("failures: 0", text)
        self.assertIn("positions=[2]", text)


class TestGoalTraceStore(unittest.TestCase):

    def setUp(self):
        self.store = GoalTraceStore(max_traces=3)

    def test_add_returns_trace_id(self):
        tid = self.store.add(_make_trace())
        self.assertTrue(tid)
        self.assertEqual(self.store.count(), 1)

    def test_add_none_raises(self):
        with self.assertRaises(GoalReplayError):
            self.store.add(None)

    def test_max_traces_zero_raises(self):
        with self.assertRaises(GoalReplayError):
            GoalTraceStore(max_traces=0)

    def test_get_by_goal_id(self):
        self.store.add(_make_trace(goal_id="g-1"))
        trace = self.store.get("g-1")
        self.assertIsNotNone(trace)
        self.assertEqual(trace.goal_id, "g-1")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("nope"))

    def test_get_by_trace_id(self):
        tid = self.store.add(_make_trace(goal_id="g-1"))
        trace = self.store.get_by_trace_id(tid)
        self.assertEqual(trace.goal_id, "g-1")

    def test_get_by_trace_id_missing(self):
        self.assertIsNone(self.store.get_by_trace_id("nope"))

    def test_all_order(self):
        for i in range(3):
            self.store.add(_make_trace(goal_id=f"g-{i}"))
        ids = [t.goal_id for t in self.store.all()]
        self.assertEqual(ids, ["g-0", "g-1", "g-2"])

    def test_max_traces_eviction(self):
        for i in range(5):
            self.store.add(_make_trace(goal_id=f"g-{i}"))
        self.assertEqual(self.store.count(), 3)
        self.assertIsNone(self.store.get("g-0"))
        self.assertIsNotNone(self.store.get("g-4"))

    def test_stats_empty(self):
        stats = self.store.stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["success_rate"], 0.0)

    def test_stats_mixed(self):
        self.store.add(_make_trace(goal_id="a", success=True))
        self.store.add(_make_trace(goal_id="b", success=False))
        stats = self.store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["success_count"], 1)
        self.assertEqual(stats["success_rate"], 0.5)

    def test_stats_steps_and_failures(self):
        self.store.add(_make_trace(goal_id="a", success=False))
        stats = self.store.stats()
        self.assertEqual(stats["total_steps"], 1)
        self.assertEqual(stats["total_failures"], 0)

    def test_clear(self):
        self.store.add(_make_trace(goal_id="a"))
        self.assertEqual(self.store.clear(), 1)
        self.assertEqual(self.store.count(), 0)

    def test_save_load_roundtrip(self):
        self.store.add(_make_trace(goal_id="a", success=True))
        self.store.add(_make_trace(goal_id="b", success=False))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "traces.jsonl")
            self.assertEqual(self.store.save_to_file(path), 2)
            store2 = GoalTraceStore()
            self.assertEqual(store2.load_from_file(path), 2)
            self.assertEqual(store2.count(), 2)
            self.assertIsNotNone(store2.get("a"))
            self.assertEqual(store2.get("b").success, False)

    def test_load_missing_file(self):
        self.assertEqual(self.store.load_from_file("nope.jsonl"), 0)

    def test_load_bad_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"goal_id": "ok"}\n')
                f.write("NOT JSON\n")
            self.assertEqual(self.store.load_from_file(path), 1)
            self.assertIsNotNone(self.store.get("ok"))

    def test_max_traces_property(self):
        self.assertEqual(self.store.max_traces, 3)

    def test_by_goal_keeps_latest_after_eviction(self):
        """by_goal 索引容量与 max_traces 一致"""
        for i in range(6):
            self.store.add(_make_trace(goal_id=f"g-{i}"))
        self.assertEqual(len(self.store._by_goal), 3)
        self.assertIsNotNone(self.store.get("g-5"))


class TestReplayService(unittest.TestCase):
    """Service 集成: run_goal 自动记录 → replay / compare / export"""

    def setUp(self):
        self.svc = EmbodiedService()
        self.svc.load_config({"embodied_enabled": True})

    def _run_ok_goal(self) -> str:
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 3})
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        return goal.goal_id

    def test_run_goal_records_trace(self):
        gid = self._run_ok_goal()
        self.assertEqual(self.svc.traces.count(), 1)
        self.assertIsNotNone(self.svc.traces.get(gid))

    def test_trace_has_steps(self):
        gid = self._run_ok_goal()
        trace = self.svc.traces.get(gid)
        self.assertGreaterEqual(trace.step_count, 1)
        self.assertEqual(trace.goal_id, gid)
        self.assertTrue(trace.success)

    def test_replay_goal(self):
        gid = self._run_ok_goal()
        d = self.svc.replay_goal(gid)
        self.assertEqual(d["goal_id"], gid)
        self.assertIn("steps", d)
        self.assertGreaterEqual(len(d["steps"]), 1)
        self.assertTrue(d["success"])
        self.assertIn("final_state", d)

    def test_replay_goal_missing(self):
        with self.assertRaises(EmbodiedServiceError):
            self.svc.replay_goal("nope")

    def test_compare_goals_same(self):
        gid = self._run_ok_goal()
        res = self.svc.compare_goals(gid, gid)
        self.assertEqual(res["comparison"]["step_count_delta"], 0)
        self.assertEqual(res["comparison"]["failure_count_delta"], 0)
        self.assertTrue(res["comparison"]["both_success"])
        self.assertEqual(res["goal_a"]["goal_id"], gid)
        self.assertEqual(res["goal_b"]["goal_id"], gid)

    def test_compare_goals_missing_a(self):
        gid = self._run_ok_goal()
        with self.assertRaises(EmbodiedServiceError):
            self.svc.compare_goals("nope", gid)

    def test_compare_goals_missing_b(self):
        gid = self._run_ok_goal()
        with self.assertRaises(EmbodiedServiceError):
            self.svc.compare_goals(gid, "nope")

    def test_compare_goals_result_fields(self):
        gid = self._run_ok_goal()
        res = self.svc.compare_goals(gid, gid)
        self.assertIn("goal_a", res)
        self.assertIn("goal_b", res)
        self.assertIn("step_count", res["goal_a"])
        self.assertIn("failure_positions", res["goal_a"])
        self.assertIn("duration_ms", res["goal_a"])
        self.assertIn("a_better", res["comparison"])

    def test_export_json(self):
        gid = self._run_ok_goal()
        out = self.svc.export_goal_trace(gid, format="json")
        self.assertEqual(out["format"], "json")
        self.assertEqual(out["trace"]["goal_id"], gid)
        self.assertIn("steps", out["trace"])
        self.assertIn("event_timeline", out["trace"])

    def test_export_text(self):
        gid = self._run_ok_goal()
        out = self.svc.export_goal_trace(gid, format="text")
        self.assertEqual(out["format"], "text")
        self.assertIn("YHLZ Embodied Goal Trace Export", out["export"])

    def test_export_default_json(self):
        gid = self._run_ok_goal()
        out = self.svc.export_goal_trace(gid)
        self.assertEqual(out["format"], "json")

    def test_export_unsupported_format(self):
        gid = self._run_ok_goal()
        with self.assertRaises(EmbodiedServiceError):
            self.svc.export_goal_trace(gid, format="xml")

    def test_export_missing(self):
        with self.assertRaises(EmbodiedServiceError):
            self.svc.export_goal_trace("nope")

    def test_trace_environment_label(self):
        gid = self._run_ok_goal()
        trace = self.svc.traces.get(gid)
        self.assertEqual(trace.environment, "mock")

    def test_run_goal_returns_trace_id(self):
        goal = EmbodiedGoal.create(description="扫描房间", constraints={"max_steps": 2})
        res = self.svc.run_goal(goal)
        self.assertTrue(res.trace_id)
        self.assertIsNotNone(self.svc.traces.get_by_trace_id(res.trace_id))

    def test_replay_after_scene_switch(self):
        """切换场景后回放环境标签正确"""
        self.svc.switch_environment("warehouse")
        goal = EmbodiedGoal.create(description="扫描仓库", constraints={"max_steps": 2})
        res = self.svc.run_goal(goal)
        self.assertTrue(res.success)
        trace = self.svc.traces.get(goal.goal_id)
        self.assertEqual(trace.environment, "warehouse")
        d = self.svc.replay_goal(goal.goal_id)
        self.assertEqual(d["environment"], "warehouse")

    def test_trace_immutable_after_run(self):
        """轨迹记录后不可变 (数据独立, 不污染 Agent Memory)"""
        gid = self._run_ok_goal()
        before = self.svc.export_goal_trace(gid)["trace"]
        self._run_ok_goal()
        after = self.svc.export_goal_trace(gid)["trace"]
        self.assertEqual(before, after)

    def test_traces_persistence_via_store(self):
        gid = self._run_ok_goal()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.jsonl")
            self.svc.traces.save_to_file(path)
            new_store = GoalTraceStore()
            self.assertEqual(new_store.load_from_file(path), 1)
            self.assertIsNotNone(new_store.get(gid))


if __name__ == "__main__":
    unittest.main()
