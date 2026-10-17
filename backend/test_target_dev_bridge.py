"""[[dev: ...]] hand-off extraction tests (ledger 0406)."""
import unittest

from backend.target_dev_bridge import extract_dev_task


class DevBridgeTest(unittest.TestCase):
    def test_extract_marker(self):
        clean, task = extract_dev_task("好的，我交给利贞。\n[[dev: 修复登录bug]]")
        self.assertNotIn("[[dev", clean)
        self.assertIn("我交给利贞", clean)
        self.assertEqual(task, "修复登录bug")

    def test_fullwidth_colon(self):
        clean, task = extract_dev_task("[[dev：把 X 改成 Y]]")
        self.assertEqual(task, "把 X 改成 Y")
        self.assertEqual(clean, "")

    def test_no_marker(self):
        clean, task = extract_dev_task("今天天气不错")
        self.assertEqual(task, "")
        self.assertEqual(clean, "今天天气不错")

    def test_multiline_task(self):
        _, task = extract_dev_task("[[dev: 第一步\n第二步]]")
        self.assertIn("第一步", task)
        self.assertIn("第二步", task)

    def test_command_routing_safe_branches(self):
        from backend.target_dev_bridge import handle_dev_command

        self.assertIsNone(handle_dev_command("今天天气不错"))
        self.assertEqual(handle_dev_command("#dev"), "用法：#dev <任务>")
        self.assertEqual(handle_dev_command("#a"), "用法：#a <给利贞的答复>")
        self.assertIn("不提交", handle_dev_command("#n"))

    def test_backend_command(self):
        """ledger 0797: #backend 只读——报告固定 harness，opencode 退役。"""
        import os
        import pathlib
        import sys
        import tempfile

        root = pathlib.Path(__file__).resolve().parent.parent
        if str(root / "tools") not in sys.path:
            sys.path.insert(0, str(root / "tools"))
        import dev_runner as dr

        from backend.target_dev_bridge import handle_dev_command

        old = dr.BACKEND_FILE
        old_env = os.environ.pop("YHLZ_DEV_BACKEND", None)
        dr.BACKEND_FILE = pathlib.Path(tempfile.mkdtemp()) / "backend.txt"
        try:
            self.assertIn("harness", handle_dev_command("#backend"))
            self.assertIn("harness", handle_dev_command("#backend dsh"))
            self.assertEqual(dr._backend(), "dsh")
            self.assertIn("退役", handle_dev_command("#be opencode"))
            self.assertEqual(dr._backend(), "dsh")  # 不再被切走
        finally:
            dr.BACKEND_FILE = old
            if old_env is not None:
                os.environ["YHLZ_DEV_BACKEND"] = old_env


class DispatchGuardTest(unittest.TestCase):
    """2026-10-13 真机联测发现：元亨派单入口在"已有任务"时谎报"已开工"。

    `start_dev_task` 必须先看运行器状态；`answer_dev_task` 必须先确认真的有
    待答复任务。两条都用 stub 验证"不谎报、不误发"。
    """

    class _Stub:
        def __init__(self, status="idle", task="", text=""):
            self.state = {"status": status, "task": task, "text": text}
            self.started: list[str] = []
            self.answered: list[str] = []

        def _load(self):
            return dict(self.state)

        def start(self, task):
            self.started.append(task)
            self.state.update(status="running", task=task, text="")
            return dict(self.state)

        def answer(self, text):
            self.answered.append(text)
            self.state.update(status="running", text="")
            return dict(self.state)

    def setUp(self):
        from backend import target_dev_bridge as tdb

        self.tdb = tdb
        self._old = tdb._dev_runner
        self.addCleanup(lambda: setattr(tdb, "_dev_runner", self._old))
        self._notes: list[str] = []
        tdb._notify = self._notes.append

    def _use(self, stub):
        self.tdb._dev_runner = lambda: stub
        return stub

    def test_start_refused_while_running(self):
        stub = self._use(self._Stub(status="running", task="在跑的任务"))
        msg = self.tdb.start_dev_task("新任务")
        self.assertIn("已有任务在跑", msg)
        self.assertNotIn("已开工", msg)
        self.assertEqual(stub.started, [])

    def test_start_refused_while_awaiting(self):
        stub = self._use(self._Stub(status="awaiting", task="等答复的任务"))
        msg = self.tdb.start_dev_task("新任务")
        self.assertIn("待你答复", msg)
        self.assertEqual(stub.started, [])

    def test_start_accepted_when_idle(self):
        stub = self._use(self._Stub(status="done", task="上一个"))
        msg = self.tdb.start_dev_task("新任务")
        self.assertIn("已开工", msg)
        for _ in range(50):          # 异步线程：等它把 stub.start 调完
            if stub.started:
                break
            import time
            time.sleep(0.02)
        self.assertEqual(stub.started, ["新任务"])
        self.assertTrue(any("已开工" in n for n in self._notes))

    def test_start_reports_real_failure_async(self):
        class _Fail(self._Stub):
            def start(self, task):
                self.started.append(task)
                return {"status": "error", "text": "harness 网关不可用"}

        stub = self._use(_Fail(status="done"))
        self.tdb.start_dev_task("会失败的任务")
        for _ in range(50):
            if self._notes:
                break
            import time
            time.sleep(0.02)
        self.assertTrue(any("未开工" in n and "网关" in n for n in self._notes))

    def test_answer_refused_without_awaiting_task(self):
        stub = self._use(self._Stub(status="running", task="在跑"))
        msg = self.tdb.answer_dev_task("答复")
        self.assertIn("没有等待答复", msg)
        self.assertEqual(stub.answered, [])

    def test_answer_forwarded_when_awaiting(self):
        stub = self._use(self._Stub(status="awaiting", task="等答复"))
        msg = self.tdb.answer_dev_task("答复")
        self.assertIn("继续中", msg)
        for _ in range(50):
            if stub.answered:
                break
            import time
            time.sleep(0.02)
        self.assertEqual(stub.answered, ["答复"])


if __name__ == "__main__":
    unittest.main()
