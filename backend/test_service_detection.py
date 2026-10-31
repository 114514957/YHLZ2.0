"""Service-detection hardening tests (2026-10-12).

Regression: cmdline-substring scans for "llama-server" were fooled by a
PowerShell whose *command text* contained `Get-Process llama-server` — so
`gpu_window.close_window` skipped the llama respawn (llama stayed down after
an official-UI session) and the watchdog gate `_proc_alive("llama-server")`
reported the service alive. Detection is now image-name / python-argv based.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import backend.gpu_window as gw  # noqa: E402
from tools import yhlz_launcher as L  # noqa: E402


def _p(pid, name, cmdline):
    return mock.Mock(info={"pid": pid, "name": name, "cmdline": cmdline})


def _patch_iter(procs):
    return mock.patch("psutil.process_iter",
                      lambda attrs=None: iter(procs))


class GpuWindowFindPidsTest(unittest.TestCase):
    def test_shell_mentioning_llama_is_not_llama(self):
        procs = [
            _p(101, "powershell.exe",
               ["powershell.exe", "-Command", "Get-Process llama-server"]),
            _p(102, "python.exe",
               ["python.exe", "-c", "print('llama-server log tail')"]),
        ]
        with _patch_iter(procs):
            self.assertEqual(gw._find_pids(exe="llama-server.exe"), [])

    def test_real_llama_found_by_exact_image_name(self):
        procs = [_p(7, "llama-server.exe",
                    ["C:\\x\\llama-server.exe", "-m", "y.gguf"])]
        with _patch_iter(procs):
            self.assertEqual(gw._find_pids(exe="llama-server.exe"), [7])

    def test_watchdog_needs_python_script_argument(self):
        procs = [
            _p(11, "powershell.exe",
               ["powershell.exe", "-Command", "type yhlz_watchdog.py"]),
            _p(12, "python.exe",
               ["python.exe", "-c", "x='yhlz_watchdog'; print(x)"]),
            _p(13, "pythonw.exe",
               ["pythonw.exe", "-B", "C:\\YHLZ\\tools\\yhlz_watchdog.py"]),
        ]
        with _patch_iter(procs):
            self.assertEqual(gw._find_pids(script="yhlz_watchdog"), [13])

    def test_state_and_kill_pids_best_effort(self):
        procs = [_p(9, "llama-server.exe", ["llama-server.exe"])]
        with _patch_iter(procs), \
                mock.patch.object(gw, "_free_mb", lambda: 1234):
            st = gw.state()
        self.assertTrue(st["llama"])
        self.assertFalse(st["watchdog"])
        with mock.patch("psutil.Process") as mp:
            mp.side_effect = [mock.Mock(), RuntimeError("gone")]
            self.assertEqual(gw._kill_pids([1, 2]), 1)


class LauncherProcAliveTest(unittest.TestCase):
    def _alive(self, procs, marker):
        with _patch_iter(procs):
            return L._proc_alive(marker)

    def test_llama_marker_ignores_shells(self):
        procs = [
            _p(101, "powershell.exe",
               ["powershell.exe", "-Command", "Get-Process llama-server"]),
            _p(102, "cmd.exe", ["cmd.exe", "/c", "dir llama-server"]),
        ]
        self.assertFalse(self._alive(procs, "llama-server"))

    def test_llama_marker_matches_image_name(self):
        procs = [_p(7, "llama-server.exe", ["llama-server.exe", "-m", "x"])]
        self.assertTrue(self._alive(procs, "llama-server"))

    def test_script_marker_requires_python_argv(self):
        procs = [
            _p(11, "powershell.exe",
               ["powershell.exe", "-Command", "watch target_daemon"]),
            _p(12, "python.exe",
               ["python.exe", "-c", "print('target_daemon')"]),
            _p(13, "python.exe",
               ["python.exe", "-B", "-m", "backend.target_daemon",
                "--port", "8321"]),
        ]
        self.assertTrue(self._alive(procs, "target_daemon"))

    def test_script_marker_ignores_mention_only(self):
        procs = [_p(12, "python.exe",
                    ["python.exe", "-c", "print('target_daemon')"])]
        self.assertFalse(self._alive(procs, "target_daemon"))


if __name__ == "__main__":
    unittest.main()
