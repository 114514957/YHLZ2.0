"""Prompts module tests (ledger 0144 baseline)."""

import unittest

from backend.target_prompts import (
    ANCHOR,
    ANTI_HALLUCINATION,
    MEMORY_L1_COMPRESS_PROMPT,
    MEMORY_L2_CANDIDATE_PROMPT,
    MEMORY_L2_JUDGE_PROMPT,
    PERSONA_FIVE_DIM,
    PROMPTS_VERSION,
    render_capabilities_tools_block,
    render_system_prompt,
)


class TestPromptsBaseline(unittest.TestCase):
    def test_anchor_present(self):
        self.assertIn("先进始于计算，元亨开拓未来", ANCHOR)

    def test_five_dim_complete(self):
        self.assertEqual(len(PERSONA_FIVE_DIM), 5)
        for dim in PERSONA_FIVE_DIM:
            self.assertTrue(dim.startswith(("开放", "尽责", "生动", "协作", "稳定")))

    def test_no_fixed_tone_constraints(self):
        text = render_system_prompt()
        self.assertNotIn("兄弟腔", text)
        self.assertNotIn("铁哥们", text)
        self.assertNotIn("口头禅", text)

    def test_anti_hallucination_clause_present(self):
        text = render_system_prompt()
        self.assertIn("不得声称", text)
        self.assertIn(ANTI_HALLUCINATION[:20], text)

    def test_tools_block_rendered(self):
        tools = [
            {"function": {"name": "ledger_search", "description": "查台账"}},
            {"function": {"name": "system_time", "description": "查时间"}},
        ]
        block = render_capabilities_tools_block(tools)
        self.assertIn("ledger_search", block)
        self.assertIn("system_time", block)
        text = render_system_prompt(tools=tools)
        self.assertIn("你可以调用以下工具", text)

    def test_no_tools_block_when_empty(self):
        text = render_system_prompt(tools=None)
        self.assertNotIn("你可以调用以下工具", text)

    def test_version_stable(self):
        self.assertEqual(PROMPTS_VERSION, "zh-1.0")

    def test_memory_templates_constraints(self):
        self.assertIn("只输出摘要", MEMORY_L1_COMPRESS_PROMPT)
        self.assertIn("只输出 JSON 数组", MEMORY_L2_CANDIDATE_PROMPT)
        self.assertIn("importance", MEMORY_L2_CANDIDATE_PROMPT)
        self.assertIn("绝不删除", MEMORY_L2_JUDGE_PROMPT)
        self.assertIn("active|downgraded|cold|archive", MEMORY_L2_JUDGE_PROMPT)


if __name__ == "__main__":
    unittest.main()
