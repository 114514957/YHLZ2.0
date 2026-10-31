"""Workbench QQ panel status priority tests (2026-10-09).

Lite chain (cache/qq_bridge/lite) is authoritative when present; the legacy
napcat_status.json is only a fallback. No sockets, no daemon.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import console_server as cs


class QqStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = patch.object(cs, "_PROJECT_ROOT", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def _lite(self, *, pid_info=None, status=None):
        d = self.tmp / "cache" / "qq_bridge" / "lite"
        d.mkdir(parents=True, exist_ok=True)
        (d / "bridge_status.json").write_text(
            json.dumps(status or {}), encoding="utf-8")
        if pid_info is not None:
            (d / "bridge.pid").write_text(
                json.dumps(pid_info), encoding="utf-8")

    def _own_pid_info(self):
        try:
            import psutil

            ct = float(psutil.Process(os.getpid()).create_time())
        except Exception:  # noqa: BLE001
            ct = time.time()
        return {"pid": os.getpid(), "create_time": ct}

    def test_lite_authoritative_when_alive(self):
        self._lite(pid_info=self._own_pid_info(),
                   status={"state": "connected", "account_online": True,
                           "started_at": 123.0})
        st = cs._qq_status()
        self.assertEqual(st["source"], "lite")
        self.assertTrue(st["bridge"])
        self.assertTrue(st["ws"])
        self.assertTrue(st["online"])

    def test_lite_down_reports_offline_even_if_stale_connected(self):
        self._lite(status={"state": "connected", "account_online": True})
        st = cs._qq_status()
        self.assertEqual(st["source"], "lite")
        self.assertFalse(st["bridge"])
        self.assertFalse(st["ws"])
        self.assertFalse(st["online"])

    def test_lite_pid_mismatch_fails_closed(self):
        self._lite(pid_info={"pid": os.getpid(), "create_time": 1.0},
                   status={"state": "connected", "account_online": True})
        st = cs._qq_status()
        self.assertFalse(st["bridge"])
        self.assertFalse(st["online"])

    def test_no_legacy_fallback_when_external(self):
        """0831 设计（2026-10-20 19:58 落到 console_server.py）：

        external 模式下 QQ 归 Lite 独占，旧 napcat_status.json 是**停更的僵尸状态**，
        所以**不再回退**——Lite 文件缺失时 source 标 'lite-missing'，online/ws/bridge
        一律 False，防止面板显示旧链的"在线"。

        原测试（10/09）断言的是"回退旧链"，与该设计相反，已按新行为更新。
        """
        d = self.tmp / "cache" / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "napcat_status.json").write_text(
            json.dumps({"online": True, "ws": True, "since": 5.0}),
            encoding="utf-8")
        with patch("psutil.process_iter", return_value=[]):
            st = cs._qq_status()
        self.assertEqual(st["source"], "lite-missing")
        # 关键：旧链状态文件即使写着 online，也不许被当真
        self.assertFalse(st["online"], "external 下不许回退旧 napcat_status.json")
        self.assertFalse(st["ws"])
        self.assertFalse(st["bridge"])


if __name__ == "__main__":
    unittest.main()
