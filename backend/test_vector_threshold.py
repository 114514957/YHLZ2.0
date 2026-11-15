"""W1 (ledger 1174): dynamic threshold selection — pure functions, no model."""
import os
import unittest
from unittest import mock

from backend import vector_memory as vm


class ThresholdTests(unittest.TestCase):
    def test_relative_sits_between_top_and_mean(self):
        scores = [0.70, 0.62, 0.55, 0.51, 0.44]
        cut = vm.pick_threshold(scores, method="relative")
        self.assertGreaterEqual(cut, 0.62 - 0.08 - 1e-9)   # top1 - 0.08
        self.assertLessEqual(cut, 0.95)

    def test_clamped_into_band(self):
        self.assertAlmostEqual(vm.pick_threshold([0.99, 0.98], method="relative"), 0.95)
        self.assertAlmostEqual(vm.pick_threshold([0.05, 0.04], method="relative"), 0.29)

    def test_floor_preserved(self):
        scores = [0.50, 0.49, 0.48]
        cut = vm.pick_threshold(scores, method="relative", floor=0.60)
        self.assertAlmostEqual(cut, 0.60)                  # floor wins over dynamic

    def test_fixed_returns_floor(self):
        self.assertAlmostEqual(vm.pick_threshold([0.9, 0.8], method="fixed", floor=0.42), 0.42)

    def test_percentile_is_distribution_based(self):
        cut = vm.pick_threshold([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2], method="percentile")
        self.assertAlmostEqual(cut, 0.725, places=3)       # numpy linear 75th percentile

    def test_select_hits_keeps_min_results(self):
        scored = [("a", 0.51), ("b", 0.50), ("c", 0.49)]
        with mock.patch.dict(os.environ, {"YHLZ_VEC_THRESHOLD": "fixed"}):
            hits = vm.select_hits(scored, top=8, min_score=0.99)
        self.assertEqual(len(hits), 3)                     # min_results wins over a silly cut

    def test_select_hits_respects_top(self):
        scored = [(str(i), 0.9 - i * 0.01) for i in range(30)]
        hits = vm.select_hits(scored, top=5, min_score=0.0)
        self.assertLessEqual(len(hits), 5)
        self.assertEqual(hits[0][0], "0")

    def test_select_hits_order_is_desc(self):
        scored = [("x", 0.3), ("y", 0.9)]
        with mock.patch.dict(os.environ, {"YHLZ_VEC_THRESHOLD": "fixed"}):
            hits = vm.select_hits(scored, top=2, min_score=0.0)
        self.assertEqual([h[0] for h in hits], ["y", "x"])


if __name__ == "__main__":
    unittest.main()
