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
