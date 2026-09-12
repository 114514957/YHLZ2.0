"""
YHLZ Embodied AI V10.1 - 交互协议生成式测试 4 (V10.1 Interaction Extra4)

覆盖 (生成式):
    - 上下文筛选 reason 矩阵
    - 工具流程统计矩阵
    - 协议引擎配置矩阵
"""
import unittest

from backend.embodied.companion.interaction import InteractionProtocol
from backend.embodied.companion.interaction.context_filter import (
    InteractionContextFilter,
)
from backend.embodied.companion.interaction.tool_flow import (
    ToolFlowRecorder,
)


# ── 生成式: 上下文筛选 reason 矩阵 ─────────────────────────────
_CTX_REASON = [
    # (名称, 文本, 期望 reason 关键词)
    ("task_t", "请完成任务", "筛选"),
    ("plan_t", "制定计划", "筛选"),
    ("chat_t", "聊聊天", "筛选"),
    ("empty_t", "", "筛选"),
    ("long_t", "x" * 500, "筛选"),
]


class TestGeneratedCtxReason(unittest.TestCase):
    """生成式: 上下文 reason"""
    pass


for _i, (_name, _text, _kw) in enumerate(_CTX_REASON):
    def _make(name=_name, text=_text, kw=_kw):
        def test_case(self):
            f = InteractionContextFilter()
            r = f.filter(text)
            self.assertIn(kw, r["reason"])
            self.assertIn("不等同长期记忆", r["reason"])
        test_case.__name__ = f"test_ctx_reason_{name}_{_i}"
        return test_case
    setattr(TestGeneratedCtxReason,
            f"test_ctx_reason_{_name}_{_i}", _make())


# ── 生成式: 工具流程统计矩阵 ───────────────────────────────────
_TF_STATS = [
    # (名称, 流程数, 完成数, 工具调用数)
    ("none", 0, 0, 0),
    ("one_plain", 1, 0, 0),
    ("one_finished", 1, 1, 0),
    ("one_tool", 1, 1, 1),
    ("three_mixed", 3, 2, 1),
]


class TestGeneratedTfStats(unittest.TestCase):
    """生成式: 工具统计"""
    pass


for _i, (_name, _n, _done, _tools) in enumerate(_TF_STATS):
    def _make(name=_name, n=_n, done=_done, tools=_tools):
        def test_case(self):
            tfr = ToolFlowRecorder()
            flows = []
            for j in range(n):
                flows.append(tfr.begin(f"t{j}"))
            for j in range(tools):
                tfr.execute(flows[j]["flow_id"], "tool",
                            lambda: 1)
            for j in range(done):
                tfr.finish(flows[j]["flow_id"], "r")
            s = tfr.stats()
            self.assertEqual(s["total_flows"], n)
            self.assertEqual(s["completed_flows"], done)
            self.assertEqual(s["tool_call_flows"], tools)
        test_case.__name__ = f"test_tfs_{name}_{_i}"
        return test_case
    setattr(TestGeneratedTfStats,
            f"test_tfs_{_name}_{_i}", _make())


# ── 生成式: 协议配置矩阵 ───────────────────────────────────────
_CONFIG_CASES = [
    # (名称, 配置, 检查字段, 期望值)
    ("ctx_len_50", {"companion_interaction_max_context_len": 50},
     "max_context_len", 50),
    ("pending_5", {"companion_interaction_max_pending": 5},
     "max_pending", 5),
    ("flows_10", {"companion_interaction_max_flows": 10},
     "max_flows", 10),
    ("latency_50", {"companion_interaction_latency_max_samples": 50},
     "max_samples", 50),
    ("audit_100", {"companion_interaction_audit_max": 100},
     "max_records", 100),
]


class TestGeneratedConfig(unittest.TestCase):
    """生成式: 配置驱动"""
    pass


for _i, (_name, _cfg, _field, _exp) in enumerate(_CONFIG_CASES):
    def _make(name=_name, cfg=_cfg, field=_field, exp=_exp):
        def test_case(self):
            p = InteractionProtocol(config=cfg)
            s = p.stats()
            if field == "max_context_len":
                self.assertEqual(
                    s["conversation"]["max_context_len"], exp,
                )
            elif field == "max_pending":
                self.assertEqual(
                    s["conversation"]["max_pending"], exp,
                )
            elif field == "max_flows":
                self.assertEqual(
                    s["tool_flow"]["max_flows"], exp,
                )
            elif field == "max_samples":
                self.assertEqual(
                    s["latency"]["stages"]["tts"]["count"], 0,
                )
                self.assertEqual(
                    p._latency._max_samples, exp,
                )
            elif field == "max_records":
                self.assertEqual(
                    s["audit"]["max_records"], exp,
                )
        test_case.__name__ = f"test_cfg_{name}_{_i}"
        return test_case
    setattr(TestGeneratedConfig,
            f"test_cfg_{_name}_{_i}", _make())


# ── 生成式: 协议组合操作稳定性矩阵 ─────────────────────────────
_COMBO_STABLE = [
    # (名称, 循环次数)
    ("repeat_5", 5),
    ("repeat_10", 10),
    ("repeat_20", 20),
]


class TestGeneratedComboStable(unittest.TestCase):
    """生成式: 组合稳定性"""
    pass


for _i, (_name, _n) in enumerate(_COMBO_STABLE):
    def _make(name=_name, n=_n):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            for j in range(n):
                p.begin_session(goal=f"任务{j}")
                p.update_stage("executing")
                flow = p.begin_tool_flow(f"t{j}")
                p.finish_tool_flow(flow["flow_id"], "r")
                p.mark_latency("tts", 1.0)
                p.set_partner_goal(f"目标{j}")
            s = p.stats()
            self.assertEqual(
                s["conversation"]["pending_count"], 0,
            )
            self.assertEqual(s["tool_flow"]["total_flows"], n)
            report = p.audit_report()
            self.assertGreaterEqual(report["stats"]["total"], n * 4)
        test_case.__name__ = f"test_combo_stable_{name}_{_i}"
        return test_case
    setattr(TestGeneratedComboStable,
            f"test_combo_stable_{_name}_{_i}", _make())


# ── 生成式: 协议最大流量矩阵 ───────────────────────────────────
_LOAD_CASES = [
    # (名称, 并发会话数)
    ("load_10", 10),
    ("load_50", 50),
    ("load_100", 100),
]


class TestGeneratedLoad(unittest.TestCase):
    """生成式: 高流量稳定性"""
    pass


for _i, (_name, _n) in enumerate(_LOAD_CASES):
    def _make(name=_name, n=_n):
        def test_case(self):
            p = InteractionProtocol(enabled=True)
            for j in range(n):
                p.begin_session(goal=f"任务{j}")
                p.mark_partner_session()
            self.assertEqual(
                p.partner_snapshot()["session_count"], n,
            )
            # begin_session 记 1 条审计, mark_partner_session 不记
            self.assertEqual(
                p.audit_report()["stats"]["total"], n,
            )
        test_case.__name__ = f"test_load_{name}_{_i}"
        return test_case
    setattr(TestGeneratedLoad,
            f"test_load_{_name}_{_i}", _make())


if __name__ == "__main__":
    unittest.main()
