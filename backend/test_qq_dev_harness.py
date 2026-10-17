"""QQ Bridge Lite × harness worker tests (ledger 0797), fully offline.

Covers the mapping contract of `tools/qq_dev_worker.py` when the executor is
the resident harness gateway: awaiting/done/error/timeout, legacy `opencode`
rows, and a dead gateway. Also exercises `harness_gateway.run_job` polling
against a fake HTTP worker (no SDK, no network, no CLI).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import harness_gateway as gw  # noqa: E402
import qq_dev_worker as worker  # noqa: E402
from backend import qq_dev_git as githelp  # noqa: E402
from backend import qq_dev_jobs as jobs  # noqa: E402


class _JobFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.ws = self.tmp / "ws"
        self.ws.mkdir()
        self.db = self.tmp / "dev_jobs.db"
        con = jobs.connect(self.db)
        self.job = jobs.create(con, owner_id="2258374446", channel="qq_p1",
                               target_project="repo", workspace=str(self.ws),
                               shared_workspace=True, branch="main",
                               backend="dsh", task="把 X 改成 Y",
                               base_head="head1", base_status="")
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(githelp, "changed_files", lambda ws: ["a.py"]).start()
        mock.patch.object(githelp, "snapshot",
                          lambda ws, head: {"hash": "snap1"}).start()
        self.posts: list = []
        mock.patch.object(gw, "ensure", lambda **kw: True).start()
        mock.patch.object(gw, "post",
                          lambda path, obj, **kw: (self.posts.append(path)
                                                   or {"ok": True})).start()

    def _run(self, result: dict, action: str = "start",
             job_id: str | None = None) -> dict:
        with mock.patch.object(gw, "run_job", lambda *a, **kw: result):
            rc = worker.run_job(str(self.db), job_id or self.job["job_id"],
                                action)
        con = jobs.connect(self.db)
        return {"rc": rc, "job": jobs.get(con, job_id or self.job["job_id"])}


class HarnessMappingTest(_JobFixture):
    def test_awaiting_maps_to_awaiting_owner(self):
        out = self._run({"state": "awaiting", "text": "[QUESTION]\n1. 范围？",
                         "session": self.job["job_id"], "error": "",
                         "timed_out": False})
        self.assertEqual(out["job"]["state"], "awaiting_owner")
        self.assertIn("[QUESTION]", out["job"]["question"])
        self.assertEqual(out["job"]["session_id"], self.job["job_id"])
        self.assertEqual(out["job"]["changed_files"], ["a.py"])

    def test_done_maps_to_completed_with_snapshot(self):
        out = self._run({"state": "done", "text": "[DONE] 已改好并验证",
                         "session": self.job["job_id"], "error": "",
                         "timed_out": False})
        self.assertEqual(out["job"]["state"], "completed")
        self.assertIn("[DONE]", out["job"]["report"])
        self.assertEqual(out["job"]["confirmed_snapshot"], "snap1")
        self.assertIn("/job/dispose", self.posts)  # runtime freed

    def test_error_maps_to_failed(self):
        out = self._run({"state": "error", "text": "", "session": "",
                         "error": "boom", "timed_out": False})
        self.assertEqual(out["job"]["state"], "failed")
        self.assertIn("boom", out["job"]["error"])

    def test_timeout_maps_to_failed(self):
        out = self._run({"state": "error", "text": "半截", "session": "",
                         "error": "超时 1800s", "timed_out": True})
        self.assertEqual(out["job"]["state"], "failed")
        self.assertIn("超时", out["job"]["error"])

    def test_empty_output_never_reports_success(self):
        out = self._run({"state": "done", "text": "", "session": "",
                         "error": "", "timed_out": False})
        self.assertEqual(out["job"]["state"], "failed")

    def test_legacy_opencode_row_runs_on_harness(self):
        con = jobs.connect(self.db)
        job = jobs.create(con, owner_id="2258374446", channel="qq_p1",
                          target_project="repo", workspace=str(self.ws),
                          shared_workspace=True, branch="main",
                          backend="opencode", task="旧行", base_head="h",
                          base_status="")
        out = self._run({"state": "done", "text": "[DONE] ok", "session": "",
                         "error": "", "timed_out": False},
                        job_id=job["job_id"])
        self.assertEqual(out["job"]["state"], "completed")
        log = pathlib.Path(out["job"]["log_path"]).read_text(encoding="utf-8")
        self.assertIn("退役", log)

    def test_dead_gateway_fails_closed(self):
        with mock.patch.object(gw, "ensure", lambda **kw: False):
            rc = worker.run_job(str(self.db), self.job["job_id"], "start")
        con = jobs.connect(self.db)
        job = jobs.get(con, self.job["job_id"])
        self.assertEqual(rc, 1)
        self.assertEqual(job["state"], "failed")
        self.assertIn("网关", job["error"])


class _FakeGateway(BaseHTTPRequestHandler):
    """Serves one job: running → (after N polls) done."""
    polls = 0

    def log_message(self, *a):
        pass

    def _send(self, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0") or 0)
        self.rfile.read(n)
        self._send({"ok": True, "state": "running"})

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/job/state"):
            _FakeGateway.polls += 1
            state = "running" if _FakeGateway.polls < 2 else "done"
            self._send({"state": state, "text": "[DONE] ok", "session": "j1",
                        "error": ""})
        else:
            self._send({"status": "ok"})


class GatewayPollingTest(unittest.TestCase):
    def test_run_job_polls_until_terminal(self):
        _FakeGateway.polls = 0
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeGateway)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        result = gw.run_job("job1", str(_ROOT), "start", task="t",
                            timeout=10, poll=0.05, url=url)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "done")
        self.assertIn("[DONE]", result["text"])


class LeaseWatchdogTest(unittest.TestCase):
    """A dead client must not leave a harness run writing into the workspace."""

    def test_stale_running_job_is_stopped(self):
        import dsh_worker as worker_mod

        disposed: list = []
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(worker_mod, "_dispose",
                          lambda ws: disposed.append(ws)).start()
        mock.patch.object(worker_mod, "LEASE_SECONDS", 60.0).start()
        # keep the sweep away from the live cache/dev/harness_jobs directory
        mock.patch.object(worker_mod, "JOBS_DIR",
                          pathlib.Path(tempfile.mkdtemp())).start()
        worker_mod._jobs.clear()
        self.addCleanup(worker_mod._jobs.clear)
        worker_mod._jobs["j-stale"] = {"job_id": "j-stale", "state": "running",
                                       "workspace": str(_ROOT), "lease": 1.0}
        worker_mod._jobs["j-live"] = {"job_id": "j-live", "state": "running",
                                      "workspace": str(_ROOT), "lease": 9e9}
        self.assertEqual(worker_mod._sweep_leases(), 1)
        self.assertEqual(worker_mod._jobs["j-stale"]["state"], "cancelled")
        self.assertEqual(worker_mod._jobs["j-live"]["state"], "running")
        self.assertEqual(disposed, [str(_ROOT)])


if __name__ == "__main__":
    unittest.main()
