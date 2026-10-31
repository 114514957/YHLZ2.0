"""NapCat launch env, permissions and workbench actions without a real QQ."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend import napcat_launcher as launch
from backend import console_server as cs


class NapcatLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "shell" / "config").mkdir(parents=True)
        (self.root / "shell" / "launcher-user.bat").write_text("@echo off\n", encoding="utf-8")
        self.webui = self.root / "shell" / "config" / "webui.json"
        self.webui.write_text(json.dumps({"autoLoginAccount": "123", "token": "local-fixture"}))
        self.entry = self.root / "entry with spaces.bat"
        self.entry.touch()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(launch, "QQWATCH_SHELL", self.root / "shell"))
        self.stack.enter_context(patch.dict(launch.os.environ, {"YHLZ_QQ_EXE": str(self.entry)}))
        self.stack.enter_context(patch.object(launch, "NAPCAT_WEBUI", self.webui))
        self.stack.enter_context(patch.object(launch, "is_elevated", return_value=False))
        # The local machine may actually have 3001 open; tests never depend on it.
        self.stack.enter_context(patch.object(launch, "onebot_online", return_value=False))
        self.stack.enter_context(patch.object(launch, "wait_online", return_value=False))
        self.stack.enter_context(patch.object(launch, "_kill_stale"))

    def credentials(self):
        secret = "local-fixture-%&!漢字"
        (self.root / "shell" / "config" / "quick_login.env").write_text(
            "ACCOUNT=123\nNAPCAT_QUICK_ACCOUNT=123\nNAPCAT_QUICK_PASSWORD=" + secret,
            encoding="utf-8-sig")
        return secret

    def test_launch_brokers_existing_entry_without_exposing_password(self):
        secret = self.credentials()
        with patch.object(launch.subprocess, "Popen", return_value=Mock(pid=4242)) as run:
            result = launch.launch_napcat("123")
        command = " ".join(run.call_args_list[0].args[0])
        options = run.call_args_list[0].kwargs
        self.assertIn("cmd.exe", command.lower())
        self.assertIn("launcher-user.bat", command)
        self.assertEqual(Path(options["cwd"]), self.root / "shell")
        self.assertNotIn("runas", command.lower())
        self.assertNotIn(secret, command)
        self.assertNotIn(secret, str(options["env"]))
        self.assertEqual(options["env"]["YHLZ_QUICK_UIN"], "123")
        self.assertNotIn("NAPCAT_QUICK_PASSWORD", options["env"])
        self.assertFalse(result["elevated"])
        self.assertEqual(result["method"], "launcher_user")
        self.assertEqual(json.loads(self.webui.read_text())["token"], "local-fixture")

    def test_switch_never_reuses_another_accounts_saved_password(self):
        secret=self.credentials()
        with patch.object(launch.subprocess,"Popen",return_value=Mock(pid=4242)) as run:
            launch.launch_napcat("456")
        self.assertEqual(run.call_args_list[0].kwargs["env"]["YHLZ_QUICK_UIN"],"456")
        self.assertNotIn(secret,str(run.call_args_list[0].kwargs["env"]))
        self.assertEqual(json.loads(self.webui.read_text())["autoLoginAccount"],"456")

    def test_online_napcat_is_not_launched_twice(self):
        with patch.object(launch, "onebot_online", return_value=True), \
                patch.object(launch.subprocess, "Popen") as run:
            result = launch.launch_napcat("123")
        run.assert_not_called()
        self.assertTrue(result["already"])
        self.assertFalse(result["elevated"])

    def test_one_shot_cmd_does_not_load_password_fallback(self):
        entry=Path(__file__).resolve().parents[1]/'tools'/'napcat_single_login.cmd'
        script=entry.read_text(encoding='utf-8')
        self.assertNotIn('quick_login.env',script)
        self.assertIn('set "NAPCAT_QUICK_PASSWORD="',script)
        self.assertIn('set "NAPCAT_QUICK_PASSWORD_MD5="',script)
        launcher=(entry.parent/'napcat_start_user.cmd').read_text(encoding='utf-8')
        self.assertIn('napcat_single_login.cmd',launcher)

    def test_elevated_launch_is_refused_before_changes(self):
        before = self.webui.read_bytes()
        with patch.object(launch, "is_elevated", return_value=True), \
                patch.object(launch.subprocess, "Popen") as run:
            with self.assertRaises(PermissionError):
                launch.launch_napcat("123")
        run.assert_not_called()
        self.assertEqual(self.webui.read_bytes(), before)

    def test_invalid_account_cannot_enter_cmd(self):
        with patch.object(launch.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                launch.launch_napcat("123&echo unsafe")
        run.assert_not_called()


class WorkbenchQqControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tools").mkdir()
        (self.root / "tools" / "qq_bridge_control.py").touch()
        self.handler = object.__new__(cs.ConsoleHandler)

    def test_stop_and_restart_preserve_napcat_login(self):
        with patch.object(cs, "_PROJECT_ROOT", self.root), \
                patch.object(cs, "_log"), \
                patch.object(cs.subprocess, "Popen") as popen:
            for action in ["qq_bridge_stop", "qq_bridge_restart"]:
                result = self.handler._control({"action": action})
                self.assertTrue(result["ok"])
                self.assertIn("--no-napcat", popen.call_args.args[0])

    def test_wake_reuses_existing_login_instead_of_killing_qq(self):
        with patch.object(cs, "_napcat_procs_alive", return_value=True), \
                patch("backend.napcat_launcher.launch_napcat") as spawn, \
                patch.object(cs.subprocess, "run") as run:
            result = self.handler._control({"action": "napcat_login"})
        self.assertTrue(result["ok"])
        spawn.assert_not_called()
        run.assert_not_called()

    def test_wake_uses_shared_nonadmin_entry(self):
        with patch.object(cs, "_napcat_procs_alive", return_value=False), \
                patch.object(cs, "_log"), \
                patch("backend.napcat_launcher.launch_napcat") as spawn:
            result = self.handler._control({"action": "napcat_login"})
        self.assertTrue(result["ok"])
        spawn.assert_called_once_with(cs.BOT_UIN)
