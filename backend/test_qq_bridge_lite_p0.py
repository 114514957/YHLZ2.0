"""Offline P0 tests: QQ bridge profile state paths stay isolated from Full.

No network, no services started. Run:
    .venv\\Scripts\\python.exe -m unittest backend.test_qq_bridge_lite_p0
"""
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

from backend import qq_bridge_state

_ROOT = pathlib.Path(__file__).resolve().parent.parent

_PROBE = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location(
    "QQBotProbe", sys.argv[1] + "/tools/qq_bot.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("@@P@@" + json.dumps({
    "status": str(mod.QQ_STATUS), "lock": str(mod._bridge_path(
        "bridge.lock", __import__("pathlib").Path("legacy-lock"))),
    "bad_modules": sorted(m for m in
        ("yhlz_launcher", "yhlz_watchdog", "napcat_watch")
        if m in sys.modules),
}))
"""


class StatePathTest(unittest.TestCase):
    def test_default_is_legacy_full(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YHLZ_QQ_PROFILE", None)
            os.environ.pop("YHLZ_QQ_STATE_DIR", None)
            legacy = qq_bridge_state.LEGACY_DIR / "qqbot.lock"
            self.assertEqual(qq_bridge_state.path("bridge.lock", legacy), legacy)
            self.assertEqual(qq_bridge_state.state_dir(),
                             qq_bridge_state.LEGACY_DIR)
            self.assertFalse(qq_bridge_state.is_scoped())

    def test_lite_profile_moves_paths(self):
        with mock.patch.dict(os.environ, {"YHLZ_QQ_PROFILE": "lite"}):
            self.assertEqual(
                qq_bridge_state.state_dir(),
                _ROOT / "cache" / "qq_bridge" / "lite")
            self.assertTrue(qq_bridge_state.is_scoped())
            self.assertEqual(
                qq_bridge_state.path("bridge.lock", pathlib.Path("legacy")),
                _ROOT / "cache" / "qq_bridge" / "lite" / "bridge.lock")

    def test_state_dir_env_wins(self):
        with mock.patch.dict(os.environ, {
                "YHLZ_QQ_PROFILE": "lite",
                "YHLZ_QQ_STATE_DIR": str(_ROOT / "cache" / "p0sandbox")}):
            self.assertEqual(qq_bridge_state.state_dir(),
                             _ROOT / "cache" / "p0sandbox")

    def test_profile_traversal_sanitized(self):
        with mock.patch.dict(os.environ,
                             {"YHLZ_QQ_PROFILE": "..\\..\\evil"}):
            self.assertEqual(qq_bridge_state.profile(), "evil")
            self.assertIn("cache", str(qq_bridge_state.state_dir()))
            self.assertNotIn("..", str(qq_bridge_state.state_dir()))


class ProfileConfigTest(unittest.TestCase):
    def test_example_config_non_sensitive(self):
        cfg = json.loads(
            (_ROOT / "config" / "qq_bridge_lite.json").read_text("utf-8"))
        self.assertEqual(cfg["profile"], "lite")
        self.assertEqual(cfg["master_uins"], ["2258374446"])
        self.assertEqual(cfg["notify_owner"], "2258374446")
        self.assertFalse([k for k, v in cfg.items()
                          if "token" in k.lower() and v])


class BridgeImportTest(unittest.TestCase):
    def _probe(self, env: dict) -> dict:
        run_env = dict(os.environ)
        run_env.pop("YHLZ_QQ_PROFILE", None)
        run_env.pop("YHLZ_QQ_STATE_DIR", None)
        run_env.update(env)
        out = subprocess.run([sys.executable, "-c", _PROBE, str(_ROOT)],
                             cwd=_ROOT, capture_output=True, text=True,
                             timeout=120, env=run_env)
        for line in (out.stdout or "").splitlines():
            if line.startswith("@@P@@"):
                return json.loads(line[5:])
        self.fail(f"probe failed rc={out.returncode}: {out.stderr[-300:]}")

    def test_full_defaults_and_no_full_watchdog_import(self):
        got = self._probe({})
        self.assertTrue(got["status"].endswith(
            str(pathlib.Path("cache", "tmp", "qq_bridge_status.json"))))
        self.assertEqual(got["lock"], "legacy-lock")
        self.assertEqual(got["bad_modules"], [])

    def test_lite_paths_and_no_full_watchdog_import(self):
        got = self._probe({"YHLZ_QQ_PROFILE": "lite"})
        self.assertIn(str(pathlib.Path("cache", "qq_bridge", "lite")),
                      got["status"])
        self.assertEqual(got["bad_modules"], [])


if __name__ == "__main__":
    unittest.main()
