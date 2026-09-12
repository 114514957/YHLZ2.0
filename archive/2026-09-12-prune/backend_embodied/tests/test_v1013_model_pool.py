"""
YHLZ Model Pool Router V10.1.3 测试

覆盖:
    - 模型注册表 (登记/查询/列表/状态/Token消耗/错误)
    - 任务分类器 (8 类)
    - 模型选择器 (评分/Token等级/切换判定)
    - 交接协议 (创建/上下文/历史)
    - 模型池门面 (路由/执行/切换/状态面板/调用记录)
"""
import unittest

from backend.model_pool import (
    ModelEntry,
    ModelPoolError,
    ModelPoolRouter,
)
from backend.model_pool.handoff import ModelHandoff
from backend.model_pool.registry import (
    ModelRegistry,
    ModelRegistryError,
)
from backend.model_pool.selector import (
    ModelSelector,
    TOKEN_LEVELS,
    TOKEN_RED_THRESHOLD,
    TOKEN_YELLOW_THRESHOLD,
)
from backend.model_pool.task_classifier import (
    TaskClassifier,
    TASK_TYPES,
)


def make_pool():
    pool = ModelPoolRouter()
    pool.register_defaults()
    return pool


class TestModelRegistry(unittest.TestCase):
    """模型注册表"""

    def setUp(self):
        self.reg = ModelRegistry()

    def _entry(self, mid="m1", mtype="fast", cap=None,
               remaining=1_000_000):
        return ModelEntry(
            model_id=mid, model_name=mid, provider="test",
            model_type=mtype, capability=cap or ["chat"],
            token_limit=1_000_000, remaining_token=remaining,
        )

    def test_register(self):
        r = self.reg.register(self._entry())
        self.assertTrue(r["ok"])
        self.assertEqual(self.reg.count(), 1)

    def test_get(self):
        self.reg.register(self._entry("m1"))
        e = self.reg.get("m1")
        self.assertEqual(e["model_id"], "m1")
        self.assertEqual(e["used_token"], 0)

    def test_get_missing(self):
        self.assertIsNone(self.reg.get("nope"))

    def test_list_filter_type(self):
        self.reg.register(self._entry("m1", "fast"))
        self.reg.register(self._entry("m2", "main"))
        self.assertEqual(len(self.reg.list(model_type="fast")), 1)

    def test_list_filter_status(self):
        self.reg.register(self._entry("m1"))
        self.reg.update_status("m1", "disabled")
        self.assertEqual(len(self.reg.list(status="disabled")), 1)

    def test_unregister(self):
        self.reg.register(self._entry("m1"))
        self.assertTrue(self.reg.unregister("m1"))
        self.assertFalse(self.reg.unregister("m1"))

    def test_consume_token(self):
        self.reg.register(self._entry("m1", remaining=1000))
        r = self.reg.consume_token("m1", 400)
        self.assertEqual(r["remaining_token"], 600)

    def test_consume_token_floor(self):
        self.reg.register(self._entry("m1", remaining=100))
        self.reg.consume_token("m1", 500)
        self.assertEqual(self.reg.get("m1")["remaining_token"], 0)

    def test_record_error(self):
        self.reg.register(self._entry("m1"))
        self.reg.record_error("m1")
        self.reg.record_error("m1")
        self.assertEqual(self.reg.get("m1")["error_count"], 2)

    def test_update_status_invalid(self):
        self.reg.register(self._entry("m1"))
        with self.assertRaises(ModelRegistryError):
            self.reg.update_status("m1", "bad")

    def test_invalid_type(self):
        with self.assertRaises(ModelRegistryError):
            ModelEntry(model_id="x", model_name="x",
                       provider="p", model_type="bad")

    def test_stats(self):
        self.reg.register(self._entry("m1", "fast"))
        self.reg.register(self._entry("m2", "main"))
        s = self.reg.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_type"]["fast"], 1)

    def test_clear(self):
        self.reg.register(self._entry("m1"))
        self.assertEqual(self.reg.clear(), 1)

    def test_disabled(self):
        reg = ModelRegistry(enabled=False)
        r = reg.register(self._entry())
        self.assertEqual(r["mode"], "error_frame")


