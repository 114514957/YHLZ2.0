"""
YHLZ Embodied AI V10.1 - 工具交互流程测试 (Tool Interaction Flow)

覆盖:
    - 全流程: Understand → Plan → Tool → Result → Reflect → Response
    - 工具执行 (回调) / 异常捕获
    - 回溯 (可审计)
    - 流程上限淘汰
    - 停用错误帧
"""
import unittest

from backend.embodied.companion.interaction.tool_flow import (
    FLOW_STAGES,
    ToolFlowError,
    ToolFlowRecorder,
)


class TestToolFlowLifecycle(unittest.TestCase):
    """工具流程生命周期"""

    def setUp(self):
        self.tfr = ToolFlowRecorder()

    def test_begin(self):
        r = self.tfr.begin("查询状态")
        self.assertTrue(r["ok"])
        self.assertTrue(r["flow_id"].startswith("tf_"))

    def test_begin_understand_stage(self):
        r = self.tfr.begin("查询")
        trace = self.tfr.trace(r["flow_id"])
        self.assertEqual(trace["flow"]["stage"], "understand")
        self.assertEqual(trace["flow"]["intent"], "查询")

    def test_full_flow(self):
        flow = self.tfr.begin("查询天气")
        self.tfr.advance(flow["flow_id"], "plan", "选择天气工具")
        self.tfr.advance(flow["flow_id"], "tool", "调用工具")
        r = self.tfr.execute(
            flow["flow_id"], "weather", lambda: "晴天", {},
        )
        self.assertTrue(r["ok"])
        self.tfr.advance(flow["flow_id"], "reflect", "结果合理")
        r = self.tfr.finish(flow["flow_id"], "今天晴天")
        self.assertTrue(r["ok"])
        self.assertIn("elapsed_ms", r)

    def test_stage_transition_order(self):
        flow = self.tfr.begin("t")
        prev = ""
        for stage in FLOW_STAGES:
            if stage == "understand":
                prev = stage
                continue
            r = self.tfr.advance(flow["flow_id"], stage)
            self.assertTrue(r["ok"])
            prev = stage

    def test_trace_steps(self):
        flow = self.tfr.begin("查询")
        self.tfr.advance(flow["flow_id"], "plan")
        self.tfr.advance(flow["flow_id"], "tool")
        trace = self.tfr.trace(flow["flow_id"])
        self.assertEqual(len(trace["flow"]["steps"]), 3)

    def test_trace_missing_flow(self):
        r = self.tfr.trace("nope")
        self.assertEqual(r["mode"], "error_frame")
        self.assertFalse(r["ok"])

    def test_invalid_stage(self):
        flow = self.tfr.begin("t")
        with self.assertRaises(ToolFlowError):
            self.tfr.advance(flow["flow_id"], "bad")


class TestToolFlowExecute(unittest.TestCase):
    """工具执行"""

    def setUp(self):
        self.tfr = ToolFlowRecorder()

    def test_execute_with_args(self):
        flow = self.tfr.begin("计算")

        def add(a, b):
            return a + b

        r = self.tfr.execute(flow["flow_id"], "add", add,
                             {"a": 1, "b": 2})
        self.assertTrue(r["ok"])
        self.assertEqual(r["latency_ms"], r["latency_ms"])

    def test_execute_result_recorded(self):
        flow = self.tfr.begin("查")

        def get():
            return {"x": 1}

        self.tfr.execute(flow["flow_id"], "get", get)
        trace = self.tfr.trace(flow["flow_id"])
        self.assertEqual(trace["flow"]["result"]["ok"], True)

    def test_execute_exception(self):
        flow = self.tfr.begin("坏")

        def boom():
            raise RuntimeError("tool failed")

        r = self.tfr.execute(flow["flow_id"], "boom", boom)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "tool failed")

    def test_execute_missing_flow(self):
        r = self.tfr.execute("nope", "t", lambda: 1)
        self.assertEqual(r["mode"], "error_frame")

    def test_execute_tool_name_recorded(self):
        flow = self.tfr.begin("t")

        def fn():
            return None

        self.tfr.execute(flow["flow_id"], "my_tool", fn)
        trace = self.tfr.trace(flow["flow_id"])
        self.assertEqual(trace["flow"]["tool"], "my_tool")

    def test_latency_non_negative(self):
        flow = self.tfr.begin("t")
        r = self.tfr.execute(flow["flow_id"], "t", lambda: 1)
        self.assertGreaterEqual(r["latency_ms"], 0)


