"""Tests for skill search/add against an isolated KB."""
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import target_scheduler_tools as sched  # noqa: E402
from backend import yuanheng_kb as kb  # noqa: E402


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._kb = kb.DEFAULT_KB_DB
        kb.DEFAULT_KB_DB = self.tmp / "kb.db"
        # isolate the pending-drafts directory so tests never pollute the repo
        self._root = sched._PROJECT_ROOT
        sched._PROJECT_ROOT = self.tmp
        self._seen = sched._SKILL_SEEN
        sched._SKILL_SEEN = self.tmp / "seen.json"
        kb.kb_add("技能：QQ知识捕获与导出运维|触发场景：涉及QQ群知识/导出历史/捕获链路",
                  category="skill", detail="步骤：qq.status看链路；qq.export导历史；qq.process抽取。")
        kb.kb_add("技能：数据口径与汇报规范|触发场景：报数字/说明数据/口径说法",
                  category="skill", detail="步骤：候选=all.jsonl；知识=yuanheng_kb。")

    def tearDown(self):
        kb.DEFAULT_KB_DB = self._kb
        sched._PROJECT_ROOT = self._root
        sched._SKILL_SEEN = self._seen

    def test_search_known_fragment(self):
        out = sched.skill_search("导出历史")
        self.assertIn("QQ知识捕获与导出运维", out)

    def test_search_fallback_lists_all(self):
        out = sched.skill_search("完全不相关的词xyz")
        self.assertIn("QQ知识捕获与导出运维", out)
        self.assertIn("数据口径与汇报规范", out)

    def test_skill_add_draft(self):
        r = sched.skill_add("测试技能", "当X时", "1.做A\n2.做B")
        self.assertIn("技能草稿已提交", r)
        p = Path(r.split("：", 1)[1])
        self.assertTrue(p.exists())
        content = p.read_text(encoding="utf-8")
        self.assertIn("触发场景：当X时", content)
        self.assertIn("做A", content)

    def test_skill_learn_draft_and_dedup(self):
        import asyncio
        import json

        calls = {"n": 0}

        async def fake_llm(messages, tools):
            calls["n"] += 1
            return {"content": json.dumps(
                {"name": "检索并入库", "trigger": "需要查并保存时",
                 "steps": "1. web_search\n2. kb_add"})}

        uses = [{"name": "web_search", "ok": True, "arguments": "{}"},
                {"name": "kb_add", "ok": True, "arguments": "{}"}]
        p1 = asyncio.run(sched.skill_learn("帮我查并保存", uses, "done", fake_llm))
        self.assertTrue(p1 and Path(p1).exists())
        self.assertIn("检索并入库", Path(p1).read_text(encoding="utf-8"))
        # dedup: same pattern -> no second draft, no second LLM call
        p2 = asyncio.run(sched.skill_learn("帮我查并保存", uses, "done", fake_llm))
        self.assertEqual(p2, "")
        self.assertEqual(calls["n"], 1)

    def test_skill_learn_needs_two_tools(self):
        import asyncio

        async def fake_llm(messages, tools):
            raise AssertionError("should not be called")

        uses = [{"name": "web_search", "ok": True, "arguments": "{}"}]
        self.assertEqual(
            asyncio.run(sched.skill_learn("查一下", uses, "done", fake_llm)), "")

    def test_skill_inject_on_trigger(self):
        out = sched.skill_inject("涉及QQ群知识/导出历史/捕获链路")
        self.assertIn("QQ知识捕获与导出运维", out)
        self.assertIn("可用技能", out)

    def test_skill_inject_no_match(self):
        self.assertEqual(sched.skill_inject("zzz完全没有关联的xyzzy词"), "")


if __name__ == "__main__":
    unittest.main()
