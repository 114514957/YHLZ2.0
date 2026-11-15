# -*- coding: utf-8 -*-
"""工具预算单测 + 省多少 token 的实测（不联网）。"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm_workbench"))

from backend import tool_budget as TB  # noqa: E402


class LevelTest(unittest.TestCase):
    def test_casual(self):
        for q in ("在吗", "晚安", "今天好热", "你吃饭了吗"):
            self.assertEqual("casual", TB.level_of(q), q)

    def test_normal(self):
        # 检索类（读）不属 work：不该吃全量 43 个工具
        for q in ("你还记得我上次说的吗", "查一下台账里上次那条", "黄河为什么叫母亲河"):
            self.assertEqual("normal", TB.level_of(q), q)

    def test_work(self):
        for q in ("改一下这个脚本", "跑一下测试", "把评测结果导出", "重启服务并看日志"):
            self.assertEqual("work", TB.level_of(q), q)


class SelectTest(unittest.TestCase):
    def setUp(self):
        os.environ["YHLZ_TOOL_BUDGET"] = "1"
        self.tools = [{"type": "function", "function": {"name": n}}
                      for n in list(TB.CORE) + list(TB.RETRIEVAL) + ["file_download",
                                                                     "member_profile",
                                                                     "skill_add"]]

    def tearDown(self):
        os.environ.pop("YHLZ_TOOL_BUDGET", None)

    def test_casual_is_small(self):
        got = TB.select(self.tools, "在吗")
        self.assertEqual(len(got), len(TB.CORE))

    def test_work_is_full(self):
        self.assertEqual(len(TB.select(self.tools, "改一下这个脚本")), len(self.tools))

    def test_disabled_returns_all(self):
        os.environ.pop("YHLZ_TOOL_BUDGET", None)
        self.assertEqual(len(TB.select(self.tools, "在吗")), len(self.tools))

    def test_allowed_narrows(self):
        got = TB.select(self.tools, "查台账", allowed={"ledger_search"})
        self.assertEqual([t["function"]["name"] for t in got], ["ledger_search"])

    def test_never_empty(self):
        got = TB.select(self.tools, "改脚本", allowed=set())
        self.assertTrue(got, "裁到空就必须回退成全量")


class SavingsTest(unittest.TestCase):
    def test_token_saving(self):
        try:
            from transformers import AutoTokenizer
        except Exception:  # noqa: BLE001
            self.skipTest("没有 tokenizer")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tok = AutoTokenizer.from_pretrained(
            os.path.join(root, "models", "gemma4-hf", "gemma-4-e4b-it"))
        try:
            import evals as EV
            tools = EV.load_tools()
        except Exception:  # noqa: BLE001
            self.skipTest("读不到工具定义")
        os.environ["YHLZ_TOOL_BUDGET"] = "1"
        try:
            def n(ts):
                return len(tok(json.dumps(ts, ensure_ascii=False),
                               add_special_tokens=False)["input_ids"])
            full = n(tools)
            casual = n(TB.select(tools, "在吗"))
            normal = n(TB.select(tools, "查一下台账里权重的事"))
            print("\n   全量 %d token｜casual %d｜normal %d"
                  % (full, casual, normal))
            self.assertLess(casual, full * 0.4, "casual 应省一半以上")
        finally:
            os.environ.pop("YHLZ_TOOL_BUDGET", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