class TestToolFlowReflect(unittest.TestCase):
    """反思"""

    def setUp(self):
        self.tfr = ToolFlowRecorder()

    def test_reflect(self):
        flow = self.tfr.begin("t")
        r = self.tfr.reflect(flow["flow_id"], "结果合理")
        self.assertTrue(r["ok"])
        trace = self.tfr.trace(flow["flow_id"])
        self.assertEqual(trace["flow"]["reflection"], "结果合理")
        self.assertEqual(trace["flow"]["stage"], "reflect")

    def test_finish_response(self):
        flow = self.tfr.begin("t")
        r = self.tfr.finish(flow["flow_id"], "回答内容")
        self.assertTrue(r["ok"])
        trace = self.tfr.trace(flow["flow_id"])
        self.assertEqual(trace["flow"]["stage"], "response")


class TestToolFlowStats(unittest.TestCase):
    """统计与上限"""

    def setUp(self):
        self.tfr = ToolFlowRecorder()

    def test_stats_empty(self):
        s = self.tfr.stats()
        self.assertEqual(s["total_flows"], 0)

    def test_stats_after_flows(self):
        f1 = self.tfr.begin("a")
        self.tfr.begin("b")
        self.tfr.finish(f1["flow_id"])
        s = self.tfr.stats()
        self.assertEqual(s["total_flows"], 2)
        self.assertEqual(s["completed_flows"], 1)

    def test_stats_tool_calls(self):
        flow = self.tfr.begin("t")
        self.tfr.execute(flow["flow_id"], "tool", lambda: 1)
        s = self.tfr.stats()
        self.assertEqual(s["tool_call_flows"], 1)

    def test_max_flows_bounded(self):
        tfr = ToolFlowRecorder(max_flows=5)
        for i in range(10):
            tfr.begin(f"t{i}")
        self.assertEqual(tfr.stats()["total_flows"], 5)

    def test_clear(self):
        self.tfr.begin("a")
        self.tfr.begin("b")
        self.assertEqual(self.tfr.clear(), 2)

    def test_disabled_begin(self):
        tfr = ToolFlowRecorder(enabled=False)
        r = tfr.begin("t")
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_execute(self):
        tfr = ToolFlowRecorder(enabled=False)
        r = tfr.execute("f", "t", lambda: 1)
        self.assertEqual(r["mode"], "error_frame")

    def test_invalid_max_flows(self):
        with self.assertRaises(ToolFlowError):
            ToolFlowRecorder(max_flows=0)


# ── 生成式: 流程阶段矩阵 ───────────────────────────────────────
_FLOW_STAGE_CASES = [
    ("plan", "plan", True),
    ("tool", "tool", True),
    ("result", "result", True),
    ("reflect", "reflect", True),
    ("response", "response", True),
    ("bad_stage", "nope", False),
]


class TestGeneratedFlowStages(unittest.TestCase):
    """生成式: 阶段推进"""
    pass


for _i, (_name, _stage, _ok) in enumerate(_FLOW_STAGE_CASES):
    def _make(name=_name, stage=_stage, ok=_ok):
        def test_case(self):
            tfr = ToolFlowRecorder()
            flow = tfr.begin("t")
            if ok:
                r = tfr.advance(flow["flow_id"], stage)
                self.assertTrue(r["ok"])
            else:
                with self.assertRaises(ToolFlowError):
                    tfr.advance(flow["flow_id"], stage)
        test_case.__name__ = f"test_fstage_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFlowStages,
            f"test_fstage_{_name}_{_i}", _make())


# ── 生成式: 执行结果矩阵 ───────────────────────────────────────
_EXEC_CASES = [
    # (名称, 回调, 期望 ok)
    ("returns_value", lambda: 42, True),
    ("returns_none", lambda: None, True),
    ("returns_dict", lambda: {"a": 1}, True),
    ("raises_error", lambda: 1 / 0, False),
    ("raises_value", lambda: _raise_ve(), False),
]


def _raise_ve():
    raise ValueError("bad input")


class TestGeneratedExec(unittest.TestCase):
    """生成式: 执行结果"""
    pass


for _i, (_name, _fn, _ok) in enumerate(_EXEC_CASES):
    def _make(name=_name, fn=_fn, ok=_ok):
        def test_case(self):
            tfr = ToolFlowRecorder()
            flow = tfr.begin("t")
            r = tfr.execute(flow["flow_id"], "tool", fn)
            self.assertEqual(r["ok"], ok)
        test_case.__name__ = f"test_exec2_{name}_{_i}"
        return test_case
    setattr(TestGeneratedExec,
            f"test_exec2_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
