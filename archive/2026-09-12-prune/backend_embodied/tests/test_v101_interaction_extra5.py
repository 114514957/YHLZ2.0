"""
YHLZ Embodied AI V10.1 - 交互协议最终补充测试 (V10.1 Interaction Extra5)

覆盖 (生成式):
    - 工具流程执行边界矩阵
    - 会话-延迟联动矩阵
    - 协议-健康联动矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.companion.interaction.tool_flow import (
    ToolFlowRecorder,
)


# ── 生成式: 工具流程执行边界矩阵 ───────────────────────────────
_EXEC_BOUND = [
    # (名称, 是否 begin, 是否 finish, 期望 execute ok)
    ("begin_exec", True, False, True),
    ("begin_exec_finish", True, True, True),
    ("no_begin", False, False, False),
    ("begin_finish_exec", True, False, True),
]


class TestGeneratedExecBound(unittest.TestCase):
    """生成式: 执行边界"""
    pass


for _i, (_name, _begin, _finish, _exp) in enumerate(_EXEC_BOUND):
    def _make(name=_name, begin=_begin, finish=_finish, exp=_exp):
        def test_case(self):
            tfr = ToolFlowRecorder()
            if begin:
                flow = tfr.begin("t")
            else:
                flow = {"flow_id": "nope"}
            if finish:
                tfr.finish(flow["flow_id"], "r")
            r = tfr.execute(flow["flow_id"], "tool",
                            lambda: 1)
            self.assertEqual(r["ok"], exp)
        test_case.__name__ = f"test_exec_bound_{name}_{_i}"
        return test_case
    setattr(TestGeneratedExecBound,
            f"test_exec_bound_{_name}_{_i}", _make())


# ── 生成式: 会话-延迟联动矩阵 ──────────────────────────────────
_SESSION_LAT = [
    # (名称, 阶段, 延迟, 期望记录)
    ("user_lat", "user_input", 12.5, True),
    ("understand_lat", "understand", 20.0, True),
    ("context_lat", "context", 5.0, True),
    ("tool_lat", "tool", 100.0, True),
    ("response_lat", "response", 300.0, True),
    ("tts_lat", "tts", 500.0, True),
    ("play_lat", "play", 50.0, True),
]


class TestGeneratedSessionLat(unittest.TestCase):
    """生成式: 延迟各阶段"""
    pass


for _i, (_name, _stage, _ms, _exp) in enumerate(_SESSION_LAT):
    def _make(name=_name, stage=_stage, ms=_ms, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            r = p.mark_latency(stage, ms)
            self.assertEqual(r["ok"], exp)
            report = p.latency_report()
            self.assertEqual(
                report["stages"][stage]["count"], 1,
            )
            self.assertEqual(
                report["stages"][stage]["avg_ms"], ms,
            )
        test_case.__name__ = f"test_session_lat_{name}_{_i}"
        return test_case
    setattr(TestGeneratedSessionLat,
            f"test_session_lat_{_name}_{_i}", _make())


# ── 生成式: 协议-健康联动矩阵 ──────────────────────────────────
_HEALTH_LINK = [
    # (名称, 操作, 期望 stats mode)
    ("session_only", "session", "rule_based"),
    ("tool_only", "tool", "rule_based"),
    ("latency_only", "latency", "rule_based"),
    ("partner_only", "partner", "rule_based"),
    ("all_ops", "all", "rule_based"),
]


class TestGeneratedHealthLink(unittest.TestCase):
    """生成式: 协议统计"""
    pass


for _i, (_name, _op, _exp) in enumerate(_HEALTH_LINK):
    def _make(name=_name, op=_op, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            if op in ("session", "all"):
                p.begin_session(goal="任务")
            if op in ("tool", "all"):
                flow = p.begin_tool_flow("t")
                p.finish_tool_flow(flow["flow_id"], "r")
            if op in ("latency", "all"):
                p.mark_latency("tts", 1.0)
            if op in ("partner", "all"):
                p.set_partner_goal("目标")
            s = p.stats()
            self.assertEqual(s["mode"], exp)
            self.assertGreaterEqual(s["audit"]["total"], 0)
        test_case.__name__ = f"test_health_link_{name}_{_i}"
        return test_case
    setattr(TestGeneratedHealthLink,
            f"test_health_link_{_name}_{_i}", _make())


# ── 生成式: 协议审计容量矩阵 ───────────────────────────────────
_AUDIT_CAP = [
    # (名称, 上限, 写入数, 期望保留)
    ("cap_10_write_5", 10, 5, 5),
    ("cap_10_write_30", 10, 30, 10),
    ("cap_100_write_200", 100, 200, 100),
    ("cap_1_write_3", 1, 3, 1),
]


class TestGeneratedAuditCap(unittest.TestCase):
    """生成式: 审计容量"""
    pass


for _i, (_name, _cap, _n, _exp) in enumerate(_AUDIT_CAP):
    def _make(name=_name, cap=_cap, n=_n, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(config={
                "companion_interaction_audit_max": cap,
            })
            for j in range(n):
                p.begin_session(goal=f"任务{j}")
            self.assertEqual(
                p.audit_report()["stats"]["total"], exp,
            )
        test_case.__name__ = f"test_audit_cap_{name}_{_i}"
        return test_case
    setattr(TestGeneratedAuditCap,
            f"test_audit_cap_{_name}_{_i}", _make())


# ── 生成式: 协议流程上限矩阵 ───────────────────────────────────
_FLOW_CAP = [
    # (名称, 上限, 流程数, 期望保留)
    ("cap_5_write_20", 5, 20, 5),
    ("cap_10_write_10", 10, 10, 10),
    ("cap_3_write_2", 3, 2, 2),
    ("cap_1_write_10", 1, 10, 1),
]


class TestGeneratedFlowCap(unittest.TestCase):
    """生成式: 流程上限"""
    pass


for _i, (_name, _cap, _n, _exp) in enumerate(_FLOW_CAP):
    def _make(name=_name, cap=_cap, n=_n, exp=_exp):
        def test_case(self):
            tfr = ToolFlowRecorder(max_flows=cap)
            for j in range(n):
                tfr.begin(f"t{j}")
            self.assertEqual(tfr.stats()["total_flows"], exp)
        test_case.__name__ = f"test_flow_cap_{name}_{_i}"
        return test_case
    setattr(TestGeneratedFlowCap,
            f"test_flow_cap_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
