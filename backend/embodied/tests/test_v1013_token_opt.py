"""
YHLZ Token Optimization Layer V10.1.3 测试

覆盖:
    - 对话压缩器 (压缩/要点/历史/统计)
    - 响应缓存 (写入/命中/未命中/LRU/命中率)
    - Token 预算 (消耗/状态/建议)
    - 优化门面 (压缩/缓存/预算/效率指标)
"""
import unittest

from backend.token_opt import TokenOptimizer, TokenOptimizerError
from backend.token_opt.budget import BudgetError, TokenBudget
from backend.token_opt.cache import CacheError, ResponseCache
from backend.token_opt.compressor import (
    CompressorError,
    ConversationCompressor,
)


class TestConversationCompressor(unittest.TestCase):
    """对话压缩器"""

    def setUp(self):
        self.cc = ConversationCompressor()

    def test_compress_short(self):
        r = self.cc.compress("短内容")
        self.assertTrue(r["ok"])
        self.assertEqual(r["compressed"], "短内容")

    def test_compress_long(self):
        text = "这是一段很长的对话内容。" * 200
        r = self.cc.compress(text)
        self.assertTrue(r["ok"])
        self.assertLess(r["compressed_len"], r["original_len"])
        self.assertEqual(r["ratio"], 0.1)

    def test_key_points(self):
        r = self.cc.compress("内容", key_points=["结论A"])
        self.assertEqual(r["key_points"], ["结论A"])

    def test_decisions(self):
        r = self.cc.compress("内容", decisions=["决定B"])
        self.assertEqual(r["decisions"], ["决定B"])

    def test_open_questions(self):
        r = self.cc.compress("内容", open_questions=["问题C"])
        self.assertEqual(r["open_questions"], ["问题C"])

    def test_next_steps(self):
        r = self.cc.compress("内容", next_steps=["下一步D"])
        self.assertEqual(r["next_steps"], ["下一步D"])

    def test_reason(self):
        text = "内容" * 100
        r = self.cc.compress(text)
        self.assertIn("压缩", r["reason"])

    def test_empty_text(self):
        r = self.cc.compress("")
        self.assertTrue(r["ok"])
        self.assertEqual(r["compressed_len"], 0)

    def test_history(self):
        self.cc.compress("内容" * 100)
        self.cc.compress("内容" * 200)
        self.assertEqual(len(self.cc.history()), 2)

    def test_stats(self):
        text = "内容" * 100
        self.cc.compress(text)
        s = self.cc.stats()
        self.assertEqual(s["total_compressions"], 1)
        self.assertGreater(s["saved_ratio"], 0.8)

    def test_clear(self):
        self.cc.compress("内容" * 100)
        self.assertEqual(self.cc.clear(), 1)

    def test_disabled(self):
        cc = ConversationCompressor(enabled=False)
        r = cc.compress("x")
        self.assertEqual(r["mode"], "error_frame")

    def test_invalid_ratio(self):
        with self.assertRaises(CompressorError):
            ConversationCompressor(compress_ratio=0.0)

    def test_ratio_over_one(self):
        with self.assertRaises(CompressorError):
            ConversationCompressor(compress_ratio=1.5)


class TestResponseCache(unittest.TestCase):
    """响应缓存"""

    def setUp(self):
        self.rc = ResponseCache()

    def test_put_get(self):
        self.rc.put("问题", "回答")
        self.assertEqual(self.rc.get("问题"), "回答")

    def test_miss(self):
        self.assertIsNone(self.rc.get("没缓存"))

    def test_same_text_same_key(self):
        self.rc.put("相同问题", "A")
        self.assertEqual(self.rc.get("相同问题"), "A")

    def test_diff_text_diff_entry(self):
        self.rc.put("问题1", "A")
        self.rc.put("问题2", "B")
        self.assertEqual(self.rc.get("问题1"), "A")
        self.assertEqual(self.rc.get("问题2"), "B")

    def test_hit_rate(self):
        self.rc.put("q", "a")
        self.rc.get("q")     # hit
        self.rc.get("nope")  # miss
        s = self.rc.stats()
        self.assertEqual(s["hit_count"], 1)
        self.assertEqual(s["miss_count"], 1)
        self.assertEqual(s["hit_rate"], 0.5)

    def test_max_entries(self):
        rc = ResponseCache(max_entries=3)
        for i in range(6):
            rc.put(f"q{i}", f"a{i}")
        self.assertLessEqual(rc.stats()["entries"], 3)

    def test_clear(self):
        self.rc.put("q", "a")
        self.rc.get("q")
        self.assertEqual(self.rc.clear(), 1)
        self.assertEqual(self.rc.stats()["entries"], 0)

    def test_disabled_put(self):
        rc = ResponseCache(enabled=False)
        r = rc.put("q", "a")
        self.assertEqual(r["mode"], "error_frame")

    def test_disabled_get(self):
        rc = ResponseCache(enabled=False)
        rc._enabled = False
        self.assertIsNone(rc.get("q"))

    def test_invalid_max(self):
        with self.assertRaises(CacheError):
            ResponseCache(max_entries=0)


