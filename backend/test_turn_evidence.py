"""R1 证据底座测试（ledger 0592）：关联 id + 写类工具载体独立读回。"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

import backend.target_schedule as sched
import backend.target_scheduler_tools as st
import backend.turn_evidence as te
import backend.yuanheng_kb as kb


class ReadbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="r1_ev_"))
        self._diary = st.DIARY_FILE
        self._task = st.TASK_FILE
        self._sched = sched.SCHED_FILE
        self._kb = kb.DEFAULT_KB_DB
        st.DIARY_FILE = self.tmp / "diary.md"
        st.TASK_FILE = self.tmp / "task.md"
        sched.SCHED_FILE = self.tmp / "sched.json"
        kb.DEFAULT_KB_DB = self.tmp / "kb.db"

    def tearDown(self):
        st.DIARY_FILE = self._diary
        st.TASK_FILE = self._task
        sched.SCHED_FILE = self._sched
        kb.DEFAULT_KB_DB = self._kb

    def test_new_id_unique(self):
        a, b = te.new_id("tr"), te.new_id("tr")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("tr_"))

    def test_diary_write_verified_and_missing(self):
        st.DIARY_FILE.write_text("今天试着写了一篇日记。", encoding="utf-8")
        ok = te.readback("diary.write", {"content": "今天试着写了一篇日记"})
        self.assertEqual(ok["status"], "verified")
        miss = te.readback("diary.write", {"content": "完全不存在的内容ZZZ"})
        self.assertEqual(miss["status"], "effect_missing")

    def test_task_plan_verified(self):
        st.TASK_FILE.write_text("- [ ] 整理素材", encoding="utf-8")
        r = te.readback("task.plan", {"action": "add", "content": "整理素材"})
        self.assertEqual(r["status"], "verified")

    def test_schedule_plan_verified(self):
        sched.SCHED_FILE.write_text('{"plans":[{"name":"早课"}]}', encoding="utf-8")
        r = te.readback("schedule.plan", {"action": "add", "name": "早课"})
        self.assertEqual(r["status"], "verified")

    def test_kb_add_verified(self):
        kb.kb_add(summary="R1 读回测试项", category="tech")
        r = te.readback("kb.add", {"summary": "R1 读回测试项"})
        self.assertEqual(r["status"], "verified")

    def test_read_only_unsupported(self):
        r = te.readback("ledger.search", {"query": "x"})
        self.assertEqual(r["status"], "unsupported")

    def test_readback_no_change_is_effect_missing(self):
        # E1 反例：载体里本来就有同前缀旧记录，但本次没写 → 不得 verified
        st.DIARY_FILE.write_text("旧记录：老爹怕冷（历史）", encoding="utf-8")
        before = te.carrier_state("diary.write")
        r = te.readback("diary.write", {"content": "老爹怕冷"}, before=before)
        self.assertEqual(r["status"], "effect_missing")
        self.assertIn("未见变化", r["detail"])

    def test_readback_with_change_and_needle_is_verified(self):
        st.DIARY_FILE.write_text("旧记录：老爹怕冷（历史）", encoding="utf-8")
        before = te.carrier_state("diary.write")
        st.DIARY_FILE.write_text("旧记录：老爹怕冷（历史）\n新写：老爹怕冷，空调别太低。\n",
                                 encoding="utf-8")
        r = te.readback("diary.write", {"content": "老爹怕冷，空调别太低"}, before=before)
        self.assertEqual(r["status"], "verified")

    def test_readback_idempotent_existing(self):
        st.DIARY_FILE.write_text("已有：老爹怕冷（旧）", encoding="utf-8")
        before = te.carrier_state("diary.write", {"content": "老爹怕冷"})
        r = te.readback("diary.write", {"content": "老爹怕冷"}, before=before)
        self.assertEqual(r["status"], "idempotent_existing")

    def test_kb_exact_not_fuzzy(self):
        kb.kb_add(summary="R1 精确条目测试", category="tech")
        self.assertEqual(te.readback("kb.add", {"summary": "R1 精确条目测试"})["status"],
                         "verified")
        self.assertEqual(te.readback("kb.add", {"summary": "R1 精确条目"})["status"],
                         "effect_missing")

    def test_task_done_requires_x(self):
        st.TASK_FILE.write_text("- [ ] 整理素材\n", encoding="utf-8")
        before = te.carrier_state("task.plan", {"content": "整理素材"})
        r = te.readback("task.plan", {"action": "done", "content": "整理素材"}, before=before)
        self.assertEqual(r["status"], "effect_missing")
        st.TASK_FILE.write_text("- [x] 整理素材\n", encoding="utf-8")
        r2 = te.readback("task.plan", {"action": "done", "content": "整理素材"}, before=before)
        self.assertEqual(r2["status"], "verified")

    def test_memory_probe_verified_missing_and_unbound(self):
        te.set_memory_probe(None)
        self.assertEqual(te.readback("memory_save", {"content": "x"})["status"], "unsupported")
        te.set_memory_probe(lambda needle: {"found": True, "id": "m1", "version": 2})
        ok = te.readback("memory_save", {"content": "老爹怕冷"})
        self.assertEqual(ok["status"], "verified")
        self.assertEqual(ok["effect_id"] != "", True)
        te.set_memory_probe(lambda needle: {"found": False})
        self.assertEqual(te.readback("memory_save", {"content": "nope"})["status"],
                         "effect_missing")
        te.set_memory_probe(None)

    def test_summarize_hides_raw_args(self):
        class U:
            name = "diary.write"
            ok = True
            trace_id = "tr_1"
            readback = "verified"
            elapsed_ms = 1.0
            arguments = {"content": "秘密"}
        s = te.summarize([U()])
        self.assertNotIn("秘密", str(s))
        self.assertEqual(s["n"], 1)


if __name__ == "__main__":
    unittest.main()
