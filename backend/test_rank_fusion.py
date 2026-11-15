"""W2 (ledger 1174): reciprocal rank fusion — pure functions."""
import os
import unittest
from unittest import mock

from backend import rank_fusion as rf


class RrfTests(unittest.TestCase):
    def test_multi_channel_boost(self):
        fused = dict(rf.rrf([["a", "b"], ["b", "c"]]))
        # b appears in both lists -> beats a and c
        self.assertGreater(fused["b"], fused["a"])
        self.assertGreater(fused["b"], fused["c"])

    def test_rank_one_wins_within_channel(self):
        fused = dict(rf.rrf([["a", "b", "c"]]))
        self.assertGreater(fused["a"], fused["b"])
        self.assertGreater(fused["b"], fused["c"])

    def test_weights_zero_ignores_channel(self):
        with_channel = dict(rf.rrf([["a"], ["b"]], weights=[1.0, 0.0]))
        self.assertIn("a", with_channel)
        self.assertNotIn("b", with_channel)

    def test_duplicate_ids_inside_one_list_count_once(self):
        once = dict(rf.rrf([["a", "b"]]))
        twice = dict(rf.rrf([["a", "a", "b"]]))
        self.assertAlmostEqual(once["a"], twice["a"])

    def test_k_changes_steepness(self):
        small = dict(rf.rrf([["a", "b"]], k=1))
        large = dict(rf.rrf([["a", "b"]], k=1000))
        self.assertGreater(small["a"] / small["b"], large["a"] / large["b"])

    def test_fuse_reads_weights_env(self):
        with mock.patch.dict(os.environ, {"YHLZ_RRF_WEIGHTS": "vector:2,lexical:1"}):
            fused = rf.fuse({"vector": ["a"], "lexical": ["b"]})
        self.assertGreater(fused["a"], fused["b"])

    def test_enabled_switch(self):
        with mock.patch.dict(os.environ, {"YHLZ_RRF": "off"}):
            self.assertFalse(rf.enabled())
        with mock.patch.dict(os.environ, {"YHLZ_RRF": "on"}):
            self.assertTrue(rf.enabled())

    def test_fuse_empty(self):
        self.assertEqual(rf.fuse({}), {})


if __name__ == "__main__":
    unittest.main()
