"""S5 对话层与 TTS 桥测试（假 LLM / 假 live 服务，stdlib unittest）。"""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.conversation import (  # noqa: E402
    LiveConversation, LiveConversationConfig, clean_reply, split_for_tts,
)
from backend.live.tts_bridge import LiveTTSBridge, LiveTTSBridgeConfig  # noqa: E402


class FakeLLMHandler(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeLLMHandler.requests.append(payload)
        body = json.dumps({
            "model": payload.get("model", "fake"),
            "choices": [{"message": {"role": "assistant",
                                     "content": "好的，我在。刚才有人问模型的事，这里先不多说。"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeLiveHandler(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeLiveHandler.requests.append(payload)
        if payload.get("action") == "say":
            text = str(payload.get("text") or "")
            duration = 25.0 if "CAP" in text else 1.5
            result = {"ok": True, "result": {"segment_id": "seg-test",
                                             "synth_ms": 123, "duration_s": duration}}
        else:
            result = {"ok": True, "result": {"generation": 9}}
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ServerMixin(unittest.TestCase):
    handler_cls = None

    @classmethod
    def setUpClass(cls):
        cls.handler_cls.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.handler_cls)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()


class TestSplitForTts(unittest.TestCase):
    def test_split_sentences(self):
        parts = split_for_tts("你好。今天天气不错，适合出门散步！")
        self.assertEqual(parts, ["你好。", "今天天气不错，适合出门散步！"])

    def test_split_long(self):
        text = "这是一句特别长的话" * 8
        parts = split_for_tts(text, max_chars=20)
        self.assertTrue(all(len(p) <= 20 for p in parts))
        self.assertEqual("".join(parts), text)

    def test_empty(self):
        self.assertEqual(split_for_tts(""), [])


class TestCleanReply(unittest.TestCase):
    def test_stage_direction_removed(self):
        cleaned = clean_reply("能。\n\n（补充）正在看呢，别急。")
        self.assertEqual(cleaned, "能。 正在看呢，别急。")

    def test_leading_parenthetical(self):
        self.assertEqual(clean_reply("（旁白）你好。"), "你好。")

    def test_plain_text_untouched(self):
        self.assertEqual(clean_reply("我是元亨，正在直播。"), "我是元亨，正在直播。")


class TestBuildMessages(_ServerMixin):
    handler_cls = FakeLLMHandler

    def test_reply_turn_prompt(self):
        conversation = LiveConversation(LiveConversationConfig(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            context_raw=2))
        turn = {"turn_id": "t1", "kind": "reply", "topic_text": "你是真人吗",
                "sources": [{"display_name": "A", "text": "你是真人吗"},
                            {"display_name": "B", "text": "你是真人吗？"}]}
        recent = [{"display_name": f"u{i}", "text": f"话{i}"} for i in range(5)]
        messages = conversation.build_messages(turn, recent)
        self.assertEqual(messages[0]["role"], "system")
        content = messages[1]["content"]
        self.assertIn("需要回应的主题：你是真人吗", content)
        self.assertIn("同一主题共有 2 条", content)
        self.assertIn("话3", content)
        self.assertNotIn("话2", content)

    def test_cold_turn_prompt(self):
        conversation = LiveConversation(LiveConversationConfig())
        messages = conversation.build_messages({"turn_id": "c1", "kind": "cold",
                                                "sources": []}, [])
        self.assertIn("没有新弹幕", messages[1]["content"])


class TestRespond(_ServerMixin):
    handler_cls = FakeLLMHandler

    def test_respond_parses_content(self):
        conversation = LiveConversation(LiveConversationConfig(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            model="gemma-test", max_tokens=123))
        result = conversation.respond({"turn_id": "t1", "kind": "reply",
                                       "topic_text": "你好", "sources": []})
        self.assertIn("好的", result["text"])
        self.assertGreaterEqual(result["llm_ms"], 0)
        self.assertEqual(result["usage"]["total_tokens"], 70)
        sent = FakeLLMHandler.requests[-1]
        self.assertEqual(sent["model"], "gemma-test")
        self.assertEqual(sent["max_tokens"], 123)
        self.assertFalse(sent["stream"])


class TestTtsBridge(_ServerMixin):
    handler_cls = FakeLiveHandler

    def test_speak_splits_and_totals(self):
        bridge = LiveTTSBridge(LiveTTSBridgeConfig(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            token="tok", max_chars=20))
        result = bridge.speak("第一句。第二句也很长很长很长很长很长很长很长。")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], len(result["segments"]))
        self.assertEqual(result["total_synth_ms"], 123 * result["count"])
        self.assertTrue(all(seg["segment_id"] == "seg-test" for seg in result["segments"]))

    def test_clear_calls_stop(self):
        bridge = LiveTTSBridge(LiveTTSBridgeConfig(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}", token="tok"))
        result = bridge.clear()
        self.assertTrue(result.get("ok"))
        self.assertEqual(FakeLiveHandler.requests[-1]["action"], "stop")

    def test_duration_cap_trips_and_clears(self):
        bridge = LiveTTSBridge(LiveTTSBridgeConfig(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            token="tok", max_segment_duration_s=20.0))
        result = bridge.speak("CAP 测试。")
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("cap_cleared"))
        self.assertIn("duration-cap-exceeded", result["segments"][0]["error"])
        self.assertEqual(FakeLiveHandler.requests[-1]["action"], "stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