class TestTaskClassifier(unittest.TestCase):
    """任务分类器"""

    def setUp(self):
        self.tc = TaskClassifier()

    def test_coding(self):
        r = self.tc.classify("帮我写一个python函数")
        self.assertEqual(r["task_type"], "CODING")

    def test_engineering(self):
        r = self.tc.classify("设计一个系统架构")
        self.assertEqual(r["task_type"], "ENGINEERING")

    def test_reasoning(self):
        r = self.tc.classify("为什么天空是蓝色的")
        self.assertEqual(r["task_type"], "REASONING")

    def test_vision(self):
        r = self.tc.classify("分析这张图片")
        self.assertEqual(r["task_type"], "VISION")

    def test_memory(self):
        r = self.tc.classify("你还记得上次说的吗")
        self.assertEqual(r["task_type"], "MEMORY")

    def test_summary(self):
        r = self.tc.classify("总结一下这段内容")
        self.assertEqual(r["task_type"], "SUMMARY")

    def test_knowledge(self):
        r = self.tc.classify("什么是机器学习")
        self.assertEqual(r["task_type"], "KNOWLEDGE")

    def test_default_chat(self):
        r = self.tc.classify("今天天气不错")
        self.assertEqual(r["task_type"], "CHAT")

    def test_reason_explainable(self):
        r = self.tc.classify("帮我写一个python函数")
        self.assertIn("命中关键词", r["reason"])

    def test_confidence(self):
        r = self.tc.classify("帮我写一个python函数处理bug")
        self.assertGreaterEqual(r["confidence"], 0.5)

    def test_task_types_enum(self):
        self.assertEqual(TASK_TYPES, [
            "CHAT", "KNOWLEDGE", "CODING", "ENGINEERING",
            "REASONING", "VISION", "MEMORY", "SUMMARY",
        ])

    def test_empty_text(self):
        r = self.tc.classify("")
        self.assertEqual(r["task_type"], "CHAT")

    def test_stats(self):
        self.tc.classify("写代码")
        self.assertEqual(self.tc.stats()["classify_count"], 1)

    def test_disabled(self):
        tc = TaskClassifier(enabled=False)
        r = tc.classify("x")
        self.assertEqual(r["mode"], "error_frame")


