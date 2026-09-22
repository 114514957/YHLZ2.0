"""Workbench singing module tests (Phase B, ledger 0457)."""
import pathlib
import tempfile
import types
import unittest
from unittest.mock import MagicMock

import backend.console_server as cs
import backend.gpu_window as gw


class _SyncThread:
    """threading.Thread replacement that runs the target immediately."""

    def __init__(self, target=None, daemon=None, name=None, args=(),
                 kwargs=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


class SingModuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._old = {"SING_DIR": cs.SING_DIR, "SING_PROMPT": cs.SING_PROMPT,
                     "Thread": cs.threading.Thread, "run": cs.subprocess.run}
        cs.SING_DIR = self.tmp
        prompt = self.tmp / "ref01.wav"
        prompt.write_bytes(b"x")
        cs.SING_PROMPT = prompt
        cs.threading.Thread = _SyncThread
        cs.SING_STATE.update(status="idle", step="", error="", result="",
                             log="", started=0.0, finished=0.0)
        self._gw_open = gw.open_window
        self._gw_close = gw.close_window
        self.closed = []
        gw.open_window = lambda **kw: {"ok": True, "free_mb": 7000}
        gw.close_window = lambda: self.closed.append(1) or {"llama": True}
        self.target = self.tmp / "song.mp3"
        self.target.write_bytes(b"y" * 200)

    def tearDown(self):
        cs.SING_DIR = self._old["SING_DIR"]
        cs.SING_PROMPT = self._old["SING_PROMPT"]
        cs.threading.Thread = self._old["Thread"]
        cs.subprocess.run = self._old["run"]
        gw.open_window = self._gw_open
        gw.close_window = self._gw_close

    def test_wsl_path_conversion(self):
        p = pathlib.Path(r"C:\Users\ACE\song.mp3")
        self.assertEqual(cs._wsl_path(p), "/mnt/c/Users/ACE/song.mp3")

    def test_start_rejects_missing_target(self):
        res = cs.sing_start(str(self.tmp / "nope.wav"))
        self.assertFalse(res["ok"])
        self.assertIn("不存在", res["error"])

    def test_start_rejects_when_busy(self):
        got = cs._sing_lock.acquire(blocking=False)
        self.assertTrue(got)
        try:
            res = cs.sing_start(str(self.target))
            self.assertFalse(res["ok"])
            self.assertIn("已有", res["error"])
        finally:
            cs._sing_lock.release()

    def test_job_success(self):
        def fake_run(cmd, **kw):
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "generated.wav").write_bytes(b"RIFFxxxx")
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "done")
        self.assertTrue(pathlib.Path(cs.SING_STATE["result"]).exists())
        self.assertTrue(self.closed)  # window always closed

    def test_job_failure_restores_and_reports(self):
        cs.subprocess.run = MagicMock(
            return_value=types.SimpleNamespace(returncode=1, stdout="",
                                               stderr="boom"))
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "error")
        self.assertIn("SVC 失败", cs.SING_STATE["error"])
        self.assertTrue(self.closed)

    def test_sing_status_shape(self):
        st = cs.sing_status()
        self.assertTrue(st["ok"])
        for k in ("status", "step", "error", "result"):
            self.assertIn(k, st)


if __name__ == "__main__":
    unittest.main()
