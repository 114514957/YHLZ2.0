"""P0 regression tests (2026-10-21): optional Ollama + GPU window supervisor.

These tests never touch the live stack: they use a temporary flag file and
mock process/GPU probes.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import backend.gpu_window as gw  # noqa: E402
import yhlz_launcher as yl  # noqa: E402


class LauncherReadinessTest(unittest.TestCase):
    def test_ollama_is_not_critical(self):
        self.assertTrue(yl.ready({"ollama": False, "gemma": True, "daemon": True}))
        self.assertFalse(yl.ready({"ollama": True, "gemma": False, "daemon": True}))
        self.assertFalse(yl.ready({"ollama": True, "gemma": True, "daemon": False}))


class GpuWindowFlagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="p0-gpu-"))
        self.flag = self.tmp / "gpu_window.lock"

    def test_flag_is_active_and_expires(self):
        with mock.patch.object(yl, "GPU_WINDOW_FLAG", self.flag), \
                mock.patch.object(yl, "GPU_WINDOW_MAX_AGE", 60.0):
            self.flag.write_text(str(time.time()), encoding="utf-8")
            self.assertTrue(yl.gpu_window_active())
            old = time.time() - 120
            import os
            os.utime(self.flag, (old, old))
            self.assertFalse(yl.gpu_window_active())
            self.assertFalse(self.flag.exists())

    def test_open_window_keeps_watchdog(self):
        calls = []
        with mock.patch.object(gw, "_FLAG", self.flag), \
                mock.patch.object(gw, "_find_pids",
                                  side_effect=lambda **kw: [111] if "exe" in kw else [222]), \
                mock.patch.object(gw, "_kill_pids",
                                  side_effect=lambda pids: calls.append(pids) or len(pids)), \
                mock.patch.object(gw, "_free_mb", return_value=7000), \
                mock.patch.object(gw.subprocess, "run", return_value=None):
            out = gw.open_window(require_free_mb=6500, timeout=1)
        self.assertTrue(out["ok"])
        self.assertTrue(out["killed"]["watchdog_kept"])
        self.assertEqual(calls, [[111]])  # llama only, never watchdog
        self.assertTrue(self.flag.exists())
        gw._set_window(False)


if __name__ == "__main__":
    unittest.main()
