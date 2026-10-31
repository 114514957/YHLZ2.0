"""节点A daemon 接线：音频 turn 走共享目标图（opt-in、默认关、失败回退）。

不打开设备、不加载模型：只验证门控与环境绑定/回退决策。
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.target_daemon import (  # noqa: E402
    DaemonRuntime,
    _daemon_target_device_binding,
    _daemon_target_voice_enabled,
)


def _bare_runtime() -> DaemonRuntime:
    """A DaemonRuntime with only the target-voice attrs (no loops/devices)."""
    rt = object.__new__(DaemonRuntime)
    rt._target_voice = None
    rt._target_voice_error = ""
    rt._target_voice_lock = threading.Lock()
    return rt


class DaemonTargetVoiceGateTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_daemon_target_voice_enabled())

    def test_flag_on(self):
        with patch.dict(os.environ, {"YHLZ_DAEMON_TARGET_VOICE": "1"}, clear=True):
            self.assertTrue(_daemon_target_voice_enabled())

    def test_binding_requires_names(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Exception):
                _daemon_target_device_binding()

    def test_binding_from_env(self):
        env = {"YHLZ_TARGET_INPUT_NAME": "麦克风", "YHLZ_TARGET_OUTPUT_NAME": "扬声器",
               "YHLZ_TARGET_ROUTE": "headset"}
        with patch.dict(os.environ, env, clear=True):
            binding = _daemon_target_device_binding()
            self.assertEqual(binding.input_name, "麦克风")
            self.assertEqual(binding.route, "headset")

    def test_ensure_returns_none_when_flag_off(self):
        rt = _bare_runtime()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(rt._ensure_target_voice())
        self.assertIsNone(rt._target_voice)
        self.assertEqual(rt._target_voice_error, "")

    def test_ensure_fails_closed_without_device_names(self):
        rt = _bare_runtime()
        with patch.dict(os.environ, {"YHLZ_DAEMON_TARGET_VOICE": "1"}, clear=True):
            self.assertIsNone(rt._ensure_target_voice())  # no devices opened
        self.assertEqual(rt._target_voice_error, "DeviceBindingError")

    def test_target_voice_turn_falls_back_when_not_enabled(self):
        rt = _bare_runtime()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(rt._target_voice_turn("元亨", "private", ["a.wav"]))


if __name__ == "__main__":
    unittest.main()
