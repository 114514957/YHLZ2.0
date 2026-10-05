"""T6 fake-provider 分支验证（ledger 0616）：验 daemon 各入口实际接的提供方。

- console（工作台）：**未注入** LLM，会话自建 **本地 8081 Gemma**；
- private / qq_g*：**注入** 默认工厂（DeepSeek 云，兜底 ollama）；
- 兜底：fallback_base_url = ollama 11434。
不触真实模型/网络；内存/索引以 Mock 隔离。
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, ".")

from backend.target_daemon import DaemonRuntime  # noqa: E402

_LOCAL = "http://127.0.0.1:8081/v1/chat/completions"
_OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"


class RouteBranchTest(unittest.TestCase):
    def _session(self, channel, calls):
        async def provider(messages, tools=None, **kw):
            return {"role": "assistant", "content": "fake"}

        def fake_builder(**kw):
            calls.append(kw)
            return provider

        with patch("backend.target_orchestrator.build_openai_compatible_llm_turn",
                   side_effect=fake_builder), \
             patch("backend.target_memory.TargetMemoryService", Mock()), \
             patch("backend.target_kw_index.KeywordIndex", Mock()):
            return DaemonRuntime._default_session(channel)

    def test_console_is_local_not_injected(self):
        calls = []
        s = self._session("console", calls)
        self.assertIs(getattr(s, "_llm_injected", None), False)
        self.assertTrue(any(c.get("base_url") == _LOCAL for c in calls),
                        "console 会话应以本地 8081 构建")

    def test_private_injected_cloud(self):
        calls = []
        s = self._session("private", calls)
        self.assertIs(getattr(s, "_llm_injected", None), True)
        self.assertFalse(any(c.get("base_url") == _LOCAL for c in calls),
                         "private 不应自建本地 8081（应为注入的默认工厂）")

    def test_group_injected_like_private(self):
        calls = []
        s = self._session("qq_g999", calls)
        self.assertIs(getattr(s, "_llm_injected", None), True)

    def test_default_fallback_is_ollama(self):
        calls = []
        self._session("private", calls)
        self.assertTrue(any(str(c.get("fallback_base_url") or "").startswith(
            "http://127.0.0.1:11434") for c in calls))


if __name__ == "__main__":
    unittest.main()
