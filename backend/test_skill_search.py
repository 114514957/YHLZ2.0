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
        kb.kb_add("技能：QQ知识捕获与导出运维|触发场景：涉及QQ群知识/导出历史/捕获链路",
                  category="skill", detail="步骤：qq.status看链路；qq.export导历史；qq.process抽取。")
        kb.kb_add("技能：数据口径与汇报规范|触发场景：报数字/说明数据/口径说法",
                  category="skill", detail="步骤：候选=all.jsonl；知识=yuanheng_kb。")

    def tearDown(self):
        kb.DEFAULT_KB_DB = self._kb
        sched._PROJECT_ROOT = self._root

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


if __name__ == "__main__":
    unittest.main()
