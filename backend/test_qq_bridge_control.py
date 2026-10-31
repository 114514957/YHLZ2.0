"""Offline tests for qq_bridge_control chain management (2026-10-07)."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))

import qq_bridge_control as ctrl  # noqa: E402
from backend.qq_bridge_lock import make_info  # noqa: E402


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_status_shape(self):
        with mock.patch.object(ctrl, "_port_open", return_value=False):
            out = ctrl.cmd_status(self.tmp, {"uin": "3655185302"})
        self.assertTrue(out["ok"])
        for key in ("napcat", "bridge", "watchdog", "notices", "desired"):
            self.assertIn(key, out)
        self.assertFalse(out["napcat"]["alive"])
        self.assertFalse(out["bridge"]["alive"])

    def test_stop_without_processes(self):
        with mock.patch.object(ctrl.time, "sleep", lambda *_: None):
            out = ctrl.cmd_stop(self.tmp, with_napcat=False)
        self.assertTrue(out["ok"])
        self.assertEqual(out["desired"], "stopped")
        data = json.loads((self.tmp / "desired_state.json").read_text(
            encoding="utf-8"))
        self.assertEqual(data["desired"], "stopped")

    def test_watchdog_owner_detected(self):
        info = make_info("lite", entry=ctrl.WATCHDOG_ENTRY, role="watchdog")
        (self.tmp / "watchdog.lock").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8")
        out = ctrl.ensure_watchdog({"profile": "lite",
                                    "state_dir": str(self.tmp),
                                    "config_path": ""})
        self.assertFalse(out["started"])
        self.assertEqual(out["pid"], os.getpid())

    def test_ensure_napcat_skips_when_port_open(self):
        info = make_info("lite", entry=ctrl.NAPCAT_ENTRY, role="napcat")
        (self.tmp / "napcat.pid").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(ctrl, "_port_open", return_value=True), \
                mock.patch.object(ctrl, "subprocess"):
            out = ctrl.ensure_napcat({"profile": "lite",
                                      "state_dir": str(self.tmp),
                                      "uin": None, "onebot_config": None})
        self.assertTrue(out["port_open"])
        self.assertFalse(out["started"])

    def test_startup_resume_respects_manual_stop(self):
        from tools.qq_bridge_service import write_desired
        write_desired(self.tmp, "stopped")
        with mock.patch.object(ctrl, "load_profile", return_value={}), \
                mock.patch.object(ctrl, "resolve", return_value={"state_dir": str(self.tmp)}), \
                mock.patch.object(ctrl, "cmd_start") as start:
            self.assertEqual(ctrl.main(["resume"]), 0)
        start.assert_not_called()

    def test_login_startup_does_not_resume_running_when_disabled(self):
        from tools.qq_bridge_service import write_desired
        write_desired(self.tmp,"running")
        with mock.patch.object(ctrl,"load_profile",return_value={"auto_resume":False}), \
                mock.patch.object(ctrl,"resolve",return_value={"state_dir":str(self.tmp)}), \
                mock.patch.object(ctrl,"cmd_start") as start:
            self.assertEqual(ctrl.main(["resume"]),0)
        start.assert_not_called()

    def test_stale_online_snapshot_is_not_ready(self):
        clock = iter([0, 0, 100, 100])
        with mock.patch.object(ctrl.time,"time",side_effect=lambda:next(clock)), \
                mock.patch.object(ctrl.time,"sleep"), \
                mock.patch.object(ctrl,"_read_json",return_value={"state":"connected","account_online":True}), \
                mock.patch.object(ctrl,"_role_info",return_value={}):
            self.assertFalse(ctrl.wait_ready(self.tmp,timeout=1)["ready"])

    def test_resume_does_not_reset_or_bypass_exhausted_budget(self):
        (self.tmp / "watchdog_state.json").write_text(json.dumps({"napcat_launch_count": 174}))
        with mock.patch.object(ctrl, "ensure_napcat") as napcat, \
                mock.patch.object(ctrl, "ensure_watchdog", return_value={}), \
                mock.patch.object(ctrl, "wait_ready", return_value={"ready": False}):
            ctrl.cmd_start({"state_dir": str(self.tmp), "profile": "lite"}, reset_attempts=False)
        napcat.assert_not_called()
        data = json.loads((self.tmp / "watchdog_state.json").read_text())
        self.assertEqual(data["napcat_launch_count"], 174)

    # -- 2026-10-11 重复实例事故后的兜底清场 -------------------------------
    def test_stop_napcat_fallback_clear(self):
        """无记录且无 NapCat 特征进程 → 视为清场完成（可以安全重拉）。"""
        with mock.patch.object(ctrl, "_napcat_leftover_pids",
                               return_value=[]):
            out = ctrl.stop_napcat(self.tmp)
        self.assertTrue(out["stopped"])
        self.assertEqual(out.get("killed", 0), 0)

    def test_stop_napcat_fallback_kills_leftovers(self):
        with mock.patch.object(ctrl, "_napcat_leftover_pids",
                               return_value=[111, 222]), \
                mock.patch.object(ctrl, "_kill_pids",
                                  return_value=(True, [])) as k:
            out = ctrl.stop_napcat(self.tmp)
        self.assertTrue(out["stopped"])
        self.assertEqual(out["killed"], 2)
        k.assert_called_once()

    def test_stop_napcat_fallback_reports_survivors(self):
        """清不干净 → stopped=False + survivors（看门狗据此不再重拉）。"""
        with mock.patch.object(ctrl, "_napcat_leftover_pids",
                               return_value=[111]), \
                mock.patch.object(ctrl, "_kill_pids",
                                  return_value=(False, [111])):
            out = ctrl.stop_napcat(self.tmp)
        self.assertFalse(out["stopped"])
        self.assertEqual(out["survivors"], [111])


if __name__ == "__main__":
    unittest.main()
