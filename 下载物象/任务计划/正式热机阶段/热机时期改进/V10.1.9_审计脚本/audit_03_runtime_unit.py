# -*- coding: utf-8 -*-
"""V10.1.9 审计 #03: 运行时单元级验证

职责（责任书 §二）: 运行时测试工程师
审计域: V10.1.9 Prompt §七 对话运行时专项 + §十一 Input Aggregator + §八 Context
  - Turn 生命周期全序列 (IDLE→...→COMPLETED→IDLE)
  - R2 实证: 队满孤儿 turn (入 _turns 但不在队列/活跃)
  - R3 实证: _turns 无上限增长 (500 turn 全部留存)
  - R6 实证: latency_summary first_token 缺失 (TTFT 失真)
  - R1 实证: 非法迁移仅警告仍执行
  - InputAggregator: 1000 条模拟 (过滤/合并/优先级/上限)
  - ContextManager: 20 轮窗口 8 + 压缩触发
运行: venv\Scripts\python.exe audit_03_runtime_unit.py
输出: 控制台 unittest 报告 (断言即证据)
"""

# ── 标准库导入 ──────────────────────────────────────────────
import sys         # 注入项目根路径 (模块导入前提)
import unittest    # 单元测试框架 (断言驱动审计)
from pathlib import Path  # (保留: 路径工具)

# ── 导入被测模块 (审计对象, 只读不修改) ─────────────────────
sys.path.insert(0, r"D:\YHLZ2.0")   # 项目根加入模块搜索路径

from backend.conversation_controller import (  # Turn 控制器 (V10.1.7)
    ConversationTurnController,
    ConversationControllerError,
)
from backend.input_aggregator import InputAggregator  # 输入治理 (V10.1.8)
from backend.context_manager import ContextManager    # 上下文管理器 (8 条窗口)


class TestTurnLifecycle(unittest.TestCase):
    """Turn 状态机审计: 生命周期 / R2 / R3 / R6 / R1"""

    def setUp(self):
        """每个用例前构造全新控制器 (隔离状态, 防用例间污染)"""
        self.ctc = ConversationTurnController()

    def test_full_lifecycle(self):
        """正常生命周期: begin→claim→streaming→complete 后回到 IDLE"""
        t = self.ctc.begin_turn("你好")   # 新输入 → READY (无活跃 turn)
        claimed = self.ctc.claim_ready_turn()  # READY → PROCESSING
        self.assertIsNotNone(claimed)          # 应成功取出
        self.ctc.mark_streaming(t.turn_id)     # PROCESSING → STREAMING
        self.ctc.complete_turn(t.turn_id)      # STREAMING → COMPLETED → 释放
        st = self.ctc.state()                  # 查询全局状态
        self.assertIn("active_turn_id", st)
        self.assertEqual(st["active_state"], "IDLE")  # 活跃 turn 已释放

    def test_r2_queue_full_orphan(self):
        """R2 实证: 队满时 turn 已写 _turns 且置 QUEUED 后抛异常 → 孤儿

        后果: D 永远无人处理, 残留在 _turns 字典中 (状态泄漏)
        """
        ctc = ConversationTurnController(max_queue=2)  # 队列上限 2
        t1 = ctc.begin_turn("A")
        ctc.claim_ready_turn()                 # A 占活跃
        t2 = ctc.begin_turn("B")               # B 入队 (队列 1/2)
        t3 = ctc.begin_turn("C")               # C 入队 (队列 2/2, 已满)
        with self.assertRaises(ConversationControllerError):
            ctc.begin_turn("D")                # D: 队列满 → 抛异常
        turns = ctc._turns                     # 内部 turn 字典 (审计直接查看)
        states = {k: v.state for k, v in turns.items()}
        queue_ids = list(ctc._queue)           # 内部队列内容
        # 断言: D 在 _turns 中且状态 QUEUED
        d_state = [v.state for k, v in turns.items()
                   if v.input_text == "D"]
        self.assertEqual(d_state, ["QUEUED"])
        # 断言: D 既不在队列, 也非活跃 → 孤儿 (永不会被处理)
        orphan = all(not (k in queue_ids) and k != ctc._active_turn
                     for k, v in turns.items() if v.input_text == "D")
        self.assertTrue(orphan, "D 为孤儿 turn: 在 _turns 但不在队列/活跃")

    def test_r3_turns_unbounded(self):
        """R3 实证: _turns 无上限无淘汰, 500 个已结束 turn 全部留存

        后果: 长会话内存无限增长 (turn 对象含文本/延迟/事件序列)
        """
        ctc = ConversationTurnController(max_queue=500)
        for i in range(500):
            t = ctc.begin_turn(f"t{i}")
            ctc.claim_ready_turn()
            ctc.complete_turn(t.turn_id)       # 每个 turn 正常走完
        self.assertGreaterEqual(len(ctc._turns), 500,
                                "500 个已结束 turn 全部留在 _turns")

    def test_r6_first_token_never_recorded(self):
        """R6 实证: latency_summary 的 TTFT 用 llm_start 兜底

        原因: 全代码无 first_token 写入点 → 实际 TTFT =
              llm_start - turn_start (不含 LLM 首 token 生成耗时)
        """
        t = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.mark_streaming(t.turn_id)
        ls = self.ctc.latency_summary()        # 延迟汇总
        self.assertIn("avg_ttft_ms", ls)       # 指标字段存在
        # 关键断言: turn.latency 中不存在 first_token 键 (从未记录)
        self.assertNotIn("first_token", self.ctc._turns[t.turn_id].latency,
                         "turn.latency 中无 first_token 写入点 → TTFT=llm_start-turn_start 失真")

    def test_r1_illegal_transition_still_applies(self):
        """R1 实证: 非法迁移 (COMPLETED → STREAMING) 仅警告仍执行

        原因: _transition 对非法迁移只 warning, 之后照样赋值
        后果: 状态机形同虚设 (生产日志已见 QUEUED→STREAMING 实例)
        """
        t = self.ctc.begin_turn("A")
        self.ctc.claim_ready_turn()
        self.ctc.complete_turn(t.turn_id)      # 先正常走完
        self.ctc.mark_streaming(t.turn_id)     # COMPLETED → STREAMING (非法)
        self.assertEqual(self.ctc._turns[t.turn_id].state, "STREAMING",
                         "非法迁移仍被实际执行")


