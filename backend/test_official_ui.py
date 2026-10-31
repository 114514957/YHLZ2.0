"""Workbench launch-entrance tests (ledger 0792): NapCat panel + official UI."""
import pathlib
import tempfile
import types
import unittest
from unittest import mock

import backend.console_server as cs
import backend.gpu_lock as gl
import backend.gpu_window as gw
import backend.official_ui as oui


class _SyncThread:
    """threading.Thread replacement that runs the target immediately."""

    def __init__(self, target=None, daemon=None, name=None, args=(),
                 kwargs=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


class _FakeProc:
    def __init__(self):
        self._alive = True
        self.terminated = 0

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated += 1
        self._alive = False


class OfficialUiTest(unittest.TestCase):
    def setUp(self):
        self._old = {
            "port_open": oui._port_open, "ui_alive": oui._ui_alive,
            "popen": oui.subprocess.Popen, "run": oui.subprocess.run,
            "thread": oui.threading.Thread,
            "wait": oui._PORT_WAIT_S, "poll": oui._PORT_POLL_S,
            "settle": oui._SETTLE_S,
            "open": gw.open_window, "close": gw.close_window,
            "unload": cs._unload_tts,
        }
        oui._PORT_WAIT_S, oui._PORT_POLL_S, oui._SETTLE_S = 0.05, 0.01, 0.0
        oui._ui_alive = lambda: False
        oui.threading.Thread = _SyncThread
        cs._unload_tts = lambda: None
        self.closed, self.procs, self.pkills = [], [], []
        gw.open_window = lambda **kw: {"ok": True, "free_mb": 7000}
        gw.close_window = lambda: self.closed.append(1) or {"llama": True}
        oui.subprocess.run = lambda *a, **k: (
            self.pkills.append(a[0]) or
            types.SimpleNamespace(returncode=0, stdout="", stderr=""))

        def fake_popen(cmd, **kw):
            p = _FakeProc()
            self.procs.append((cmd, p))
            return p

        oui.subprocess.Popen = fake_popen
        oui._STATE.update(status="idle", step="", error="",
                          port=oui.DEFAULT_PORT, started=0.0, finished=0.0,
                          attached=False)
        oui._proc, oui._owns_lock = None, False
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        oui._port_open = self._old["port_open"]
        oui._ui_alive = self._old["ui_alive"]
        oui.subprocess.Popen = self._old["popen"]
        oui.subprocess.run = self._old["run"]
        oui.threading.Thread = self._old["thread"]
        oui._PORT_WAIT_S = self._old["wait"]
        oui._PORT_POLL_S = self._old["poll"]
        oui._SETTLE_S = self._old["settle"]
        gw.open_window = self._old["open"]
        gw.close_window = self._old["close"]
        cs._unload_tts = self._old["unload"]
        oui._proc, oui._owns_lock = None, False
        oui._STATE.update(status="idle", step="", error="", attached=False)
        gl.release_sing()

    def test_start_runs_job_then_stop_restores(self):
        gate = {"n": 0}

        def port_open(port, timeout=0.5):
            gate["n"] += 1
            return gate["n"] >= 2          # 1st = attach probe, 2nd = job poll

        oui._port_open = port_open
        res = oui.start()
        self.assertTrue(res["ok"])
        self.assertEqual(oui.state()["status"], "running")
        self.assertEqual(gl.owner(), "sing-svc")   # chat blocked (唱窗)
        self.assertTrue(self.procs)
        cmd = " ".join(map(str, self.procs[0][0]))
        self.assertIn("wsl.exe", cmd)
        self.assertIn("webui_svc.py", cmd)
        self.assertIn("--port 7861", cmd)
        # 冷启动必须带 HF 镜像（WSL 直连 huggingface.co 不可达，见 0792）
        self.assertIn("HF_ENDPOINT", cmd)
        self.assertIn("hf-mirror.com", cmd)

        out = oui.stop()
        self.assertTrue(out["ok"])
        self.assertEqual(oui.state()["status"], "idle")
        self.assertEqual(gl.owner(), "")
        self.assertTrue(self.closed)
        self.assertTrue(self.pkills)
        self.assertEqual(self.procs[0][1].terminated, 1)

    def test_start_attaches_to_existing_instance(self):
        oui._port_open = lambda port, timeout=0.5: True
        res = oui.start()
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("attached"))
        self.assertEqual(oui.state()["status"], "running")
        self.assertEqual(oui.state()["attached"], True)
        self.assertFalse(self.procs)              # no second window/process
        self.assertEqual(gl.owner(), "sing-svc")
        oui.stop()
        self.assertEqual(gl.owner(), "")

    def test_start_refused_when_gpu_busy(self):
        self.assertTrue(gl.acquire_sing())        # a cover job owns the GPU
        oui._port_open = lambda port, timeout=0.5: False
        res = oui.start()
        self.assertFalse(res["ok"])
        self.assertIn("互锁", res["error"])
        self.assertEqual(oui.state()["status"], "idle")

    def test_window_failure_restores_and_reports(self):
        gw.open_window = lambda **kw: {"ok": False, "free_mb": 100}
        oui._port_open = lambda port, timeout=0.5: False
        res = oui.start()
        self.assertTrue(res["ok"])
        self.assertEqual(oui.state()["status"], "error")
        self.assertIn("显存不足", oui.state()["error"])
        self.assertTrue(self.closed)
        self.assertEqual(gl.owner(), "")

    def test_port_timeout_reports_error(self):
        oui._PORT_WAIT_S = 0.03
        oui._port_open = lambda port, timeout=0.5: False
        res = oui.start()
        self.assertTrue(res["ok"])
        self.assertEqual(oui.state()["status"], "error")
        self.assertIn("超时", oui.state()["error"])
        self.assertEqual(gl.owner(), "")

    def test_stop_during_starting_is_refused(self):
        oui._STATE.update(status="starting")
        out = oui.stop()
        self.assertFalse(out["ok"])
        self.assertIn("启动中", out["error"])

    def test_reap_keeps_slow_attached_instance(self):
        # Attached while the external UI is still loading (port closed, but
        # the process is alive) → status must stay running, no reap/stop.
        oui._port_open = lambda port, timeout=0.5: False
        oui._ui_alive = lambda: True
        res = oui.start()
        self.assertTrue(res.get("attached"))
        st = oui.status()
        self.assertEqual(st["status"], "running")
        self.assertFalse(self.closed)
        self.assertEqual(gl.owner(), "sing-svc")
        oui.stop()

    def test_reap_restores_when_ui_gone_externally(self):
        gate = {"n": 0}

        def port_open(port, timeout=0.5):
            gate["n"] += 1
            return gate["n"] == 1              # attach probe only

        oui._port_open = port_open
        oui.start()
        self.assertEqual(oui.state()["status"], "running")
        oui._port_open = lambda port, timeout=0.5: False
        st = oui.status()
        self.assertEqual(st["status"], "idle")
        self.assertEqual(gl.owner(), "")
        self.assertTrue(self.closed)

    def test_status_shape(self):
        st = oui.status()
        self.assertTrue(st["ok"])
        for k in ("status", "step", "error", "url", "attached"):
            self.assertIn(k, st)


