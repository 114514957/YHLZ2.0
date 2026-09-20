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
        """A1 gray switch (ledger 0450): #backend status/switch via dev console."""
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
            self.assertIn("opencode", handle_dev_command("#backend"))
            self.assertIn("dsh", handle_dev_command("#backend dsh"))
            self.assertEqual(dr._backend(), "dsh")
            self.assertIn("opencode", handle_dev_command("#be opencode"))
            self.assertEqual(dr._backend(), "opencode")
        finally:
            dr.BACKEND_FILE = old
            if old_env is not None:
                os.environ["YHLZ_DEV_BACKEND"] = old_env


if __name__ == "__main__":
    unittest.main()