class TestInputAggregator(unittest.TestCase):
    """输入治理审计: 1000 条直播风格模拟 + 优先级"""

    def test_1000_messages_live_style(self):
        """模拟直播 1000 条: 重要/普通/闲聊/噪声/重复混合输入

        断言: 全部处理无崩溃; 重复被合并; 噪声被丢弃; 队列 ≤ 上限
        (注意: 模块本身正确, 但生产未接线 → 见报告 Critical #7)
        """
        agg = InputAggregator(max_queue=30)    # 队列上限 30 (同生产默认)
        texts = []
        # 构造 1000 条: 200 重要 + 20 重复 + 300 普通 + 300 闲聊 + 200 噪声
        for i in range(200):
            texts.append(f"请马上回答我的问题{i}号")   # important (含关键词)
        for i in range(20):
            texts.append("请马上回答我的问题7号")      # 重复文本 → 应合并
        for i in range(300):
            texts.append(f"随便聊聊今天天气如何{i}")    # normal (无关键词)
        for i in range(300):
            texts.append(f"哈哈哈哈哈{i}")             # chat (闲聊关键词)
        for i in range(200):
            texts.append("啊")                         # noise (≤4字无意义)
        n_dropped_noise = 0
        n_merged = 0
        # 逐条注入, 跟踪累计统计 (合并/丢弃计数)
        for i, text in enumerate(texts):
            ok = agg.process(text)             # 单条治理入口
            st = agg.stats()                   # 实时统计快照
            if st["dropped"] > n_dropped_noise + st["merged"]:
                n_dropped_noise = st["dropped"]
            if st["merged"] > n_merged:
                n_merged = st["merged"]
        st = agg.stats()
        self.assertGreaterEqual(st["processed"], 1000)  # 全部被处理
        self.assertGreaterEqual(st["merged"], 1, "重复输入应被合并")
        self.assertGreaterEqual(st["dropped"], 1, "噪声应被丢弃")
        # 队满行为: 队列长度不超上限 (挤压/拒收兜底)
        qlen = agg.queue_length()
        self.assertLessEqual(qlen, 30)

    def test_priority_order(self):
        """优先级排序: important 必须最先弹出 (其次 normal, 最后 chat)"""
        agg = InputAggregator(max_queue=30)
        agg.process("今天天气怎么样")          # normal (无关键词)
        agg.process("哈哈哈哈哈")              # chat
        agg.process("请帮我修复这个bug")        # important (含 bug)
        items = [agg.next() for _ in range(3)]  # 依次弹出全部
        texts = [it.text for it in items]
        self.assertIn("请帮我修复这个bug", texts[:1], f"important 应最先: {texts}")


class TestContextManager(unittest.TestCase):
    """上下文审计: 20 轮窗口 8 + 压缩触发 + 不对称性观察"""

    def test_20_turns_window_8(self):
        """20 轮对话 (40 条消息) → 窗口必须裁剪到 ≤8 条"""
        cm = ContextManager()
        for i in range(20):
            cm.add_message("user", f"用户第{i}轮提问")
            cm.add_message("assistant", f"助手第{i}轮回答")
        ctx = cm.get_context()                 # 取上下文 (默认 recent_messages=10)
        history = [m for m in ctx if m["role"] in ("user", "assistant")]
        self.assertLessEqual(len(history), 8, "窗口应裁剪到 8 条")

    def test_compression_triggers(self):
        """12 轮超窗 → 工作摘要生成且保留"目标"字段"""
        cm = ContextManager()
        for i in range(12):
            cm.add_message("user", f"我的目标是完成任务{i}")      # 含"目标"关键词
            cm.add_message("assistant", f"结论: 方案{i}已确认")    # 含"结论"关键词
        self.assertIsNotNone(cm.summary, "超窗后应生成工作摘要")
        self.assertIn("目标", cm.summary)      # 保留字段: 用户目标

    def test_window_asymmetry(self):
        """窗口裁剪不对称性观察: 可能出现 user 被裁 assistant 残留

        说明: 6 轮 (12 条) 裁到 8 条时按条数滑动, 不对齐轮次,
              存在"assistant 保留但其 user 问题被裁"的风险 (串话隐患)
        """
        cm = ContextManager()
        for i in range(6):
            cm.add_message("user", f"u{i}")
            cm.add_message("assistant", f"a{i}")
        ctx = cm.get_context()
        last = ctx[-1] if ctx else None
        # 仅观察输出 (不断言: 记录实际裁剪行为供报告引用)
        print(f"[info] 窗口不对称检查: 末条 role={last.get('role') if last else None}")


if __name__ == "__main__":
    unittest.main(verbosity=2)  # 详细模式: 每个用例独立一行 (审计可读性)