class LaunchEntranceControlTest(unittest.TestCase):
    def _handler(self):
        return object.__new__(cs.ConsoleHandler)

    def _webui_file(self, port: int) -> pathlib.Path:
        tmp = pathlib.Path(tempfile.mkdtemp())
        f = tmp / "webui.json"
        f.write_text('{"port": %d}' % port, encoding="utf-8")
        return f

    def test_control_official_ui_start_stop_delegate(self):
        calls = []
        start = lambda port=7861: calls.append(("start", port)) or \
            {"ok": True, "status": "starting"}
        stop = lambda reason="": calls.append(("stop", reason)) or \
            {"ok": True, "status": "idle"}
        with mock.patch.object(oui, "start", start), \
                mock.patch.object(oui, "stop", stop):
            h = self._handler()
            r1 = h._control({"action": "official_ui_start"})
            r2 = h._control({"action": "official_ui_stop"})
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        self.assertEqual(calls[0], ("start", oui.DEFAULT_PORT))
        self.assertEqual(calls[1][0], "stop")

    def test_control_official_ui_start_custom_port(self):
        with mock.patch.object(oui, "start",
                               lambda port=7861: {"ok": True, "port": port}):
            r = self._handler()._control(
                {"action": "official_ui_start", "port": 9000})
        self.assertEqual(r["port"], 9000)

    def test_control_napcat_ui_online(self):
        wf = self._webui_file(6199)
        with mock.patch.object(cs, "NAPCAT_WEBUI", wf), \
                mock.patch.object(cs, "_tcp_open",
                                  lambda host, port, timeout=0.8:
                                  int(port) == 6199):
            r = self._handler()._control({"action": "napcat_ui"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["up"])
        self.assertEqual(r["url"], "http://127.0.0.1:6199/webui")

    def test_control_napcat_ui_launches_when_down(self):
        wf = self._webui_file(6099)
        tmp = wf.parent
        (tmp / "launcher-user.bat").write_text("x", encoding="utf-8")
        with mock.patch.object(cs, "NAPCAT_WEBUI", wf), \
                mock.patch.object(cs, "QQWATCH_SHELL", tmp), \
                mock.patch.object(cs, "_tcp_open", lambda *a, **k: False), \
                mock.patch.object(cs, "_napcat_procs_alive", lambda: False), \
                mock.patch("backend.napcat_launcher.launch_napcat") as launch:
            r = self._handler()._control({"action": "napcat_ui"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["up"])
        self.assertIn("拉起", r["note"])
        launch.assert_called_once_with(cs.BOT_UIN)

    def test_control_napcat_ui_alive_but_panel_down(self):
        wf = self._webui_file(6099)
        with mock.patch.object(cs, "NAPCAT_WEBUI", wf), \
                mock.patch.object(cs, "_tcp_open", lambda *a, **k: False), \
                mock.patch.object(cs, "_napcat_procs_alive", lambda: True):
            r = self._handler()._control({"action": "napcat_ui"})
        self.assertTrue(r["ok"])
        self.assertFalse(r["up"])
        self.assertIn("稍候", r["note"])


if __name__ == "__main__":
    unittest.main()
