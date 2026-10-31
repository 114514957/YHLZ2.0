"""P1 offline tests: service check, fake-transport probe, inbox bounds.

No network, no real QQ, no Full launcher/watchdog import.
Run:
    .venv\\Scripts\\python.exe -m unittest backend.test_qq_bridge_p1
"""
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

from tools import qq_bot as qq

_ROOT = pathlib.Path(__file__).resolve().parent.parent


class ServiceCheckTests(unittest.TestCase):
    def _run_check(self, *extra: str):
        return subprocess.run(
            [sys.executable, str(_ROOT / "tools" / "qq_bridge_service.py"),
             "--config", str(_ROOT / "config" / "qq_bridge_lite.json"),
             "--check", *extra],
            cwd=_ROOT, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")

    def test_check_profile_ok(self):
        out = self._run_check()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        data = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertTrue(data["ok"])
        self.assertEqual(data["masters"], ["2258374446"])
        self.assertEqual(data["profile"], "lite")
        self.assertIn(str(pathlib.Path("cache", "qq_bridge", "lite")),
                      data["state_dir"])

    def test_second_owner_fails_closed(self):
        out = self._run_check("--master", "10001")
        self.assertEqual(out.returncode, 2)
        data = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertFalse(data["ok"])
        self.assertIn("2258374446", data["error"])


class FakeEchoProbeTests(unittest.TestCase):
    def test_probe_passes_offline(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = pathlib.Path(td) / "p1"
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            for key in ("YHLZ_QQ_PROFILE", "YHLZ_QQ_STATE_DIR"):
                env.pop(key, None)
            run = subprocess.run(
                [sys.executable,
                 str(_ROOT / "tools" / "qq_bridge_p1_fake_echo.py"),
                 "--out", str(out_dir)],
                cwd=_ROOT, capture_output=True, text=True, timeout=240,
                env=env, encoding="utf-8", errors="replace")
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            data = json.loads(
                (out_dir / "fake_echo.json").read_text(encoding="utf-8"))
            self.assertTrue(data["pass"])
            self.assertTrue(data["echo"]["ok"])
            self.assertLess(data["echo"]["latency_ms"], 2000)
            self.assertTrue(data["devstatus"]["ok"])
            self.assertTrue(data["devstatus"]["slow_chat_still_blocked"])
            self.assertTrue(data["heartbeat"]["ok"])
            self.assertTrue(data["slow_reply"]["ok"])
            self.assertEqual(data["full_watchdog_modules"], [])
            self.assertFalse(data["daemon_started"])
            self.assertEqual(data["port_isolation"]["connect_attempts"], [])


class InboxBoundsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bridge = qq.QQBridge("unused", "900", pathlib.Path("unused"),
                                  masters={"2258374446"})

    def test_queue_full_records_busy_without_task_spawn(self):
        self.bridge.inbox = asyncio.Queue(maxsize=1)
        self.bridge.inbox.put_nowait({"post_type": "message"})
        self.bridge._enqueue({"post_type": "message"})
        self.assertEqual(self.bridge.inbox_busy, 1)
        self.assertEqual(self.bridge.inbox.qsize(), 1)
        self.assertEqual(self.bridge.inbox_processed, 0)

    def test_owner_command_detection_uses_outer_sender(self):
        ev = {"post_type": "message", "message_type": "private",
              "user_id": "2258374446",
              "message": [{"type": "text", "data": {"text": "#dev x"}}]}
        self.assertTrue(self.bridge._is_owner_command(ev))
        ev["user_id"] = "10086"
        self.assertFalse(self.bridge._is_owner_command(ev))

    async def test_dev_single_flight(self):
        self.bridge._say = AsyncMock()
        release = threading.Event()

        class Runner:
            @staticmethod
            def start(task):
                release.wait(5)
                return {"status": "done", "text": task}

        with patch.object(qq, "dev_runner", Runner()):
            await self.bridge._start_dev(None, {}, "t1")
            await self.bridge._start_dev(None, {}, "t2")
            release.set()
            texts = [str(c.args[2]) for c in self.bridge._say.await_args_list]
            self.assertTrue(any(t.startswith("[利贞] 已开工") for t in texts))
            self.assertTrue(any("已有开发任务在执行" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
