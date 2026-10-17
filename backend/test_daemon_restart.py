"""daemon_restart v2 regression tests (ledger 0803), fully offline.

Pins the incident of 2026-10-13 16:00: `killed=0` was reported as success while
the stale daemon kept serving 8321, and a "duplicate" rule that ignored the
launcher+interpreter pair would kill a healthy instance.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import daemon_restart as dr  # noqa: E402


class _FakeProc:
    def __init__(self, pid: int, ppid: int = 0, children: tuple = ()) -> None:
        self.pid = pid
        self._ppid = ppid
        self._children = [_FakeProc(c) for c in children]

    def ppid(self) -> int:
        return self._ppid

    def children(self, recursive: bool = True):
        return self._children


class FamilyTest(unittest.TestCase):
    def test_pair_is_one_instance(self):
        proc = _FakeProc(200, ppid=100)
        with mock.patch.object(dr.psutil, "Process", lambda pid: proc):
            self.assertEqual(dr.instance_family(200), {200, 100})

    def test_unknown_pid_yields_itself(self):
        def boom(pid):
            raise dr.psutil.NoSuchProcess(pid)

        with mock.patch.object(dr.psutil, "Process", boom):
            self.assertEqual(dr.instance_family(999), {999})


class KillReportingTest(unittest.TestCase):
    def test_kill_failure_is_reported_not_swallowed(self):
        done = mock.Mock(returncode=1, stderr="Access is denied.", stdout="")
        with mock.patch.object(dr.subprocess, "run", lambda *a, **k: done), \
                mock.patch.object(dr.psutil, "Process",
                                  side_effect=dr.psutil.AccessDenied(1)):
            ok, detail = dr.kill_pid(4242)
        self.assertFalse(ok)
        self.assertIn("denied", detail.lower())

    def test_taskkill_success_short_circuits(self):
        done = mock.Mock(returncode=0, stdout="SUCCESS", stderr="")
        with mock.patch.object(dr.subprocess, "run", lambda *a, **k: done):
            self.assertEqual(dr.kill_pid(1), (True, "taskkill"))


class RestartFlowTest(unittest.TestCase):
    """Scenario tests around the restart decision rule."""

    def setUp(self):
        self.killed: list[int] = []
        self.spawned = 0
        self.addCleanup(mock.patch.stopall)

    def _patch(self, *, pids_seq, owner_seq, health_seq, kill_ok=True,
               family=None):
        pids_state = list(pids_seq)
        owner_state = list(owner_seq)
        health_state = list(health_seq)

        def daemon_pids():
            return pids_state.pop(0) if len(pids_state) > 1 else pids_state[0]

        def port_owner(port=dr.PORT):
            return owner_state.pop(0) if len(owner_state) > 1 \
                else owner_state[0]

        def health(timeout=8.0):
            return health_state.pop(0) if len(health_state) > 1 \
                else health_state[0]

        def kill_pid(pid):
            if not kill_ok:
                return False, "denied"
            self.killed.append(pid)
            return True, "taskkill"

        def instance_family(pid):
            return set((family or {}).get(pid, {pid}))

        def spawn():
            self.spawned += 1

        mock.patch.object(dr, "daemon_pids", daemon_pids).start()
        mock.patch.object(dr, "port_owner", port_owner).start()
        mock.patch.object(dr, "health", health).start()
        mock.patch.object(dr, "kill_pid", kill_pid).start()
        mock.patch.object(dr, "instance_family", instance_family).start()
        mock.patch.object(dr, "_spawn_daemon", spawn).start()
        mock.patch.object(dr, "WAIT_SECONDS", 0.3).start()

    def test_restart_reports_success_only_with_fresh_health(self):
        # before: stale pair holds 8321; after: fresh pair, uptime < 60s
        self._patch(pids_seq=[[100, 200], [300, 400]],
                    owner_seq=[100, 300],
                    health_seq=[{"uptime_s": 28000.0}, {"uptime_s": 12.0}],
                    family={300: {300, 400}})
        self.assertEqual(dr.restart(), 0)
        self.assertEqual(sorted(self.killed), [100, 200])   # old pair killed
        self.assertEqual(self.spawned, 1)

    def test_restart_fails_when_kill_is_denied(self):
        self._patch(pids_seq=[[100, 200], [100, 200]],
                    owner_seq=[100, 100],
                    health_seq=[{"uptime_s": 28000.0}, {"uptime_s": 28000.0}],
                    kill_ok=False)
        self.assertEqual(dr.restart(), 1)   # stale owner survived, no rewrite
        self.assertEqual(self.killed, [])

    def test_extra_instance_outside_the_family_is_cleaned(self):
        # owner 300 is healthy; a watchdog-spawned 400 is an extra and goes away
        # (pids_seq covers: before-report, post-kill check, after-report,
        #  cleaned-report)
        self._patch(pids_seq=[[100], [300, 400], [300, 400], [300]],
                    owner_seq=[100, 300, 300],
                    health_seq=[{"uptime_s": 2.0}, {"uptime_s": 3.0},
                                {"uptime_s": 5.0}],
                    family={300: {300, 301}})
        self.assertEqual(dr.restart(), 0)
        self.assertIn(100, self.killed)
        self.assertIn(400, self.killed)
        self.assertNotIn(300, self.killed)
        self.assertNotIn(301, self.killed)

    def test_healthy_status_mode_is_read_only(self):
        self._patch(pids_seq=[[300, 301]], owner_seq=[300],
                    health_seq=[{"uptime_s": 900.0}])
        self.assertEqual(dr.status(), 0)
        self.assertEqual(self.killed, [])
        self.assertEqual(self.spawned, 0)


if __name__ == "__main__":
    unittest.main()
