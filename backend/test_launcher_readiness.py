"""Desktop entry readiness, full-stack failure reporting; no real services."""
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from tools import yhlz_launcher as launcher


class LauncherReadinessTests(unittest.TestCase):
    def run_launcher(self, state, *args):
        with patch("sys.argv", ["yhlz_launcher.py", *args]), \
                patch.object(launcher, "ensure_stack"), \
                patch.object(launcher, "status", return_value=state), \
                patch.object(launcher.time, "sleep") as sleep, \
                patch.object(launcher.webbrowser, "open") as browser, \
                redirect_stdout(io.StringIO()):
            result = launcher.main()
        return result, browser, sleep

    def test_workbench_opens_while_models_load(self):
        result, browser, sleep = self.run_launcher(
            {"daemon": True, "gemma": False, "ollama": False})
        self.assertEqual(result, 0)
        browser.assert_called_once_with("http://127.0.0.1:8321/")
        sleep.assert_not_called()

    def test_workbench_waits_for_daemon(self):
        ready = {"daemon": True, "gemma": False, "ollama": False}
        with patch("sys.argv", ["yhlz_launcher.py"]), \
                patch.object(launcher, "ensure_stack"), \
                patch.object(launcher, "status", side_effect=[
                    {**ready, "daemon": False}, ready]), \
                patch.object(launcher.time, "sleep") as sleep, \
                patch.object(launcher.webbrowser, "open") as browser, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
        sleep.assert_called_once_with(1)
        browser.assert_called_once()

    def test_daemon_timeout_never_opens_dead_workbench(self):
        result, browser, _ = self.run_launcher(
            {"daemon": False, "gemma": True, "ollama": True})
        self.assertEqual(result, 1)
        browser.assert_not_called()

    def test_no_browser_reports_model_timeout_as_failure(self):
        result, browser, _ = self.run_launcher(
            {"daemon": True, "gemma": False, "ollama": True}, "--no-browser")
        self.assertEqual(result, 1)
        browser.assert_not_called()

    def test_no_browser_succeeds_with_full_stack(self):
        result, browser, sleep = self.run_launcher(
            {"daemon": True, "gemma": True, "ollama": True}, "--no-browser")
        self.assertEqual(result, 0)
        browser.assert_not_called()
        sleep.assert_not_called()

    def test_failed_self_test_does_not_print_ok(self):
        response = unittest.mock.MagicMock()
        response.read.return_value = b"YHLZ"
        with patch.object(launcher, "ensure_stack"), \
                patch.object(launcher, "status", return_value={
                    "daemon": True, "gemma": False, "ollama": True}), \
                patch.object(launcher.time, "sleep"), \
                patch("urllib.request.urlopen", return_value=response), \
                redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as error:
                launcher._self_test()
        self.assertEqual(error.exception.code, 1)
        self.assertIn("SELFTEST FAIL", out.getvalue())
        self.assertNotIn("SELFTEST OK", out.getvalue())
