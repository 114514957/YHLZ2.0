"""Tests for backend.prompt_budget (F-08, ledger 1104)."""
from __future__ import annotations

import unittest

from backend.prompt_budget import estimate_tokens, fit_messages, total_tokens


def _m(role: str, text: str) -> dict:
    return {"role": role, "content": text}


class PromptBudgetTests(unittest.TestCase):
    def test_estimate_cjk_heavier_than_ascii(self):
        self.assertGreater(estimate_tokens("元" * 100), estimate_tokens("a" * 100))

    def test_under_budget_is_noop(self):
        msgs = [_m("system", "sys"), _m("user", "hi")]
        out, stats = fit_messages(msgs, 1000)
        self.assertEqual(out, msgs)
        self.assertEqual(stats["dropped_messages"], 0)
        self.assertFalse(stats["truncated"])

    def test_drops_oldest_and_keeps_newest(self):
        msgs = [
            _m("system", "S" * 100),
            _m("user", "旧" * 400),
            _m("assistant", "旧" * 400),
            _m("user", "新" * 10),
        ]
        out, stats = fit_messages(msgs, 300)
        self.assertLessEqual(total_tokens(out), 300)
        self.assertEqual(out[-1]["content"], "新" * 10)
        self.assertEqual(out[0]["content"], "S" * 100)
        self.assertGreater(stats["dropped_messages"], 0)

    def test_truncates_when_single_message_over_budget(self):
        msgs = [_m("user", "长" * 5000)]
        out, stats = fit_messages(msgs, 500)
        self.assertTrue(stats["truncated"])
        self.assertLessEqual(total_tokens(out), 510)
        self.assertTrue(out[0]["content"].endswith("已截断）"))

    def test_multimodal_parts_counted_and_image_kept(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "x" * 900},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]}]
        out, stats = fit_messages(msgs, 100)
        self.assertTrue(stats["truncated"])
        self.assertLessEqual(total_tokens(out), 110)
        self.assertTrue(any(
            isinstance(p, dict) and p.get("type") == "image_url"
            for p in out[0]["content"]))

    def test_empty_messages(self):
        out, stats = fit_messages([], 100)
        self.assertEqual(out, [])
        self.assertEqual(stats["fitted_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
