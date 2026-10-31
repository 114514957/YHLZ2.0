"""P2 offline tests: notices, account lock, pid lock, watchdog breaker.

No network, no real QQ, no Full stack.
Run:
    .venv\\Scripts\\python.exe -m unittest backend.test_qq_bridge_p2
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from backend.qq_account_lock import AccountLock
from backend.qq_bridge_lock import (
    LockError, acquire_pid_lock, make_info, owner_matches, proc_create_time,
    terminate_owned,
)
from backend.qq_bridge_notices import NoticeStore

_ROOT = pathlib.Path(__file__).resolve().parent.parent

RECOVERY = {
    "check_interval_seconds": 2, "attempt_timeout_seconds": 15,
    "attempt2_delay_seconds": 2, "stall_seconds": 30,
    "start_grace_seconds": 30, "backoff_seconds": [15, 30, 60],
    "blocked_after_failures": 5, "blocked_retry_seconds": 600,
}
SUPERVISION = {
    "napcat_miss_grace_seconds": 100,
    "napcat_launch_cooldown_seconds": 300,
    "napcat_launch_wait_seconds": 1,
    "account_offline_grace_seconds": 100,
    "account_max_attempts": 2,
    "account_restart_cooldown_seconds": 50,
    "account_recover_wait_seconds": 1,
    "account_blocked_retry_seconds": 600,
    "scan_notice_after_seconds": 200,
}


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.store = NoticeStore(self.tmp / "notices.jsonl",
                                 bot_uin="3655185302", release_s=10.0)

    def test_lost_before_recovered(self):
        self.store.create(outage_id="o1", kind="lost", recipient="2258374446",
                          now=100.0)
        self.store.create(outage_id="o1", kind="recovered",
                          recipient="2258374446", now=101.0)
        nxt = self.store.next_to_send(now=102.0)
        self.assertEqual(nxt["kind"], "lost")
        self.store.mark(nxt["notice_id"], "sent", now=103.0)
        self.assertEqual(self.store.next_to_send(now=104.0)["kind"], "recovered")

    def test_unknown_lost_not_resent_and_releases_recovered(self):
        lost = self.store.create(outage_id="o2", kind="lost",
                                 recipient="2258374446", now=200.0)
        self.store.create(outage_id="o2", kind="recovered",
                          recipient="2258374446", now=201.0)
        self.store.mark(lost["notice_id"], "unknown", now=202.0)
        self.assertEqual(self.store.next_to_send(now=203.0)["kind"], "recovered")
        self.assertEqual(self.store.next_to_send(now=400.0)["kind"],
                         "recovered")

    def test_recovered_released_after_stuck_lost(self):
        self.store.create(outage_id="o3", kind="lost", recipient="2258374446",
                          now=300.0)
        self.store.create(outage_id="o3", kind="recovered",
                          recipient="2258374446", now=301.0)
        self.assertEqual(self.store.next_to_send(now=305.0)["kind"], "lost")
        nxt = self.store.next_to_send(now=311.0)
        self.assertEqual(nxt["kind"], "recovered")

    def test_fixed_texts_and_dedup(self):
        a = self.store.create(outage_id="o4", kind="lost",
                              recipient="2258374446", now=1.0)
        b = self.store.create(outage_id="o4", kind="lost",
                              recipient="2258374446", now=2.0)
        self.assertEqual(a["notice_id"], b["notice_id"])
        self.assertEqual(a["text"], "【系统检测到异常，元亨丢失】")
        self.assertEqual(len(self.store._load()), 1)


class AccountLockTests(unittest.TestCase):
    def test_single_holder_fail_closed(self):
        uin = f"test{__import__('os').getpid()}"
        first = AccountLock(uin)
        self.assertTrue(first.acquire())
        second = AccountLock(uin)
        self.assertFalse(second.acquire())
        first.release()
        third = AccountLock(uin)
        self.assertTrue(third.acquire())
        third.release()


class PidLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.lock = self.tmp / "bridge.lock"

    def test_live_owner_conflicts(self):
        self.assertNotEqual(proc_create_time(__import__("os").getpid()), 0.0)
        acquire_pid_lock(self.lock, make_info("lite", role="bridge"))
        with self.assertRaises(LockError):
            acquire_pid_lock(self.lock, make_info("lite", role="bridge"))

    def test_stale_lock_replaced(self):
        self.lock.write_text(json.dumps(
            {"pid": 99999999, "create_time": 1.0, "profile": "lite"}),
            encoding="utf-8")
        info = acquire_pid_lock(self.lock, make_info("lite", role="bridge"))
        self.assertEqual(info["profile"], "lite")

    def test_pid_reuse_detected(self):
        info = make_info("lite", role="bridge")
        info["create_time"] = 1.0
        ok, reason = owner_matches(info)
        self.assertFalse(ok)
        self.assertEqual(reason, "pid_reused")

    def test_terminate_refuses_pid_reuse(self):
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(30)"])
        try:
            info = {"pid": proc.pid, "create_time": 1.0}
            ok, reason = terminate_owned(info)
            self.assertFalse(ok)
            self.assertEqual(reason, "pid_reused")
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_terminate_refuses_entry_mismatch(self):
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(30)"])
        try:
            info = {"pid": proc.pid,
                    "create_time": proc_create_time(proc.pid),
                    "entry": str(_ROOT / "tools" / "not_same.py")}
            ok, reason = terminate_owned(info, entry=str(_ROOT / "tools" / "qq_bot.py"))
            self.assertFalse(ok)
            self.assertEqual(reason, "entry_mismatch")
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=10)


class WatchdogBreakerTests(unittest.TestCase):
    def test_five_failures_block_then_retry(self):
        from tools.qq_bridge_watchdog import FakeChecker, Watchdog

        base = pathlib.Path(tempfile.mkdtemp())
        clock = {"t": 0.0}
        resolved = {"profile": "lite", "state_dir": str(base),
                    "masters": ["2258374446"], "uin": "3655185302",
                    "config": {"recovery": dict(RECOVERY)}}
        checker = FakeChecker({"owner_ok": [False], "bridge_pid_info": [{}],
                               "bridge_status": [{}], "send_results": ["confirmed"]})
        wd = Watchdog(resolved, checker=checker, now=lambda: clock["t"],
                      jitter=lambda: 1.0, state_dir=base)
        for t in (0.0, 15.0, 17.0, 32.0, 47.0, 62.0, 92.0, 107.0,
                  167.0, 182.0):
            clock["t"] = t
            wd.tick()
        self.assertEqual(wd.state["phase"], "blocked")
        spawns = checker.calls["spawn"]
        clock["t"] = 781.0
        wd.tick()
        self.assertEqual(checker.calls["spawn"], spawns)  # still blocked
        clock["t"] = 783.0
        wd.tick()
        self.assertEqual(checker.calls["spawn"], spawns + 1)


class WatchdogSupervisionTests(unittest.TestCase):
    """账号监管（2026-10-10）：被踢自动重登 / NapCat 拉起 / 扫码提示。"""

    def _mk(self, checker_script, base):
        from tools.qq_bridge_watchdog import FakeChecker, Watchdog

        clock = {"t": 0.0}
        resolved = {"profile": "lite", "state_dir": str(base),
                    "masters": ["2258374446"], "uin": "3655185302",
                    "config": {"recovery": dict(RECOVERY),
                               "supervision": dict(SUPERVISION)}}
        checker = FakeChecker(checker_script)
        wd = Watchdog(resolved, checker=checker, now=lambda: clock["t"],
                      jitter=lambda: 1.0, state_dir=base)
        wd.qr_guard_path = base / "no_qr.png"  # 隔离扫码保护（默认无二维码）
        return wd, checker, clock

    @staticmethod
    def _status(online):
        return {"state": "connected", "account_online": online,
                "event_loop_ts": 1e9}

    def test_account_offline_restart_then_recovered(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [self._status(False), self._status(False),
                              self._status(True)],
            "send_results": ["locked"]}, base)
        clock["t"] = 10.0
        wd.tick()
        clock["t"] = 130.0
        wd.tick()
        self.assertEqual(checker.calls.get("napcat_restart"), 1)
        clock["t"] = 160.0
        wd.tick()
        self.assertEqual(wd.state["account_offline_since"], 0.0)
        self.assertEqual(wd.state["account_attempts"], 0)
        kinds = [i.get("kind") for i in wd.store._load()]
        self.assertIn("account_lost", kinds)
        self.assertIn("account_recovered", kinds)

    def test_account_blocked_after_max_attempts(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [self._status(False)],
            "send_results": ["locked"]}, base)
        for t in (10.0, 130.0, 200.0, 260.0, 330.0):
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_restart"), 2)
        kinds = [i.get("kind") for i in wd.store._load()]
        self.assertIn("account_needs_scan", kinds)
        self.assertGreater(wd.state["account_blocked_until"], 330.0)

    def test_awaiting_scan_skips_restart_then_resumes_when_stale(self):
        """2026-10-11：二维码新鲜=正在等人扫码 → 不重启；超时提醒；
        二维码变陈旧（无人扫）→ 恢复常规重登动作。"""
        base = pathlib.Path(tempfile.mkdtemp())
        qr = base / "qrcode.png"
        qr.write_bytes(b"x")
        os.utime(qr, (1000120, 1000120))
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [self._status(False)],
            "send_results": ["locked"]}, base)
        wd.qr_guard_path = qr
        clock["t"] = 1000010.0
        wd.tick()  # 离线计时开始
        clock["t"] = 1000130.0
        wd.tick()  # 宽限已过，但二维码新鲜 → 跳过重启
        self.assertEqual(checker.calls.get("napcat_restart", 0), 0)
        clock["t"] = 1000250.0
        wd.tick()  # 等待扫码超 200s → 发提醒（不重启）
        kinds = [i.get("kind") for i in wd.store._load()]
        self.assertIn("account_needs_scan", kinds)
        self.assertEqual(checker.calls.get("napcat_restart", 0), 0)
        os.utime(qr, (999000, 999000))  # 二维码变陈旧
        clock["t"] = 1001000.0
        wd.tick()
        self.assertEqual(checker.calls.get("napcat_restart"), 1)

    def test_napcat_missing_launches_once_with_cooldown(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [{"state": "reconnecting", "account_online": None,
                               "event_loop_ts": 1e9}],
            "onebot_reachable": [False], "napcat_running": [False],
            "napcat_owned_alive": [False],
            "launch_result": [{"port_open": True}],
            "send_results": ["locked"]}, base)
        for t in (10.0, 130.0, 150.0):
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_launch"), 1)

    def test_napcat_running_but_login_stuck_notices_scan(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [{"state": "reconnecting", "account_online": None,
                               "event_loop_ts": 1e9}],
            "onebot_reachable": [False], "napcat_running": [True],
            "send_results": ["locked"]}, base)
        for t in (10.0, 150.0, 250.0):
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_launch", 0), 0)
        kinds = [i.get("kind") for i in wd.store._load()]
        self.assertIn("account_needs_scan", kinds)


    def test_manual_only_policy_never_starts_or_relogs_after_failure(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid":1}],
            "bridge_status": [self._status(False)],
            "onebot_reachable": [False], "napcat_running": [False],
            "napcat_owned_alive": [False], "send_results": ["locked"]}, base)
        wd.auto_start_napcat = False
        wd.auto_relogin = False
        for t in [10, 200, 1000, 10000, 100000]:
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_launch",0),0)
        self.assertEqual(checker.calls.get("napcat_restart",0),0)

    def test_missing_napcat_launch_budget_does_not_reset_with_time(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [{"state": "reconnecting", "event_loop_ts": 1e9}],
            "onebot_reachable": [False], "napcat_running": [False],
            "napcat_owned_alive": [False], "send_results": ["locked"]}, base)
        for t in [10, 130, 450, 770, 1090, 5000, 100000]:
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_launch"), 3)
        self.assertEqual(wd.state["napcat_launch_count"], 3)
        # A new watchdog process reloads the same exhausted budget.
        wd2, checker2, clock2 = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [{"state": "reconnecting", "event_loop_ts": 1e9}],
            "onebot_reachable": [False], "napcat_running": [False],
            "napcat_owned_alive": [False], "send_results": ["locked"]}, base)
        clock2["t"] = 200000
        wd2.tick()
        self.assertEqual(checker2.calls.get("napcat_launch", 0), 0)

    def test_expired_account_budget_waits_for_manual_login(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [self._status(False)], "send_results": ["locked"]}, base)
        for t in [10, 130, 190, 250, 1000, 10000]:
            clock["t"] = t
            wd.tick()
        self.assertEqual(checker.calls.get("napcat_restart"), 2)
        self.assertTrue(wd.state["account_requires_login"])

    def test_qr_for_current_episode_remains_protected_after_150_seconds(self):
        base = pathlib.Path(tempfile.mkdtemp())
        wd, checker, clock = self._mk({
            "owner_ok": True, "bridge_pid_info": [{"pid": 1}],
            "bridge_status": [self._status(False)], "send_results": ["locked"]}, base)
        clock["t"] = 1000000
        wd.tick()
        qr = base / "qrcode.png"
        qr.write_bytes(b"fixture")
        os.utime(qr, (1000020, 1000020))
        wd.qr_guard_path = qr
        clock["t"] = 1003000
        wd.tick()
        self.assertEqual(checker.calls.get("napcat_restart", 0), 0)


class ServiceGateTests(unittest.TestCase):
    def test_stopped_desired_state_prevents_start(self):
        from tools.qq_bridge_service import run_service, write_desired

        base = pathlib.Path(tempfile.mkdtemp())
        write_desired(base, "stopped")
        rc = run_service({"profile": "lite", "state_dir": str(base),
                          "masters": ["2258374446"], "uin": None,
                          "onebot_config": None, "voice": False,
                          "conversation": "optional", "config": {}})
        self.assertEqual(rc, 0)
        self.assertFalse((base / "bridge.lock").exists())


if __name__ == "__main__":
    unittest.main()
