"""Unit tests for hybrid LLM composition helpers."""

from __future__ import annotations

import unittest

from backend.llm_hybrid_compose import (
    API_BASE_URL,
    API_MODEL,
    LOCAL_BASE_URL,
    LOCAL_MODEL,
    create_hybrid_llm_provider,
    create_hybrid_reasoner,
)
from backend.llm_reasoner import SYSTEM_PROMPT, LLMReasoner
from backend.llm_vllm_provider import LlmVllmProvider


class HybridComposeTests(unittest.TestCase):
    def test_create_hybrid_llm_provider_wires_defaults(self) -> None:
        hybrid = create_hybrid_llm_provider(api_key="sk-test")
        self.assertIsInstance(hybrid.primary, LlmVllmProvider)
        self.assertIsInstance(hybrid.backup, LlmVllmProvider)
        self.assertEqual(hybrid.primary.base_url, API_BASE_URL)
        self.assertEqual(hybrid.primary.model, API_MODEL)
        self.assertEqual(hybrid.backup.base_url, LOCAL_BASE_URL)
        self.assertEqual(hybrid.backup.model, LOCAL_MODEL)
        self.assertEqual(hybrid.primary.api_key, "sk-test")

    def test_create_hybrid_reasoner_binds_reasoner(self) -> None:
        reasoner = create_hybrid_reasoner(system_prompt="定制模板")
        self.assertIsInstance(reasoner, LLMReasoner)
        self.assertEqual(reasoner.system_prompt, "定制模板")
        self.assertIsInstance(reasoner.provider, type(create_hybrid_llm_provider(api_key="x")))

    def test_default_template_is_production(self) -> None:
        self.assertEqual(SYSTEM_PROMPT, "先进始于计算，元亨开拓未来")


if __name__ == "__main__":
    unittest.main()
