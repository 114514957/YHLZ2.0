"""Tests for Yuanheng self-tools: task board (task.plan)."""
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import target_scheduler_tools as sched  # noqa: E402


class TaskPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "taskboard.md"
        self._orig = sched.TASK_FILE
        sched.TASK_FILE = self.tmp

    def tearDown(self):
        sched.TASK_FILE = self._orig

    def test_add_list_done_flow(self):
        out = sched.task_plan("测试任务A")
        self.assertIn("已加入", out)
        out = sched.task_plan("读主题总结并写感想")
        self.assertIn("已加入", out)
        listing = sched.task_plan("", action="list")
        self.assertIn("测试任务A", listing)
        self.assertIn("读主题总结并写感想", listing)
        done = sched.task_plan("读主题总结", action="done")
        self.assertIn("已完成", done)
        listing2 = sched.task_plan("", action="list")
        self.assertNotIn("- [ ] 读主题总结", listing2)
        self.assertIn("- [x]", listing2)

    def test_done_not_found(self):
        self.assertIn("没找到", sched.task_plan("不存在的东西", action="done"))

    def test_diary_write_append(self):
        d = self.tmp.parent / "diary.md"
        orig = sched.DIARY_FILE
        sched.DIARY_FILE = d
        try:
            out = sched.diary_write("今天的第一篇")
            self.assertIn("已写入", out)
            out2 = sched.diary_write("同天的第二段")
            self.assertIn("已写入", out2)
            content = d.read_text(encoding="utf-8")
            self.assertIn("今天的第一篇", content)
            self.assertIn("同天的第二段", content)
            lst = sched.diary_list(5)
            self.assertIn("同天的第二段", lst)
        finally:
            sched.DIARY_FILE = orig

    def test_policy_registry(self):
        reg = sched.setup_scheduler_capabilities()
        caps = set(reg.names())
        self.assertIn("task.plan", caps)
        self.assertIn("diary.write", caps)
        self.assertTrue(reg.get_policy(sched.TASK_AUTO_POLICY)())


if __name__ == "__main__":
    unittest.main()