class TestTokenBudget(unittest.TestCase):
    """Token 预算"""

    def setUp(self):
        self.tb = TokenBudget(daily_limit=1000, monthly_limit=10000,
                              emergency_limit=500)

    def test_spend(self):
        r = self.tb.spend(100)
        self.assertTrue(r["ok"])
        self.assertEqual(r["spent"], 100)

    def test_today_usage(self):
        self.tb.spend(200)
        self.tb.spend(300)
        self.assertEqual(self.tb._today_usage(), 500)

    def test_check_green(self):
        self.tb.spend(100)
        s = self.tb.check()
        self.assertEqual(s["level"], "GREEN")

    def test_check_yellow(self):
        self.tb.spend(600)
        s = self.tb.check()
        self.assertEqual(s["level"], "YELLOW")

    def test_check_red(self):
        self.tb.spend(900)
        s = self.tb.check()
        self.assertEqual(s["level"], "RED")
        self.assertIn("降低模型等级", s["suggestion"])

    def test_negative_spend(self):
        with self.assertRaises(BudgetError):
            self.tb.spend(-5)

    def test_stats(self):
        self.tb.spend(100)
        s = self.tb.stats()
        self.assertEqual(s["daily_usage"], 100)

    def test_clear(self):
        self.tb.spend(100)
        self.assertEqual(self.tb.clear(), 1)

    def test_invalid_daily(self):
        with self.assertRaises(BudgetError):
            TokenBudget(daily_limit=0)


class TestTokenOptimizer(unittest.TestCase):
    """Token 优化门面"""

    def setUp(self):
        self.opt = TokenOptimizer()

    def test_compress(self):
        r = self.opt.compress_conversation("内容" * 100)
        self.assertTrue(r["ok"])
        self.assertLess(r["compressed_len"], r["original_len"])

    def test_compress_structured(self):
        r = self.opt.compress_conversation(
            "内容" * 100,
            key_points=["结论"], decisions=["决定"],
            open_questions=["问题"], next_steps=["下一步"],
        )
        self.assertEqual(r["key_points"], ["结论"])
        self.assertEqual(r["next_steps"], ["下一步"])

    def test_cache(self):
        self.opt.cache_response("q", "a")
        self.assertEqual(self.opt.cached_response("q"), "a")
        self.assertIsNone(self.opt.cached_response("nope"))

    def test_spend_budget(self):
        r = self.opt.spend_token(1000)
        self.assertTrue(r["ok"])
        self.assertEqual(self.opt.budget_status()["daily_usage"],
                         1000)

    def test_record_task(self):
        self.opt.spend_token(1000)
        r = self.opt.record_task(done=True, solved=True,
                                 memory_added=2, user_rating=5)
        self.assertTrue(r["recorded"])

    def test_efficiency(self):
        self.opt.spend_token(1000)
        self.opt.record_task(done=True, solved=True,
                             memory_added=2)
        eff = self.opt.efficiency()
        self.assertGreater(eff["token_value_rate"], 0)
        self.assertEqual(eff["effective_tasks"], 1)

    def test_efficiency_empty(self):
        eff = self.opt.efficiency()
        self.assertEqual(eff["total_token"], 0)

    def test_stats_structure(self):
        s = self.opt.stats()
        for key in ("compressor", "cache", "budget",
                    "task_records"):
            self.assertIn(key, s)

    def test_clear(self):
        self.opt.spend_token(100)
        self.opt.cache_response("q", "a")
        n = self.opt.clear()
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
