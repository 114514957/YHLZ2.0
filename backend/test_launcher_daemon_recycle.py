"""launcher daemon 健康自愈节流（0535）：空闲且超时 → 回收，默认关。

不启动/杀死真实进程；psutil 与 /health 均被替换。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import yhlz_launcher as L  # noqa: E402


class _Proc:
    def __init__(self):
        self.info = {"cmdline": ["python", "-m", "backend.target_daemon",
                                 "--port", "8321"]}
        self.killed = False

    def kill(self):
        self.killed = True


class DaemonRecycleTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(L, "_daemon_health") as health:
            L._maybe_recycle_daemon()
            health.assert_not_called()

    def test_recycles_idle_over_uptime(self):
        proc = _Proc()
        env = {"YHLZ_DAEMON_MAX_UPTIME_S": "10"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(L, "_daemon_health",
                             return_value={"uptime_s": 99, "active_turns": 0}), \
                patch.object(L, "_spawn_allowed", return_value=True), \
                patch("psutil.process_iter", return_value=[proc]):
            L._maybe_recycle_daemon()
        self.assertTrue(proc.killed)

    def test_busy_daemon_not_recycled(self):
        proc = _Proc()
        env = {"YHLZ_DAEMON_MAX_UPTIME_S": "10"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(L, "_daemon_health",
                             return_value={"uptime_s": 99, "active_turns": 1}), \
                patch.object(L, "_spawn_allowed", return_value=True), \
                patch("psutil.process_iter", return_value=[proc]):
            L._maybe_recycle_daemon()
        self.assertFalse(proc.killed)

    def test_young_daemon_not_recycled(self):
        proc = _Proc()
        env = {"YHLZ_DAEMON_MAX_UPTIME_S": "10000"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(L, "_daemon_health",
                             return_value={"uptime_s": 5, "active_turns": 0}), \
                patch.object(L, "_spawn_allowed", return_value=True), \
                patch("psutil.process_iter", return_value=[proc]):
            L._maybe_recycle_daemon()
        self.assertFalse(proc.killed)


if __name__ == "__main__":
    unittest.main()
