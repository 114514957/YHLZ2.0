"""L1 本机音频服务测试（真实 HTTP 回环 + 假 TTS 服务，stdlib unittest）。

覆盖：token 鉴权、武装门控、租约单消费者、ack 状态机、stop/代际、
TTL 过期、队列上限、租约超时接管、TTS 失败、页面静态服务。
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.audio_sink import (  # noqa: E402
    LiveConfig, make_server, wav_info,
)

TOKEN = "test-token-0123456789"


def make_wav(duration_s: float = 0.2, sr: int = 24000) -> bytes:
    frames = int(duration_s * sr)
    data = b"\x00\x00" * frames
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
              + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
              + b"data" + struct.pack("<I", len(data)))
    return header + data


class FakeTtsHandler(BaseHTTPRequestHandler):
    requests: list = []
    fail_marker = "FAIL"
    delay_marker = "SLOW"
    delay_s = 0.4

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        text = str(payload.get("text") or "")
        FakeTtsHandler.requests.append(payload)
        if FakeTtsHandler.delay_marker in text:
            time.sleep(FakeTtsHandler.delay_s)
        if self.fail_marker in text:
            self.send_response(500)
            body = b'{"error":"fake-tts-failure"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = make_wav(0.2)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def http(method: str, url: str, payload=None, raw: bool = False):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return resp.status, body if raw else json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {"raw": body}
        return exc.code, parsed


class SinkTestBase(unittest.TestCase):
    config_overrides: dict = {}

    @classmethod
    def setUpClass(cls):
        FakeTtsHandler.requests = []
        cls.tts = ThreadingHTTPServer(("127.0.0.1", 0), FakeTtsHandler)
        cls.tts.daemon_threads = True
        threading.Thread(target=cls.tts.serve_forever, daemon=True).start()
        cls.tts_port = cls.tts.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.tts.shutdown()
        cls.tts.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        kwargs = dict(
            host="127.0.0.1", port=0,
            tts_url=f"http://127.0.0.1:{self.tts_port}/tts",
            audio_dir=str(Path(self.tmp.name) / "audio"),
            lease_token=TOKEN,
            segment_ttl_s=30.0, lease_ttl_s=30.0, poll_timeout_s=0.2)
        kwargs.update(self.config_overrides)
        config = LiveConfig(**kwargs)
        self.server = make_server(config)
        self.service = self.server.RequestHandlerClass.service
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def say(self, text: str):
        return http("POST", f"{self.base}/control",
                    {"token": TOKEN, "action": "say", "text": text})

    def arm(self):
        return http("POST", f"{self.base}/control",
                    {"token": TOKEN, "action": "arm", "route": "obs_browser",
                     "monitor": "off"})

    def channel(self, client_id: str, since: int = 0, token: str = TOKEN):
        return http("GET", f"{self.base}/channel?token={token}"
                           f"&client_id={client_id}&since={since}")

    def ack(self, client_id: str, segment_id: str, kind: str, generation: int):
        return http("POST", f"{self.base}/ack",
                    {"token": TOKEN, "client_id": client_id,
                     "segment_id": segment_id, "kind": kind,
                     "generation": generation})

    def status(self):
        return http("GET", f"{self.base}/status")


class TestBasicFlow(SinkTestBase):
    def test_status_initial(self):
        code, body = self.status()
        self.assertEqual(code, 200)
        self.assertFalse(body["armed"])
        self.assertEqual(body["generation"], 1)
        self.assertEqual(body["queue"], [])

    def test_auth_required(self):
        code, _ = http("GET", f"{self.base}/channel?token=bad&client_id=x")
        self.assertEqual(code, 401)
        code, _ = http("POST", f"{self.base}/control",
                       {"token": "bad", "action": "arm"})
        self.assertEqual(code, 401)

    def test_say_enqueue_and_wav(self):
        code, body = self.say("你好，元亨。")
        self.assertEqual(code, 200)
        segment = body["result"]
        self.assertTrue(segment["segment_id"])
        self.assertEqual(segment["sample_rate"], 24000)
        self.assertGreater(segment["duration_s"], 0.1)
        self.assertIn("audio_path", segment)
        code, status = self.status()
        self.assertEqual(len(status["queue"]), 1)
        self.assertEqual(status["queue"][0]["state"], "queued")
        wav_path = Path(self.tmp.name) / "audio" / f"{segment['segment_id']}.wav"
        self.assertTrue(wav_path.exists())
        sr, ch, bits, size = wav_info(wav_path.read_bytes())
        self.assertEqual((sr, ch, bits), (24000, 1, 16))
        self.assertEqual(FakeTtsHandler.requests[-1]["text"], "你好，元亨。")

    def test_tts_failure_returns_502(self):
        code, body = self.say("这张会 FAIL")
        self.assertEqual(code, 502)
        _, status = self.status()
        self.assertEqual(status["queue"], [])
        self.assertGreaterEqual(status["counters"].get("tts_fail", 0), 1)


class TestDispatchGating(SinkTestBase):
    def test_unarmed_blocks_audio_and_arm_unlocks(self):
        _, say = self.say("第一句")
        segment = say["result"]
        code, chan = self.channel("obs-A")
        self.assertEqual(code, 200)
        self.assertFalse(chan["armed"])
        self.assertEqual(len(chan["queue"]), 1)
        code, _ = http("GET", f"{self.base}{segment['audio_path']}?token={TOKEN}")
        self.assertEqual(code, 409)
        code, _ = self.arm()
        self.assertEqual(code, 200)
        code, wav = http("GET", f"{self.base}{segment['audio_path']}?token={TOKEN}",
                         raw=True)
        self.assertEqual(code, 200)
        self.assertEqual(wav[:4], b"RIFF")
        code, _ = http("GET", f"{self.base}{segment['audio_path']}")
        self.assertEqual(code, 401)


class TestLeaseAndAck(SinkTestBase):
    def test_ack_state_machine_and_lease_conflict(self):
        _, say = self.say("回执测试")
        segment = say["result"]["segment_id"]
        self.arm()
        code, chan = self.channel("obs-A")
        self.assertEqual(code, 200)
        self.assertEqual(chan["lease"]["client_id"], "obs-A")
        code, chan_b = self.channel("obs-B")
        self.assertEqual(code, 409)
        self.assertEqual(chan_b["holder"], "obs-A")
        code, body = self.ack("obs-A", segment, "scheduled", 1)
        self.assertEqual((code, body["state"]), (200, "scheduled"))
        code, body = self.ack("obs-A", segment, "started", 1)
        self.assertEqual((code, body["state"]), (200, "started"))
        code, _ = self.ack("obs-B", segment, "ended", 1)
        self.assertEqual(code, 409)
        code, body = self.ack("obs-A", segment, "ended", 1)
        self.assertEqual((code, body["state"]), (200, "ended"))
        _, status = self.status()
        self.assertGreaterEqual(status["counters"].get("started", 0), 1)
        self.assertGreaterEqual(status["counters"].get("ended", 0), 1)
        self.assertEqual(status["queue"], [])

    def test_stop_cancels_and_bumps_generation(self):
        self.say("第一句")
        self.say("第二句")
        self.arm()
        self.channel("obs-A")
        code, body = http("POST", f"{self.base}/control",
                          {"token": TOKEN, "action": "stop", "reason": "test"})
        self.assertEqual(code, 200)
        status = body["result"]
        self.assertEqual(status["generation"], 2)
        self.assertFalse(status["armed"])
        self.assertEqual(status["queue"], [])
        self.assertIsNone(status["lease"]["holder"])
        code, _ = self.channel("obs-A")
        self.assertEqual(code, 200)

    def test_stale_generation_ack_rejected(self):
        _, say = self.say("旧代际")
        segment = say["result"]["segment_id"]
        self.arm()
        self.channel("obs-A")
        http("POST", f"{self.base}/control", {"token": TOKEN, "action": "stop"})
        code, body = self.ack("obs-A", segment, "started", 1)
        self.assertEqual(code, 409)
        self.assertEqual(body["error"], "stale-generation")


class TestExpiryAndLimits(SinkTestBase):
    config_overrides = {"segment_ttl_s": 0.15, "lease_ttl_s": 0.2}

    def test_ttl_expiry(self):
        self.say("会过期")
        time.sleep(0.3)
        _, status = self.status()
        self.assertEqual(status["queue"], [])
        self.assertGreaterEqual(status["counters"].get("expired", 0), 1)

    def test_lease_timeout_takeover(self):
        self.say("接管测试")
        self.arm()
        self.channel("obs-A")
        _, status = self.status()
        self.assertEqual(status["lease"]["holder"], "obs-A")
        time.sleep(0.3)
        code, chan = self.channel("obs-B")
        self.assertEqual(code, 200)
        self.assertEqual(chan["lease"]["client_id"], "obs-B")
        self.assertFalse(chan["armed"])
        self.assertGreaterEqual(chan["generation"], 2)
        _, status = self.status()
        self.assertEqual(status["lease"]["holder"], "obs-B")
        self.assertGreaterEqual(status["counters"].get("lease_lost", 0), 1)


class TestQueueLimit(SinkTestBase):
    config_overrides = {"max_queue": 1}

    def test_queue_full_429(self):
        code, _ = self.say("第一句")
        self.assertEqual(code, 200)
        code, body = self.say("第二句")
        self.assertEqual(code, 429)
        self.assertEqual(body["error"], "queue-full")


class TestCachedReplay(SinkTestBase):
    def test_enqueue_cached_wav(self):
        cached = Path(self.tmp.name) / "audio" / "cached-test.wav"
        cached.write_bytes(make_wav(0.5))
        code, body = http("POST", f"{self.base}/control",
                          {"token": TOKEN, "action": "enqueue_audio",
                           "filename": "cached-test.wav"})
        self.assertEqual(code, 200)
        segment = body["result"]
        self.assertEqual(segment["source"], "cached")
        self.assertEqual(segment["audio_path"], "/audio/cached-test.wav")
        self.assertAlmostEqual(segment["duration_s"], 0.5, delta=0.06)
        code, _ = http("POST", f"{self.base}/control",
                       {"token": TOKEN, "action": "enqueue_audio",
                        "filename": "../secret.wav"})
        self.assertEqual(code, 400)
        code, _ = http("POST", f"{self.base}/control",
                       {"token": TOKEN, "action": "enqueue_audio",
                        "filename": "missing.wav"})
        self.assertEqual(code, 404)


class TestGenerationRace(SinkTestBase):
    def test_stop_during_synth_drops_result(self):
        result = {}

        def worker():
            result["resp"] = self.say("SLOW 这句话合成很慢")

        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(0.1)
        http("POST", f"{self.base}/control", {"token": TOKEN, "action": "stop"})
        thread.join(timeout=10)
        code, body = result.get("resp", (0, {}))
        self.assertEqual(code, 409)
        self.assertEqual(body.get("error"), "generation-changed")
        _, status = self.status()
        self.assertEqual(status["queue"], [])
        self.assertGreaterEqual(status["counters"].get("dropped_stale", 0), 1)


class TestPage(SinkTestBase):
    def test_player_page_served(self):
        code, body = http("GET", f"{self.base}/player", raw=True)
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        self.assertIn("obsstudio", text)
        self.assertIn("AudioContext", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