class TestModelSelector(unittest.TestCase):
    """模型选择器"""

    def setUp(self):
        self.sel = ModelSelector()

    def _entries(self):
        return [
            {"model_id": "main1", "capability": ["chat", "code"],
             "token_limit": 1_000_000, "remaining_token": 1_000_000,
             "cost_per_1k": 0.001, "latency_ms": 800.0,
             "status": "active"},
            {"model_id": "fast1", "capability": ["chat", "summary"],
             "token_limit": 1_000_000, "remaining_token": 1_000_000,
             "cost_per_1k": 0.0003, "latency_ms": 400.0,
             "status": "active"},
        ]

    def test_select_capability_priority(self):
        entries = self._entries()
        r = self.sel.select(entries, "CODING")
        self.assertEqual(r["selected"]["model_id"], "main1")
        self.assertTrue(r["ok"])

    def test_select_no_available(self):
        entries = [
            {"model_id": "x", "capability": ["chat"],
             "token_limit": 100, "remaining_token": 0,
             "cost_per_1k": 0, "latency_ms": 0,
             "status": "active"},
        ]
        r = self.sel.select(entries, "CHAT")
        self.assertFalse(r["ok"])
        self.assertIsNone(r["selected"])

    def test_select_disabled_excluded(self):
        entries = self._entries()
        entries[0]["status"] = "disabled"
        r = self.sel.select(entries, "CODING")
        self.assertEqual(r["selected"]["model_id"], "fast1")

    def test_candidates_listed(self):
        entries = self._entries()
        r = self.sel.select(entries, "CHAT")
        self.assertEqual(len(r["candidates"]), 2)

    def test_reason(self):
        entries = self._entries()
        r = self.sel.select(entries, "CHAT")
        self.assertIn("score", r["reason"])

    def test_token_level_green(self):
        self.assertEqual(
            self.sel.token_level(800_000, 1_000_000), "GREEN",
        )

    def test_token_level_yellow(self):
        self.assertEqual(
            self.sel.token_level(200_000, 1_000_000), "YELLOW",
        )

    def test_token_level_red(self):
        self.assertEqual(
            self.sel.token_level(50_000, 1_000_000), "RED",
        )

    def test_should_switch_token(self):
        entry = {"remaining_token": 50_000, "token_limit": 1_000_000,
                 "error_count": 0, "status": "active",
                 "latency_ms": 100.0}
        r = self.sel.should_switch(entry)
        self.assertTrue(r["switch"])
        self.assertIn("Token", r["reasons"][0])

    def test_should_switch_error(self):
        entry = {"remaining_token": 1_000_000,
                 "token_limit": 1_000_000, "error_count": 5,
                 "status": "active", "latency_ms": 100.0}
        r = self.sel.should_switch(entry)
        self.assertTrue(r["switch"])

    def test_should_switch_latency(self):
        entry = {"remaining_token": 1_000_000,
                 "token_limit": 1_000_000, "error_count": 0,
                 "status": "active", "latency_ms": 6000.0}
        r = self.sel.should_switch(entry)
        self.assertTrue(r["switch"])

    def test_no_switch(self):
        entry = {"remaining_token": 900_000,
                 "token_limit": 1_000_000, "error_count": 0,
                 "status": "active", "latency_ms": 100.0}
        r = self.sel.should_switch(entry)
        self.assertFalse(r["switch"])

    def test_switch_thresholds_enum(self):
        self.assertEqual(TOKEN_LEVELS, ["GREEN", "YELLOW", "RED"])
        self.assertLess(TOKEN_RED_THRESHOLD, TOKEN_YELLOW_THRESHOLD)

    def test_stats(self):
        self.sel.select(self._entries(), "CHAT")
        self.assertEqual(self.sel.stats()["select_count"], 1)


class TestModelHandoff(unittest.TestCase):
    """交接协议"""

    def setUp(self):
        self.h = ModelHandoff()

    def test_create(self):
        r = self.h.create(
            from_model="a", to_model="b",
            user="老万", project="YHLZ", task="热机",
        )
        self.assertTrue(r["handoff_id"].startswith("ho_"))
        self.assertEqual(r["from_model"], "a")
        self.assertEqual(r["to_model"], "b")

    def test_context_for_model(self):
        self.h.create(from_model="a", to_model="b", task="t1")
        ctx = self.h.context_for_model("b")
        self.assertTrue(ctx["identity_anchor_loaded"])
        self.assertEqual(ctx["handoff"]["to_model"], "b")

    def test_context_no_handoff(self):
        ctx = self.h.context_for_model("nope")
        self.assertIsNone(ctx["handoff"])

    def test_history(self):
        self.h.create(from_model="a", to_model="b", task="t1")
        self.h.create(from_model="b", to_model="c", task="t2")
        self.assertEqual(len(self.h.history()), 2)

    def test_history_by_model(self):
        self.h.create(from_model="a", to_model="b", task="t1")
        self.h.create(from_model="b", to_model="c", task="t2")
        # a 只作为 from_model 出现 (t1)
        self.assertEqual(len(self.h.history(model_id="a")), 1)
        # b 作为 from (t2) 和 to (t1) 出现
        self.assertEqual(len(self.h.history(model_id="b")), 2)
        self.assertEqual(len(self.h.history(model_id="c")), 1)

    def test_stats(self):
        self.h.create(from_model="a", to_model="b")
        self.assertEqual(self.h.stats()["total_handoffs"], 1)

    def test_max_records(self):
        h = ModelHandoff(max_records=3)
        for i in range(6):
            h.create(from_model=f"a{i}", to_model="b")
        self.assertEqual(h.stats()["total_handoffs"], 3)

    def test_clear(self):
        self.h.create(from_model="a", to_model="b")
        self.assertEqual(self.h.clear(), 1)


