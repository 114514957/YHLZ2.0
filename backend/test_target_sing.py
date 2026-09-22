"""Workbench singing module tests (Phase B, ledger 0457)."""
import pathlib
import tempfile
import types
import unittest

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
                     "Thread": cs.threading.Thread, "run": cs.subprocess.run,
                     "SING_OUT_DIR": cs.SING_OUT_DIR}
        cs.SING_DIR = self.tmp
        cs.SING_OUT_DIR = self.tmp / "out_dir"
        prompt = self.tmp / "ref01.wav"
        prompt.write_bytes(b"x")
        cs.SING_PROMPT = prompt
        cs.threading.Thread = _SyncThread
        cs.SING_STATE.update(status="idle", step="", error="", result="",
                             log="", started=0.0, finished=0.0, song_id="")
        import backend.song_library as sl

        self._sl_dir, self._sl_idx = sl.SONGS_DIR, sl.INDEX
        sl.SONGS_DIR = self.tmp / "songs"
        sl.INDEX = sl.SONGS_DIR / "songs.json"
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
        cs.SING_OUT_DIR = self._old["SING_OUT_DIR"]
        cs.threading.Thread = self._old["Thread"]
        cs.subprocess.run = self._old["run"]
        gw.open_window = self._gw_open
        gw.close_window = self._gw_close
        import backend.song_library as sl

        sl.SONGS_DIR, sl.INDEX = getattr(self, "_sl_dir", sl.SONGS_DIR), \
            getattr(self, "_sl_idx", sl.INDEX)

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

    def test_job_success_two_stage(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:  # prep stage (no window)
                return types.SimpleNamespace(returncode=0, stdout="prep ok",
                                             stderr="")
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "generated.wav").write_bytes(b"RIFFxxxx")
            return types.SimpleNamespace(returncode=0, stdout="svc ok",
                                         stderr="")

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "done")
        self.assertTrue(pathlib.Path(cs.SING_STATE["result"]).exists())
        self.assertTrue(self.closed)  # window always closed
        self.assertEqual(len(calls), 2)
        self.assertIn("wsl_soulx_prep.sh", " ".join(map(str, calls[0])))
        self.assertIn("wsl_soulx_svc.sh", " ".join(map(str, calls[1])))
        # finished song auto-saved to the local library (ledger 0460/0464:
        # library REFERENCES the 音频素材/翻唱产出/ file, no second copy)
        import backend.song_library as sl

        self.assertTrue(cs.SING_STATE["song_id"])
        outs = list(cs.SING_OUT_DIR.glob("*.wav"))
        self.assertEqual(len(outs), 1)
        self.assertIn("Xiaoyi嗓", outs[0].name)
        it = sl.resolve("Xiaoyi嗓")
        self.assertIsNotNone(it)
        self.assertEqual(sl.song_path(it["id"]), outs[0])

    def test_voice_bright_uses_bright_prompt(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                return types.SimpleNamespace(returncode=0, stdout="",
                                             stderr="")
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "generated.wav").write_bytes(b"RIFF")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target), voice="bright")
        self.assertTrue(res["ok"])
        self.assertIn("bright", " ".join(map(str, calls[0])))
        outs = list(cs.SING_OUT_DIR.glob("*.wav"))
        self.assertTrue(any("清亮嗓" in p.name for p in outs), outs)

    def test_job_failure_restores_and_reports(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if len(calls) == 1:
                return types.SimpleNamespace(returncode=0, stdout="",
                                             stderr="")
            return types.SimpleNamespace(returncode=1, stdout="",
                                         stderr="boom")

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "error")
        self.assertIn("SVC 失败", cs.SING_STATE["error"])
        self.assertTrue(self.closed)

    def test_vocal_sep_flag_propagates(self):
        def fake_run(cmd, **kw):
            fake_run.n = getattr(fake_run, "n", 0) + 1
            if fake_run.n == 1:
                return types.SimpleNamespace(returncode=0, stdout="",
                                             stderr="")
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "generated.wav").write_bytes(b"RIFF")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        cs.subprocess.run = fake_run
        cs.sing_start(str(self.target), vocal_sep=False)
        self.assertFalse(cs.SING_STATE["vocal_sep"])

    def test_sing_status_shape(self):
        st = cs.sing_status()
        self.assertTrue(st["ok"])
        for k in ("status", "step", "error", "result"):
            self.assertIn(k, st)

    def test_interlock_blocks_second_job_and_releases(self):
        """ledger 0459: one singing job owns the GPU; released on finish."""
        import backend.gpu_lock as gl

        def fake_run(cmd, **kw):
            fake_run.n = getattr(fake_run, "n", 0) + 1
            if fake_run.n == 1:
                return types.SimpleNamespace(returncode=0, stdout="",
                                             stderr="")
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            (out / "generated.wav").write_bytes(b"RIFF")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        cs.subprocess.run = fake_run
        self.assertTrue(gl.acquire_sing())  # simulate a running job
        try:
            res = cs.sing_start(str(self.target))
            self.assertFalse(res["ok"])
            self.assertIn("互锁", res["error"])
        finally:
            gl.release_sing()
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(gl.owner(), "")  # released after the sync job


if __name__ == "__main__":
    unittest.main()
