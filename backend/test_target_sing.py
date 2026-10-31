"""Workbench singing module tests (Phase B, ledger 0457)."""
import json
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

    def _fake_ok(self, calls):
        """Fake subprocess.run for the 3-stem job: creates stage outputs."""

        def fake_run(cmd, **kw):
            calls.append(cmd)
            joined = " ".join(map(str, cmd))
            if "cover_seedvc.py" in joined:
                outdir = cs.SING_DIR / "seedvc_job" / "run"
                outdir.mkdir(parents=True, exist_ok=True)
                final = outdir / "成品_test_seedvc_e.wav"
                final.write_bytes(b"RIFFseedvc")
                for n in ("干声", "和声", "伴奏"):
                    (outdir / f"{n}.wav").write_bytes(b"RIFF" + n.encode())
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"ok": True, "out_dir": str(outdir),
                                       "outputs": [str(final)]},
                                      ensure_ascii=False),
                    stderr="")
            stem_dir = cs.SING_DIR / "stem3"
            stem_dir.mkdir(parents=True, exist_ok=True)
            if "wsl_stem3_split.sh" in joined:
                for n in ("lead", "backing", "bgm"):
                    (stem_dir / f"{n}.wav").write_bytes(b"RIFF" + n.encode())
            out = cs.SING_DIR / "out"
            out.mkdir(parents=True, exist_ok=True)
            if "wsl_dereverb.sh" in joined:
                (stem_dir / "lead_dry.wav").write_bytes(b"RIFFdry")
            if "wsl_soulx_svc.sh" in joined:
                (out / "generated.wav").write_bytes(b"RIFFxxxx")
            if "wsl_clarity_enhance.sh" in joined:
                (out / "enhanced.wav").write_bytes(b"RIFFenh")
            if "cover_v3_dsp.py" in joined:
                (out / "dsp_soft.wav").write_bytes(b"RIFFdsp")
            if "wsl_mix3.sh" in joined:
                (out / "mixed.wav").write_bytes(b"RIFFmix")
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        return fake_run

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

    def test_job_success_seedvc(self):
        """2026-10-21 (台账 0935): 生产链路 = 三轨分离 + Seed-VC 44k + 柔化 e。"""
        calls = []
        cs.subprocess.run = self._fake_ok(calls)
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "done")
        self.assertTrue(pathlib.Path(cs.SING_STATE["result"]).exists())
        self.assertTrue(self.closed)  # window always closed
        joined = [" ".join(map(str, c)) for c in calls]
        self.assertEqual(len(joined), 1)
        self.assertIn("cover_seedvc.py", joined[0])
        self.assertIn("--presets e", joined[0])
        self.assertIn("--voice bright", joined[0])
        import backend.song_library as sl

        self.assertTrue(cs.SING_STATE["song_id"])
        outs = list(cs.SING_OUT_DIR.glob("**/成品_*.wav"))
        self.assertEqual(len(outs), 1)
        self.assertIn("清亮嗓", outs[0].name)
        run_dir = outs[0].parent
        # 2026-10-21 老爹定：产出只要成品，不再保留分层/说明。
        self.assertFalse((run_dir / "说明.txt").exists())
        self.assertEqual(
            sorted(p.name for p in run_dir.iterdir()), [outs[0].name])
        it = sl.resolve("清亮嗓")
        self.assertIsNotNone(it)
        self.assertEqual(sl.song_path(it["id"]), outs[0])

    def test_voice_bright_uses_bright_prompt(self):
        calls = []
        cs.subprocess.run = self._fake_ok(calls)
        res = cs.sing_start(str(self.target), voice="bright")
        self.assertTrue(res["ok"])
        self.assertIn("bright", " ".join(" ".join(map(str, c))
                                         for c in calls))
        outs = list(cs.SING_OUT_DIR.glob("**/成品_*.wav"))
        self.assertTrue(any("清亮嗓" in p.name for p in outs), outs)

    def test_job_failure_restores_and_reports(self):
        calls = []
        ok = self._fake_ok(calls)

        def fake_run(cmd, **kw):
            if "cover_seedvc.py" in " ".join(map(str, cmd)):
                calls.append(cmd)
                return types.SimpleNamespace(returncode=1, stdout="",
                                             stderr="boom")
            return ok(cmd, **kw)

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "error")
        self.assertIn("新链路失败", cs.SING_STATE["error"])
        self.assertTrue(self.closed)

    @unittest.skip("旧 SoulX 分轨失败路径已退出生产（台账 0935）")
    def test_stage_errors_reports_split_failure(self):
        """Rule 2026-10-09: split failure is reported (no SVC attempted)."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "wsl_stem3_split.sh" in " ".join(map(str, cmd)):
                return types.SimpleNamespace(returncode=2, stdout="",
                                             stderr="demucs failed")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        cs.subprocess.run = fake_run
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "error")
        self.assertIn("分轨失败", cs.SING_STATE["error"])
        self.assertEqual(len(calls), 1)  # split failed → nothing downstream
        self.assertTrue(self.closed)  # window closed even on failure

    @unittest.skip("旧 SoulX 三轨规则测试已退出生产（台账 0935）")
    def test_cover_rule_only_lead_uses_ai(self):
        """老爹 2026-10-09: 干声换 AI，和声/背景沿用原声（三轨混回）。"""
        calls = []
        cs.subprocess.run = self._fake_ok(calls)
        cs.sing_start(str(self.target))
        joined = [" ".join(map(str, c)) for c in calls]
        # F0/SVC target the dereverbed dry lead; clarity enhance uses the
        # dereverbed lead's high band; the mixdown consumes softened AI lead +
        # untouched backing(和声)/bgm(伴奏).
        self.assertIn("lead_dry.wav", joined[2])
        self.assertIn("wsl_clarity_enhance.sh", joined[4])
        self.assertIn("generated.wav", joined[4])
        self.assertIn("dsp_soft.wav", joined[6])
        self.assertIn("backing.wav", joined[6])
        self.assertIn("bgm.wav", joined[6])

    def test_sing_status_shape(self):
        st = cs.sing_status()
        self.assertTrue(st["ok"])
        for k in ("status", "step", "error", "result"):
            self.assertIn(k, st)

    def test_interlock_blocks_second_job_and_releases(self):
        """ledger 0459: one singing job owns the GPU; released on finish."""
        import backend.gpu_lock as gl

        calls = []
        cs.subprocess.run = self._fake_ok(calls)
        self.assertTrue(gl.acquire_sing())  # simulate a running job
        try:
            res = cs.sing_start(str(self.target))
            self.assertFalse(res["ok"])
            self.assertIn("互锁", res["error"])
        finally:
            gl.release_sing()
        res = cs.sing_start(str(self.target))
        self.assertTrue(res["ok"])
        self.assertEqual(cs.SING_STATE["status"], "done")
        self.assertEqual(gl.owner(), "")  # released after the sync job


if __name__ == "__main__":
    unittest.main()
