"""Tests for group name -> id resolution used by qq.export."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.target_scheduler_tools import resolve_group_id  # noqa: E402

GROUPS = [
    {"group_id": "855372167", "group_name": "AI开发交流群（禁广告）"},
    {"group_id": "931057213", "group_name": "llm & agent party学习交流群~"},
    {"group_id": "681195563", "group_name": "Cortico开发基地"},
    {"group_id": "780788103", "group_name": "VanYo AI交流群禁广"},
    {"group_id": "1104213421", "group_name": "CGMiao学习交流群①"},
]


class ResolveTest(unittest.TestCase):
    def test_digit_passthrough(self):
        self.assertEqual(resolve_group_id("855372167", GROUPS), "matched:855372167")

    def test_name_fragment(self):
        self.assertEqual(resolve_group_id("AI开发", GROUPS), "matched:855372167")
        self.assertEqual(resolve_group_id("开发基地", GROUPS), "matched:681195563")
        self.assertEqual(resolve_group_id("Cortico", GROUPS), "matched:681195563")

    def test_english_mixed_token(self):
        self.assertEqual(resolve_group_id("llm agent", GROUPS), "matched:931057213")

    def test_ambiguous(self):
        r = resolve_group_id("AI交流", GROUPS)
        self.assertTrue(r.startswith("ambiguous:") or r.startswith("matched:"))
        if r.startswith("ambiguous:"):
            self.assertIn("780788103", r)

    def test_none_gives_hint(self):
        r = resolve_group_id("完全不存在群", GROUPS)
        self.assertTrue(r.startswith("none:"))

    def test_empty(self):
        self.assertTrue(resolve_group_id("", GROUPS).startswith("none"))


if __name__ == "__main__":
    unittest.main()
