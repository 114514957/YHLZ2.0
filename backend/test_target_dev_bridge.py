"""Dev hand-off + single-lane dispatch adapter tests (0831)."""
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
        self.assertIn("未知指令", handle_dev_command("#bakend"))

    def test_backend_command(self):
        """ledger 0797/0831: #backend 只读——固定 harness，opencode 退役。"""
        from backend.target_dev_bridge import handle_dev_command

        self.assertIn("harness", handle_dev_command("#backend"))
        self.assertIn("harness", handle_dev_command("#backend dsh"))
        self.assertIn("退役", handle_dev_command("#be opencode"))


class _StubRunner:
    """Lite job runner stub (same API surface as tools/qq_dev_runner.py)."""

    def __init__(self):
        self.started: list[tuple] = []
        self.answered: list[tuple] = []
        self.awaiting: dict | None = None
        self.start_result = {"status": "accepted", "job_id": "job1",
                             "text": "[利贞] 已开工：新任务"}
        self.resolve = None

    def start(self, task, *, owner, channel):
        self.started.append((task, owner, channel))
        return dict(self.start_result)

    def awaiting_job(self, owner, channel):
        return self.awaiting

    def answer(self, text, *, owner, channel, job_id=None):
        if not self.awaiting:
            return {"status": "error", "text": "没有等待答复的开发任务"}
        self.answered.append((text, channel, job_id))
        return {"status": "accepted", "text": "[利贞] 收到答复，继续…"}

    def status_text(self):
        return "[利贞] 状态=idle"

    def resolve_job(self, _job_id=None):
        return self.resolve

    def backend_status(self):
        return "[利贞] 当前后端：harness（dsh）"

    def set_backend(self, arg):
        return "[利贞] 后端固定 harness（dsh），opencode 已退役。"


class DispatchGuardTest(unittest.TestCase):
    """不谎报开工；答复只在真有等待任务时转发（0831 改走 Lite job 库）。"""

    def setUp(self):
        from backend import target_dev_bridge as tdb

        self.tdb = tdb
        self._old_runner = tdb._runner
        self._old_notify = tdb._notify
        self.addCleanup(lambda: setattr(tdb, "_runner", self._old_runner))
        self.addCleanup(lambda: setattr(tdb, "_notify", self._old_notify))
        self._notes: list[str] = []
        tdb._notify = self._notes.append
        self.stub = _StubRunner()
        tdb._runner = lambda: self.stub

    def test_start_busy_does_not_claim_success(self):
        self.stub.start_result = {
            "status": "busy", "job_id": "job9",
            "text": "[利贞] 已有任务 job9 状态=running，先处理或 #cancel <job_id>"}
        msg = self.tdb.start_dev_task("新任务")
        self.assertIn("已有任务", msg)
        self.assertNotIn("已开工", msg)
        self.assertEqual(self._notes, [])

    def test_start_accepted_notifies(self):
        msg = self.tdb.start_dev_task("新任务")
        self.assertIn("已开工", msg)
        self.assertEqual(self.stub.started[0][0], "新任务")
        self.assertTrue(any("已开工" in n for n in self._notes))

    def test_start_error_is_reported(self):
        self.stub.start_result = {"status": "error",
                                  "text": "[利贞] 工作树创建失败：fatal"}
        msg = self.tdb.start_dev_task("会失败的任务")
        self.assertIn("失败", msg)

    def test_answer_refused_without_awaiting_task(self):
        msg = self.tdb.answer_dev_task("答复")
        self.assertIn("没有等待答复", msg)
        self.assertEqual(self.stub.answered, [])

    def test_answer_forwarded_when_awaiting(self):
        from backend.target_dev_bridge import maybe_answer_pending

        self.stub.awaiting = {"job_id": "job7", "state": "awaiting_owner"}
        msg = maybe_answer_pending("答复", channel="console")
        self.assertIn("继续", msg)
        self.assertEqual(self.stub.answered, [("答复", "console", "job7")])

    def test_hash_command_is_not_a_plain_answer(self):
        from backend.target_dev_bridge import maybe_answer_pending

        self.stub.awaiting = {"job_id": "job7", "state": "awaiting_owner"}
        self.assertIsNone(maybe_answer_pending("#devstatus", channel="console"))
        self.assertEqual(self.stub.answered, [])

    def test_dev_status_maps_job_state(self):
        self.stub.resolve = {"job_id": "job3", "state": "awaiting_owner",
                             "task": "修复登录"}
        self.assertEqual(self.tdb.dev_status(),
                         {"status": "awaiting", "task": "修复登录",
                          "job_id": "job3"})


if __name__ == "__main__":
    unittest.main()
