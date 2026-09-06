"""Digital-nerve signal capture tests (ledger 0193)."""
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backend.target_signals as sg  # noqa: E402


class SignalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "signals.jsonl"
        self._f = sg.SIGNALS_FILE
        sg.SIGNALS_FILE = self.tmp

    def tearDown(self):
        sg.SIGNALS_FILE = self._f

    def test_classify(self):
        self.assertEqual(sg.classify_signal("很好，这个方案不错"), "praise")
        self.assertEqual(sg.classify_signal("你太啰嗦了"), "critique")
        self.assertEqual(sg.classify_signal("我之前说错了"), "correction")
        self.assertEqual(sg.classify_signal("今天下雨记得带伞"), "")

    def test_capture_and_count(self):
        self.assertEqual(sg.capture("很好，继续"), "signal:praise")
        self.assertEqual(sg.capture("这样不行"), "signal:critique")
        self.assertEqual(sg.capture("普通聊天"), "")
        self.assertEqual(sg.count(), {"praise": 1, "critique": 1})
        lines = self.tmp.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()


class FakeLLM:
    async def __call__(self, messages, tools):
        import json as _j
        return {"content": _j.dumps({"suggestions": [{
            "target": "style", "dimension": "concise",
            "suggestion": "回答更简短直接，少客套",
            "reason": "多次被批评啰嗦"}]}, ensure_ascii=False)}


class SuggestTest(unittest.TestCase):
    def setUp(self):
        import asyncio
        self.tmp = Path(tempfile.mkdtemp()) / "s.jsonl"
        self._f = sg.SIGNALS_FILE
        sg.SIGNALS_FILE = self.tmp

    def tearDown(self):
        sg.SIGNALS_FILE = self._f

    def test_too_few_signals(self):
        import asyncio
        out = asyncio.run(sg.suggest(FakeLLM()))
        self.assertFalse(out["ok"])
        self.assertIn("太少", out["reason"])

    def test_suggest_parses(self):
        import asyncio
        lines = ["praise 很好", "critique 太啰嗦了", "critique 又啰嗦", "praise 简洁就好"]
        self.tmp.write_text("\n".join(
            '{"ts": %d, "kind": "%s", "text": "%s", "channel": "p"}' % (i, l.split()[0], l.split()[1]) for i, l in enumerate(lines)), encoding="utf-8")
        out = asyncio.run(sg.suggest(FakeLLM()))
        self.assertTrue(out["ok"])
        self.assertEqual(out["suggestions"][0]["target"], "style")
