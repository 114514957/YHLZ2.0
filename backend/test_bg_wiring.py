"""T5 接线"防花瓶"测试（ledger 0614）：证明后台 caller 真的经统一入口。

- 反射/社区/QQ抽取的 `_local_llm()/build_llm_turn()` 返回的 provider 必须
  在 bg_scheduler 计数里出现（kind 正确）——否则接线是花瓶。
- 包装器失败（timeout/skip）必须**抛错**，绝不静默返回空结果冒充成功。
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, ".")

import backend.bg_scheduler as bg  # noqa: E402
import backend.communities as comm  # noqa: E402
import backend.qqextract as qe  # noqa: E402
import backend.reflection as refl  # noqa: E402


async def _fake_provider(messages, tools=None, **kw):
    return {"role": "assistant", "content": "ok"}


class WiringTest(unittest.TestCase):
    def setUp(self):
        bg.reset_for_tests()
        refl._LLM = None
        comm._LLM = None

    def test_reflection_routes_through_scheduler(self):
        with patch("backend.target_orchestrator.build_openai_compatible_llm_turn",
                   return_value=_fake_provider):
            llm = refl._local_llm()
        out = asyncio.run(llm([{"role": "user", "content": "x"}], None))
        self.assertEqual(out["content"], "ok")
        s = bg.status()
        self.assertEqual(s["counters"]["done"], 1)
        self.assertEqual(s["recent"][-1]["kind"], "reflection")
        self.assertEqual(s["recent"][-1]["endpoint"], "8081")

    def test_communities_routes_through_scheduler(self):
        with patch("backend.target_orchestrator.build_openai_compatible_llm_turn",
                   return_value=_fake_provider):
            llm = comm._local_llm()
        asyncio.run(llm([{"role": "user", "content": "x"}], None))
        s = bg.status()
        self.assertEqual(s["counters"]["done"], 1)
        self.assertEqual(s["recent"][-1]["kind"], "communities")

    def test_qqextract_routes_through_scheduler(self):
        with patch("backend.target_orchestrator.build_openai_compatible_llm_turn",
                   return_value=_fake_provider):
            llm = qe.build_llm_turn()
        asyncio.run(llm([{"role": "user", "content": "x"}], None))
        s = bg.status()
        self.assertEqual(s["counters"]["done"], 1)
        self.assertEqual(s["recent"][-1]["kind"], "qqextract")

    def test_wrapper_failure_surfaces_not_silent(self):
        async def slow(messages, tools=None, **kw):
            await asyncio.sleep(5)
            return {"content": "late"}

        wrapped = bg.wrap_llm_turn(slow, kind="t", timeout_s=0.05)
        with self.assertRaises(RuntimeError):
            asyncio.run(wrapped([], None))
        self.assertEqual(bg.status()["counters"]["timeout"], 1)

    def test_wrapper_policy_skip_raises(self):
        wrapped = bg.wrap_llm_turn(_fake_provider, kind="t", policy_check=lambda: False)
        with self.assertRaises(RuntimeError):
            asyncio.run(wrapped([], None))
        self.assertEqual(bg.status()["counters"]["skipped_policy"], 1)

    def test_session_turn_marks_foreground(self):
        """真实前台接线：会话 turn 必须调 foreground_enter/exit（非花瓶）。"""
        from unittest.mock import Mock

        import backend.target_entry as te_mod

        async def provider(messages, tools=None, **kw):
            return {"role": "assistant", "content": "ok"}

        with patch("backend.target_memory.TargetMemoryService", Mock()), \
             patch("backend.target_kw_index.KeywordIndex", Mock()):
            s = te_mod.ConversationSession(llm_turn=provider, memory=Mock(),
                                           channel="console")
        try:
            asyncio.run(s.run_turn("在吗？"))
        except Exception:  # noqa: BLE001 — 接线验证：异常也要 exit
            pass
        st = bg.status()
        self.assertGreaterEqual(st["fg_entered"], 1)
        self.assertEqual(st["foreground_active"], 0)  # 进出平衡


if __name__ == "__main__":
    unittest.main()
