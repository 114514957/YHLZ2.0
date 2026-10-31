"""B站 queue/notes unit tests (no browser, no worker)."""
from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest

from backend import bili_tools as bt


class BiliToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="bili-test-"))
        self._old = (bt.QUEUE, bt.RESULTS, bt.NOTES, bt.LOCK)
        bt.QUEUE = self.tmp / "queue"
        bt.RESULTS = self.tmp / "results"
        bt.NOTES = self.tmp / "notes"
        bt.LOCK = self.tmp / "worker.lock"
        for d in (bt.QUEUE, bt.RESULTS, bt.NOTES):
            d.mkdir(parents=True, exist_ok=True)
        self._old_ensure = bt.ensure_worker
        bt.ensure_worker = lambda timeout=3.0: 4242

    def tearDown(self) -> None:
        bt.QUEUE, bt.RESULTS, bt.NOTES, bt.LOCK = self._old
        bt.ensure_worker = self._old_ensure
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enqueue_find_creates_queue_file(self) -> None:
        msg = bt.enqueue_find("线性代数", 6)
        self.assertIn("已排队", msg)
        files = list(bt.QUEUE.glob("*.json"))
        self.assertEqual(len(files), 1)
        job = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(job["kind"], "find")
        self.assertEqual(job["params"]["keyword"], "线性代数")
        self.assertEqual(job["params"]["limit"], 6)

    def test_enqueue_rejects_empty_or_bad(self) -> None:
        self.assertIn("需要关键词", bt.enqueue_find("  "))
        self.assertIn("需要 B 站", bt.enqueue_watch("not-a-video"))
        self.assertIn("B 站", bt.enqueue_watch("https://example.com/x"))

    def test_status_lists_queued_and_done(self) -> None:
        job_id = bt.enqueue("watch", {"target": "BV1Va411Y7Ff"})
        done = {"id": "20260101-000000-abcdef", "kind": "find",
                "status": "done", "created_at": 1.0,
                "params": {"keyword": "x"}, "result": {"title": "T"}}
        (bt.RESULTS / "20260101-000000-abcdef.json").write_text(
            json.dumps(done, ensure_ascii=False), encoding="utf-8")
        text = bt.list_jobs(10)
        self.assertIn(job_id, text)
        self.assertIn("[queued]", text)
        self.assertIn("[done]", text)
        self.assertIn("T", text)

    def test_notes_list_and_read(self) -> None:
        note = bt.NOTES / "BV1Va411Y7Ff.md"
        note.write_text(
            "# 标题\n\n- URL: https://x\n- UP: 某人\n- 抓取时间: 2026-10-21 14:30\n"
            "\n## 字幕原文\n\n内容\n\n## 元亨的笔记\n\n判断\n", encoding="utf-8")
        text = bt.recent_notes(5)
        self.assertIn("BV1Va411Y7Ff", text)
        self.assertIn("某人", text)
        self.assertIn("有笔记", text)
        body = bt.read_note("BV1Va411Y7Ff", 100)
        self.assertIn("元亨的笔记", body)
        long_note = bt.NOTES / "BV1Va411Y7Fg.md"
        long_note.write_text("# long\n\n" + "啊" * 800, encoding="utf-8")
        self.assertIn("已截断", bt.read_note("BV1Va411Y7Fg", 500))
        self.assertIn("需要", bt.read_note("nope"))


if __name__ == "__main__":
    unittest.main()