class TestModelPoolRouter(unittest.TestCase):
    """模型池门面"""

    def test_register_defaults(self):
        pool = make_pool()
        self.assertEqual(pool.stats()["registry"]["total"], 5)

    def test_route_coding(self):
        pool = make_pool()
        r = pool.route("帮我写一个python函数")
        self.assertEqual(r["task_type"], "CODING")
        self.assertIsNotNone(r["selected"])

    def test_route_chat(self):
        pool = make_pool()
        r = pool.route("随便聊聊")
        self.assertEqual(r["task_type"], "CHAT")

    def test_route_fallback_when_all_disabled(self):
        pool = make_pool()
        for e in pool._registry.list():
            pool._registry.update_status(e["model_id"], "disabled")
        r = pool.route("聊天")
        self.assertTrue(r["fallback_mode"])

    def test_execute(self):
        pool = make_pool()
        r = pool.execute("qwen-turbo", "CHAT", lambda: "hi",
                         token_used=100)
        self.assertTrue(r["ok"])
        self.assertEqual(r["token_used"], 100)

    def test_execute_error(self):
        pool = make_pool()
        r = pool.execute("qwen-turbo", "CHAT",
                         lambda: 1 / 0, token_used=0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "division by zero")

    def test_execute_records_error_count(self):
        pool = make_pool()
        pool.execute("qwen-turbo", "CHAT", lambda: 1 / 0)
        self.assertEqual(
            pool._registry.get("qwen-turbo")["error_count"], 1,
        )

    def test_check_and_switch_token(self):
        pool = make_pool()
        pool._registry.consume_token("qwen-turbo", 950_000)
        r = pool.check_and_switch("qwen-turbo", task="t",
                                  user="u", project="p")
        self.assertTrue(r["switch"])
        self.assertIn("to_model", r)

    def test_check_and_switch_no(self):
        pool = make_pool()
        r = pool.check_and_switch("qwen-turbo")
        self.assertFalse(r["switch"])

    def test_check_and_switch_fallback(self):
        pool = make_pool()
        # 停用其他所有模型, 只剩 qwen-turbo
        for e in pool._registry.list():
            if e["model_id"] != "qwen-turbo":
                pool._registry.update_status(
                    e["model_id"], "disabled",
                )
        pool._registry.consume_token("qwen-turbo", 950_000)
        r = pool.check_and_switch("qwen-turbo")
        self.assertTrue(r["switch"])
        self.assertTrue(r["fallback_mode"])

    def test_model_status_panel(self):
        pool = make_pool()
        s = pool.model_status()
        self.assertEqual(len(s["models"]), 5)
        self.assertGreater(s["total_remaining_token"], 0)

    def test_call_history(self):
        pool = make_pool()
        pool.execute("qwen-turbo", "CHAT", lambda: 1)
        pool.execute("qwen-turbo", "CHAT", lambda: 2)
        h = pool.call_history()
        self.assertEqual(len(h), 2)

    def test_call_history_by_model(self):
        pool = make_pool()
        pool.execute("qwen-turbo", "CHAT", lambda: 1)
        pool.execute("qwen-vl-plus", "VISION", lambda: 2)
        h = pool.call_history(model_id="qwen-turbo")
        self.assertEqual(len(h), 1)

    def test_stats_structure(self):
        pool = make_pool()
        s = pool.stats()
        for key in ("registry", "classifier", "selector",
                    "handoff", "call_records"):
            self.assertIn(key, s)

    def test_disabled(self):
        pool = ModelPoolRouter(enabled=False)
        r = pool.route("聊天")
        self.assertEqual(r["mode"], "error_frame")

    def test_clear(self):
        pool = make_pool()
        pool.execute("qwen-turbo", "CHAT", lambda: 1)
        n = pool.clear()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(pool.stats()["registry"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
