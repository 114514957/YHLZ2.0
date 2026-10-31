"""Vector-side policy (P0, 2026-10-22): mode switch, warm-up gate, rerank gate.

Owner decision: semantic stays OFF by default; ``auto`` enables only after the
background warm-up succeeded; the cross-encoder is out of the recall path.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import memory_resource_policy as mrp
from backend.target_memory import _rerank_in_recall_enabled
from backend.vector_memory import l2_scope


class SemanticModeTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertEqual(mrp.semantic_mode({}), "off")
        self.assertFalse(mrp.semantic_model_allowed({}))

    def test_legacy_cpu_means_on(self):
        env = {"YHLZ_MEMORY_SEMANTIC_MODE": "cpu"}
        self.assertEqual(mrp.semantic_mode(env), "on")
        self.assertTrue(mrp.semantic_model_allowed(env))

    def test_auto_waits_for_warmup(self):
        env = {"YHLZ_MEMORY_SEMANTIC_MODE": "auto"}
        self.assertEqual(mrp.semantic_mode(env), "auto")
        with patch("backend.vector_memory.semantic_ready", return_value=False):
            self.assertFalse(mrp.semantic_model_allowed(env))
        with patch("backend.vector_memory.semantic_ready", return_value=True):
            self.assertTrue(mrp.semantic_model_allowed(env))

    def test_training_marker_wins(self):
        env = {"YHLZ_MEMORY_SEMANTIC_MODE": "on", "YHLZ_TRAINING_ACTIVE": "1"}
        self.assertEqual(mrp.semantic_mode(env), "off")
        env = {"YHLZ_MEMORY_SEMANTIC_MODE": "on", "YHLZ_FINETUNE_ACTIVE": "true"}
        self.assertFalse(mrp.semantic_model_allowed(env))

    def test_disabled_aliases(self):
        for raw in ("disabled", "off", "0", "", "no"):
            self.assertEqual(
                mrp.semantic_mode({"YHLZ_MEMORY_SEMANTIC_MODE": raw}), "off", raw)


class RerankGateTests(unittest.TestCase):
    def test_off_by_default(self):
        old = os.environ.pop("YH_RERANK_IN_RECALL", None)
        try:
            self.assertFalse(_rerank_in_recall_enabled())
        finally:
            if old is not None:
                os.environ["YH_RERANK_IN_RECALL"] = old

    def test_experiment_flag(self):
        with patch.dict(os.environ, {"YH_RERANK_IN_RECALL": "1"}):
            self.assertTrue(_rerank_in_recall_enabled())


class VectorScopeTests(unittest.TestCase):
    def test_main_db_stays_l2(self):
        self.assertEqual(l2_scope(), "l2")

    def test_other_db_gets_own_scope(self):
        other = Path("cache/memstore/qq_group.db")
        scoped = l2_scope(other)
        self.assertNotEqual(scoped, "l2")
        self.assertTrue(scoped.startswith("l2@"))


class SummaryOnlyPolicyTests(unittest.TestCase):
    """L1 compression may be enabled alone: local model, no per-token cost."""

    def test_default_is_off(self):
        p = mrp.load_memory_resource_policy({})
        self.assertFalse(p.summary_enabled)
        self.assertFalse(p.llm_enabled)

    def test_summary_only_does_not_enable_full_memory_llm(self):
        p = mrp.load_memory_resource_policy({"YHLZ_MEMORY_SUMMARY_MODE": "local"})
        self.assertTrue(p.summary_enabled)
        self.assertFalse(p.llm_enabled)

    def test_training_marker_blocks_summary(self):
        p = mrp.load_memory_resource_policy({
            "YHLZ_MEMORY_SUMMARY_MODE": "local",
            "YHLZ_TRAINING_ACTIVE": "1",
        })
        self.assertFalse(p.summary_enabled)

    def test_summary_only_hooks_defer_adjudication(self):
        import asyncio

        class Inner:
            async def compress(self, dropped, prev=""):
                return ("s", 1)

        hooks = mrp.SummaryOnlyHooks(Inner())
        self.assertEqual(asyncio.run(hooks.compress([{"role": "user", "text": "x"}])),
                         ("s", 1))
        self.assertEqual(asyncio.run(hooks.candidates({})), [])
        with self.assertRaises(mrp.MemoryWorkDeferred):
            asyncio.run(hooks.adjudicate({"id": "x"}))

    def test_scheduler_accepts_summary_only_mode(self):
        from backend import memory_summary_scheduler as sched

        old = {k: os.environ.pop(k, None) for k in
               ("YHLZ_MEMORY_LLM_MODE", "YHLZ_MEMORY_SUMMARY_MODE", "YHLZ_TRAINING_ACTIVE")}
        try:
            self.assertFalse(sched._model_allowed())
            os.environ["YHLZ_MEMORY_SUMMARY_MODE"] = "local"
            self.assertTrue(sched._model_allowed())
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
