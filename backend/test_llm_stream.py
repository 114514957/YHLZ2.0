"""llm_stream unified-event protocol tests (ledger 0204)."""
import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.llm_stream import stream_openai_compatible  # noqa: E402

SSE_FRAMES = [
    {"choices": [{"delta": {"reasoning_content": "让我想想"}}]},
    {"choices": [{"delta": {"reasoning_content": "步骤一"}}]},
    {"choices": [{"delta": {"content": "你好"}}]},
    {"choices": [{"delta": {"content": "，我是元亨"}}]},
    {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
]


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for f in SSE_FRAMES:
            self.wfile.write(b"data: " + json.dumps(f, ensure_ascii=False).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")


class StreamProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), _H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_events_unified_and_stage_separated(self):
        got = []

        async def on(ev):
            got.append(ev)

        asyncio.run(stream_openai_compatible(
            base_url=f"http://127.0.0.1:{self.port}/v1/chat/completions",
            api_key="x", model="m",
            messages=[{"role": "user", "content": "hi"}],
            on_event=on))
        deltas = [e for e in got if e["kind"] == "delta"]
        reasoning = "".join(e["delta"] for e in deltas if e["stage"] == "reasoning")
        content = "".join(e["delta"] for e in deltas if e["stage"] == "content")
        done = [e for e in got if e["kind"] == "done"][0]
        self.assertEqual(reasoning, "让我想想步骤一")
        self.assertEqual(content, "你好，我是元亨")
        self.assertEqual(done["text"], "你好，我是元亨")
        self.assertEqual(done["reasoning"], "让我想想步骤一")
        self.assertEqual(done["usage"], {"prompt": 10, "completion": 5})
        self.assertEqual(done["finish"], "stop")


if __name__ == "__main__":
    unittest.main()
