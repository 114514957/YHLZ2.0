"""0830 回归：QQ 派单守卫。

老爹原话（2026-10-20）："qq桥元亨派单逻辑混乱，我在 #退出任务 时依然在派单"。
现场证据：dev_jobs.db 里 18:50-19:04 连续出现 task='哦好了' / '差点' /
'你现在怎么样？元亨' / '她派单逻辑出问题了' —— 普通聊天被判成开发任务。

根因两条：
  1. 任何主人 `#` 指令都会 _set_work(True)，而 `#退出任务` 不清这个标记；
     之后每条普通聊天都被 `#dev + 原文` 二次派单（qq_bot.handle）。
  2. `_dev_cmd_lite` 的 else 兜底把未知 `#...` 整句当任务派发
     （`#cancle`、`#退出任务，这不是任务指令` 都被派出去了）。

Run: .venv\\Scripts\\python.exe -m unittest backend.test_qq_dispatch_guard
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
import uuid
from unittest import mock
from unittest.mock import AsyncMock

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))

# 沙箱对「测试运行期新建的子目录」不给写权限，临时文件直接落在
# 已存在且可写的 cache/tmp 下，用唯一文件名隔离。
_TMP_BASE = _ROOT / "cache" / "tmp"
_TMP_BASE.mkdir(parents=True, exist_ok=True)


def _tmpfile(tag: str) -> pathlib.Path:
    return _TMP_BASE / f"test_{tag}_{uuid.uuid4().hex}.json"


class CommandPolicyTests(unittest.TestCase):
    def test_exit_commands(self):
        from backend.qq_behavior import dev_exit_command

        for text in ("#退出任务", "#退出任务模式", "#退出",
                     "#退出任务 job20260101abc", "#退出 job1"):
            self.assertTrue(dev_exit_command(text), text)
        for text in ("#退出任务，这不是任务指令", "#退出任务x", "#退出任务模式化",
                     "退出任务", "#解除", "#取消任务", ""):
            self.assertFalse(dev_exit_command(text), text)

    def test_lane_commands(self):
        from backend.qq_behavior import dev_lane_command

        for text in ("#dev 修个 bug", "#任务派发 做事", "#y", "#n", "#push",
                     "#cancel job1", "#cancle", "#取消任务 job1",
                     "#answer job1 好了"):
            self.assertTrue(dev_lane_command(text), text)
        for text in ("#voice on", "#profile", "#", "#活泼", "#devstatus",
                     "#任务栏", "#解除", "哦好了"):
            self.assertFalse(dev_lane_command(text), text)


class DispatchRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import qq_bot as qq

        self.qq = qq
        self.state_file = _tmpfile("qq_state")
        self.addCleanup(lambda: self.state_file.unlink(missing_ok=True))
        self.env = mock.patch.dict(os.environ, {
            "YHLZ_QQ_PROFILE": "lite",
            "YHLZ_QQ_STATE_DIR": str(_TMP_BASE),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        for name, value in (("QQ_STATE", self.state_file),):
            p = mock.patch.object(qq, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.stub = mock.Mock()
        self.stub.start.return_value = {"status": "accepted", "text": "开工"}
        self.stub.detach.return_value = {"status": "ok", "text": "已退出"}
        self.stub.cancel.return_value = {"status": "ok", "text": "已取消"}
        self.stub.awaiting_job.return_value = None
        self._lite = mock.patch.object(qq, "_lite_dev", self.stub)
        self._lite.start()
        self.addCleanup(self._lite.stop)
        self.turn = mock.patch.object(
            qq, "_daemon_turn", lambda *a, **k: {"answer": ""})
        self.turn.start()
        self.addCleanup(self.turn.stop)
        self.bridge = qq.QQBridge("unused", "3655185302",
                                  pathlib.Path("unused"),
                                  masters={"2258374446"})
        self.bridge.log = mock.Mock()
        self.bridge._say = AsyncMock()

    def event(self, mid, text):
        return {"post_type": "message", "message_type": "private",
                "user_id": "2258374446", "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    def _says(self) -> list[str]:
        return [str(c.args[2]) for c in self.bridge._say.await_args_list]

    async def test_exit_task_clears_work_state(self):
        self.bridge._set_work("2258374446", True, "qq_p2258374446")
        self.assertTrue(self.bridge._work_enabled("2258374446"))
        await self.bridge.handle(None, self.event(1, "#退出任务"))
        self.stub.detach.assert_called_once()
        self.assertFalse(self.bridge._work_enabled("2258374446"))

    async def test_exit_task_without_dispatch(self):
        await self.bridge.handle(None, self.event(2, "#退出任务"))
        self.stub.start.assert_not_called()
        self.stub.detach.assert_called_once()

    async def test_plain_chat_never_dispatches(self):
        # 旧逻辑：work=True 时 '#dev ' + text 直接派单
        self.bridge._set_work("2258374446", True, "qq_p2258374446")
        await self.bridge.handle(None, self.event(3, "哦好了"))
        self.stub.start.assert_not_called()

    async def test_bug_report_line_never_dispatches(self):
        self.bridge._set_work("2258374446", True, "qq_p2258374446")
        await self.bridge.handle(None, self.event(4, "她派单逻辑出问题了"))
        self.stub.start.assert_not_called()

    async def test_unknown_hash_command_is_not_dispatched(self):
        await self.bridge.handle(None, self.event(5, "#退出任务，这不是任务指令"))
        self.stub.start.assert_not_called()
        self.assertTrue(any("未知指令" in t for t in self._says()), self._says())

    async def test_typo_hash_command_is_not_dispatched(self):
        await self.bridge.handle(None, self.event(6, "#bakend"))
        self.stub.start.assert_not_called()
        self.assertTrue(any("未知指令" in t for t in self._says()), self._says())

    async def test_cancel_typo_alias(self):
        await self.bridge.handle(None, self.event(7, "#cancle job1"))
        self.stub.cancel.assert_called_once_with("job1")

    async def test_cancel_task_alias(self):
        await self.bridge.handle(None, self.event(10, "#取消任务 job1"))
        self.stub.cancel.assert_called_once_with("job1")
        self.stub.detach.assert_not_called()

    async def test_non_lane_command_does_not_enable_work(self):
        await self.bridge.handle(None, self.event(8, "#voice on"))
        self.assertFalse(self.bridge._work_enabled("2258374446"))

    async def test_dev_command_keeps_work_lane(self):
        await self.bridge.handle(None, self.event(9, "#dev 修个测试"))
        self.stub.start.assert_called_once()
        self.assertTrue(self.bridge._work_enabled("2258374446"))


class LegacyReaperTests(unittest.TestCase):
    class _Proc:
        def __init__(self, pid, name, cmd):
            self.info = {"pid": pid, "name": name, "cmdline": cmd}

    class _Fake:
        def __init__(self, sink):
            self.sink = sink

        def terminate(self):
            self.sink.append("terminate")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.sink.append("kill")

    def test_reaps_only_legacy_scripts(self):
        import yhlz_launcher as launcher

        root = r"C:\repo"
        procs = [
            self._Proc(11, "python.exe", [r"C:\py\python.exe", "-B",
                                          root + r"\tools\qq_bot.py"]),
            self._Proc(12, "python.exe", [r"C:\py\python.exe", "-B",
                                          root + r"\tools\napcat_watch.py"]),
            self._Proc(13, "python.exe", [r"C:\py\python.exe", "-B",
                                          root + r"\tools\qq_bridge_service.py"]),
            self._Proc(14, "python.exe", [r"C:\py\python.exe", "-B",
                                          root + r"\tools\qq_bridge_watchdog.py"]),
            self._Proc(15, "python.exe", [r"C:\py\python.exe", "-c",
                                          "import psutil"]),
        ]
        sink: list[str] = []
        tmp_lock = _tmpfile("qq_lock")
        tmp_watch_lock = _tmpfile("watch_lock")
        with mock.patch("psutil.process_iter", return_value=procs), \
                mock.patch("psutil.Process", lambda pid: self._Fake(sink)), \
                mock.patch.object(launcher, "QQBOT_LOCK", tmp_lock), \
                mock.patch.object(launcher, "NAPCAT_WATCH_LOCK",
                                  tmp_watch_lock):
            killed = launcher._reap_legacy_qq()
        self.assertEqual(len(killed), 2)
        self.assertEqual(sink.count("terminate"), 2)
        self.assertTrue(any("qq_bot.py" in k for k in killed), killed)
        self.assertTrue(any("napcat_watch.py" in k for k in killed), killed)

    def test_watchdog_reaps_every_tick_in_external_mode(self):
        """看门狗在服务全健康时也要收旧链（旧逻辑只有 ensure_stack 才收）。"""
        import yhlz_launcher as launcher
        import yhlz_watchdog as wd

        healthy = {"ollama": True, "gemma": True, "daemon": True}
        with mock.patch.object(launcher, "status", return_value=healthy), \
                mock.patch.object(launcher, "qq_management",
                                  return_value="external"), \
                mock.patch.object(launcher, "_reap_legacy_qq",
                                  return_value=["11:qq_bot.py"]) as reap, \
                mock.patch.object(wd, "_load_state", return_value={}), \
                mock.patch.object(wd, "_save_state"), \
                mock.patch.object(wd, "_log"):
            after = wd.tick()
        self.assertTrue(reap.called)
        self.assertEqual(after, healthy)

    def test_ensure_stack_reaps_only_when_external(self):
        import yhlz_launcher as launcher

        base = {
            "status": mock.patch.object(
                launcher, "status",
                return_value={"ollama": True, "gemma": True, "daemon": True}),
            "_port_open": mock.patch.object(launcher, "_port_open",
                                            return_value=True),
            "_proc_alive": mock.patch.object(launcher, "_proc_alive",
                                             return_value=True),
            "_qqbot_alive": mock.patch.object(launcher, "_qqbot_alive",
                                              return_value=True),
            "_spawn_allowed": mock.patch.object(launcher, "_spawn_allowed",
                                                return_value=False),
            "_maybe_recycle_daemon": mock.patch.object(
                launcher, "_maybe_recycle_daemon"),
            "sleep": mock.patch.object(launcher.time, "sleep", lambda s: None),
        }
        for mode, expected in (("full", False), ("external", True)):
            patchers = list(base.values())
            for p in patchers:
                p.start()
            try:
                with mock.patch.object(launcher, "qq_management",
                                       return_value=mode), \
                        mock.patch.object(launcher, "_reap_legacy_qq") as reap:
                    launcher.ensure_stack()
                self.assertEqual(reap.called, expected, mode)
            finally:
                for p in patchers:
                    p.stop()


if __name__ == "__main__":
    unittest.main()
