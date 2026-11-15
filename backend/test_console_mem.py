"""Workbench memory page (W1-W4 surface): /mem query params + /mem/lifecycle."""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, r"C:\Users\ACE_WA~1\YHLZ\YH")

from backend.console_server import ConsoleHandler  # noqa: E402


class _FakeMemory:
    def __init__(self) -> None:
        self.calls = []
        self.lifecycle_calls = 0

    def recall(self, query, limit=5, time_start=0.0, time_end=0.0):
        self.calls.append({"query": query, "limit": limit,
                           "start": time_start, "end": time_end})
        return [{"id": "m1", "type": "preference", "importance": 8,
                 "status": "active", "summary": "老爹喜欢冰美式",
                 "score": 0.812, "_channels": ["literal", "bm25"]}]

    def health(self):
        return {"l2_items": 877, "l2_active": 329, "l2_frozen": 4}

    def apply_lifecycle(self):
        self.lifecycle_calls += 1
        return {"enabled": True, "frozen": 2, "revived": 1, "checked": 329}


class _FakeSession:
    def __init__(self, memory):
        self.memory = memory


class _FakeRuntime:
    def __init__(self, memory):
        self._mem = memory

    def _session(self, name):
        return _FakeSession(self._mem)


class _FakeHandler:
    """Minimal stand-in for ConsoleHandler: only what _mem/_do_mem_lifecycle use."""

    path = "/mem"
    runtime = None
    _send_json = ConsoleHandler._send_json
    _mem = ConsoleHandler._mem
    _do_mem_lifecycle = ConsoleHandler._do_mem_lifecycle

    def __init__(self, memory, path="/mem"):
        self.runtime = _FakeRuntime(memory)
        self.path = path
        self.sent = []

    def send_json(self, code, obj):  # replaced bound method
        self.sent.append((code, obj))

    # ConsoleHandler._send_json is called as self._send_json(...)
    def __getattr__(self, item):
        raise AttributeError(item)


class MemPageTests(unittest.TestCase):
    def setUp(self):
        self.memory = _FakeMemory()
        self.handler = _FakeHandler(self.memory)
        self.handler._send_json = lambda code, obj: self.handler.sent.append((code, obj))

    def test_status_without_query(self):
        out = self.handler._mem()
        self.assertTrue(out["ok"])
        self.assertEqual(out["items"], [])
        self.assertEqual(out["lifecycle"]["frozen"], 4)
        self.assertEqual(self.memory.calls, [])

    def test_query_with_window_passes_epochs(self):
        self.handler.path = "/mem?q=%E5%92%96%E5%95%A1&time_start=2026-11-01&time_end=2026-11-10"
        out = self.handler._mem()
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["items"]), 1)
        item = out["items"][0]
        self.assertEqual(item["score"], 0.812)
        self.assertEqual(item["channels"], ["literal", "bm25"])
        call = self.memory.calls[0]
        self.assertEqual(call["query"], "咖啡")
        self.assertGreater(call["start"], 0)
        self.assertGreater(call["end"], call["start"])

    def test_bad_date_is_an_error_not_empty(self):
        self.handler.path = "/mem?q=%E5%92%96%E5%95%A1&time_start=%E4%B8%8A%E5%91%A8"
        out = self.handler._mem()
        self.assertFalse(out["ok"])
        self.assertIn("YYYY-MM-DD", out["error"])
        self.assertEqual(self.memory.calls, [])

    def test_inverted_window_is_an_error(self):
        self.handler.path = "/mem?q=x&time_start=2026-11-10&time_end=2026-11-01"
        out = self.handler._mem()
        self.assertFalse(out["ok"])
        self.assertIn("晚于", out["error"])

    def test_lifecycle_action(self):
        self.handler._do_mem_lifecycle()
        code, body = self.handler.sent[-1]
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["frozen"], 2)
        self.assertEqual(self.memory.lifecycle_calls, 1)


class StaticAssetTests(unittest.TestCase):
    def test_page_has_window_inputs_and_lifecycle_button(self):
        html = open(r"C:\Users\ACE_WA~1\YHLZ\YH\assets\webui\index.html",
                    encoding="utf-8").read()
        for needle in ('id="memFrom"', 'id="memTo"', 'id="memMaint"', 'id="memStat"'):
            self.assertIn(needle, html)

    def test_js_wires_window_and_lifecycle(self):
        js = open(r"C:\Users\ACE_WA~1\YHLZ\YH\assets\webui\console.js",
                  encoding="utf-8").read()
        self.assertIn('params.set("time_start"', js)
        self.assertIn('"/mem/lifecycle"', js)
        self.assertIn("memLifecycle", js)


if __name__ == "__main__":
    unittest.main()
