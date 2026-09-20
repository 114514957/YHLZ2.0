"""dev_runner dual-track backend tests (v1.1, ledger 0446).

The dsh backend proxies start/answer to tools/dsh_worker.py over HTTP; these
tests use a fake worker so no SDK/CLI process is needed.
"""
import importlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))


class _FakeWorker(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):  # noqa: D102
        pass

    def _send(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._send({"status": "ok"})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        _FakeWorker.calls.append((self.path.split("?")[0], payload))
        self._send({"ok": True, "status": "running", "session": "dev-1"})


class DevRunnerBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeWorker)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        os.environ["YHLZ_DSH_WORKER"] = cls.url
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        cls.dr = importlib.reload(importlib.import_module("dev_runner"))
        cls._state = cls.dr.STATE
        cls.dr.STATE = cls.tmp / "state.json"
        # isolate the A1 gray-switch file too (the repo may be switched to dsh)
        cls._backend_file = cls.dr.BACKEND_FILE
        cls.dr.BACKEND_FILE = cls.tmp / "backend.txt"

    @classmethod
    def tearDownClass(cls):
        cls.dr.STATE = cls._state
        cls.dr.BACKEND_FILE = cls._backend_file
        cls.srv.shutdown()

    def setUp(self):
        _FakeWorker.calls = []

    def test_backend_selection(self):
        os.environ["YHLZ_DEV_BACKEND"] = "bogus"
        self.assertEqual(self.dr._backend(), "opencode")
        os.environ["YHLZ_DEV_BACKEND"] = "dsh"
        self.assertEqual(self.dr._backend(), "dsh")
        os.environ.pop("YHLZ_DEV_BACKEND", None)
        self.assertEqual(self.dr._backend(), "opencode")

    def test_dsh_start_posts_to_worker(self):
        os.environ["YHLZ_DEV_BACKEND"] = "dsh"
        try:
            res = self.dr.start("把 X 改成 Y")
        finally:
            os.environ.pop("YHLZ_DEV_BACKEND", None)
        self.assertEqual([c[0] for c in _FakeWorker.calls], ["/start"])
        self.assertEqual(_FakeWorker.calls[0][1].get("task"), "把 X 改成 Y")
        self.assertIn(res.get("status"), ("running", "idle", "awaiting"))

    def test_dsh_answer_posts_to_worker(self):
        os.environ["YHLZ_DEV_BACKEND"] = "dsh"
        try:
            self.dr.answer("用方案 A")
        finally:
            os.environ.pop("YHLZ_DEV_BACKEND", None)
        self.assertEqual([c[0] for c in _FakeWorker.calls], ["/answer"])
        self.assertEqual(_FakeWorker.calls[0][1].get("text"), "用方案 A")

    def test_backend_file_precedence(self):
        """A1 (ledger 0450): env > backend.txt > opencode default."""
        import pathlib
        import tempfile

        old = self.dr.BACKEND_FILE
        self.dr.BACKEND_FILE = pathlib.Path(tempfile.mkdtemp()) / "backend.txt"
        os.environ.pop("YHLZ_DEV_BACKEND", None)
        try:
            self.assertEqual(self.dr._backend(), "opencode")
            self.assertIn("dsh", self.dr.set_backend("dsh"))
            self.assertEqual(self.dr._backend(), "dsh")
            os.environ["YHLZ_DEV_BACKEND"] = "opencode"
            self.assertEqual(self.dr._backend(), "opencode")  # env wins
        finally:
            os.environ.pop("YHLZ_DEV_BACKEND", None)
            self.dr.BACKEND_FILE = old

    def test_set_backend_rejects_bad(self):
        self.assertIn("用法", self.dr.set_backend("bogus"))

    def test_dsh_start_fails_when_worker_down_and_venv_missing(self):
        os.environ["YHLZ_DEV_BACKEND"] = "dsh"
        os.environ["YHLZ_DSH_WORKER"] = "http://127.0.0.1:9"
        os.environ["YHLZ_DSH_PYTHON"] = str(self.tmp / "nope.exe")
        try:
            self.dr.DSH_WORKER_URL = "http://127.0.0.1:9"
            self.dr.DSH_PY = self.tmp / "nope.exe"
            res = self.dr.start("x")
        finally:
            os.environ.pop("YHLZ_DEV_BACKEND", None)
            os.environ["YHLZ_DSH_WORKER"] = self.url
            self.dr.DSH_WORKER_URL = self.url
        self.assertEqual(res.get("status"), "error")


if __name__ == "__main__":
    unittest.main()
