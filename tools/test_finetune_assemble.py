"""R1(0652) 装配器角色映射修复的最小回归。

运行：.venv\\Scripts\\python.exe -B -m unittest tools.test_finetune_assemble -v
"""
import unittest

from tools import finetune_assemble as fa


class ToMessagesTest(unittest.TestCase):
    def test_lizhen_kept_as_user(self):
        msgs = fa._to_messages([("利贞", "问", "她记的是啥"), ("元亨", "答", "记好了")])
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant"])
        self.assertEqual(msgs[1]["content"], "利贞：她记的是啥")

    def test_no_adjacent_assistant_with_lizhen_between(self):
        msgs = fa._to_messages([
            ("元亨", "答", "B1"), ("利贞", "问", "Q2"), ("元亨", "答", "B2")])
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "assistant", "user", "assistant"])
        for a, b in zip(roles, roles[1:]):
            self.assertFalse(a == "assistant" and b == "assistant")

    def test_true_double_yuanheng_merged(self):
        msgs = fa._to_messages([("元亨", "答", "B1"), ("元亨", "答", "B2")])
        self.assertEqual([m["role"] for m in msgs], ["system", "assistant"])
        self.assertEqual(msgs[1]["content"], "B1\nB2")

    def test_unknown_speaker_kept(self):
        msgs = fa._to_messages([("群友甲", "说", "你好"), ("元亨", "答", "嗨")])
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "群友甲：你好")

    def test_requires_assistant(self):
        self.assertIsNone(fa._to_messages([("老爹", "问", "在吗")]))

    def test_fiction_frame_injected(self):
        msgs = fa._to_messages([("元亨", "答", "咱今天去河边了")], fiction=True)
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant"])
        self.assertEqual(msgs[1]["content"], "（虚构小剧场）")
        msgs2 = fa._to_messages([("老爹", "问", "在吗"), ("元亨", "答", "在")], fiction=True)
        self.assertTrue(msgs2[1]["content"].startswith("（虚构小剧场）"))
        self.assertEqual([m["role"] for m in msgs2], ["system", "user", "assistant"])


class RepairRepeatTest(unittest.TestCase):
    def test_repair(self):
        seg = "这是一段足够长的重复文本内容0123456789"
        text = "开头" + seg + seg + "结尾"
        out, changed = fa._repair_repeat(text)
        self.assertTrue(changed)
        self.assertEqual(out.count(seg), 1)

    def test_no_false_positive(self):
        out, changed = fa._repair_repeat("没有重复的普通文本，正常内容。")
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
