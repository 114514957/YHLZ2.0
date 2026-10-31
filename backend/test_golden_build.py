"""真实语料标注入口测试（2026-09-24，台账 0500）。

`golden_build` 的"这条我要"链路（review → pick → 占比可见）此前存在但没人知道、
也没测试守着。这里只测确定性的纯函数与解析，不碰真实素材文件。
"""
import json
import tempfile
import unittest
from pathlib import Path

from tools import golden_build as gb


class FreshCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"user": "老爹问甲", "assistant": "答甲"},
            {"user": "老爹问乙", "assistant": "答乙"},
            {"user": "老爹问丙", "assistant": "答丙"},
        ]

    def test_all_fresh_when_nothing_picked(self):
        got = gb.fresh_candidates(self.rows, set())
        self.assertEqual([i for i, _ in got], [1, 2, 3])

    def test_picked_are_excluded(self):
        picked = {"老爹问甲"[:40]}
        got = gb.fresh_candidates(self.rows, picked)
        self.assertEqual([i for i, _ in got], [2, 3])

    def test_indices_stay_pickable(self):
        """编号必须仍是候选文件里的序号，否则 review 列出的号拿去 pick 会选错。"""
        rows = [{"user": f"q{i}"} for i in range(5)]  # q0..q4 -> 编号 1..5
        got = gb.fresh_candidates(rows, {"q2"})
        self.assertEqual([i for i, _ in got], [1, 2, 4, 5])


class CoverageSummaryTest(unittest.TestCase):
    def test_ratios_and_synthetic_remainder(self):
        st = {"tag": "v6", "total": 1000, "real": 38, "golden": 71,
              "scene": 500, "memory": 300, "extra": 91}
        c = gb.coverage_summary(st)
        self.assertEqual(c["total"], 1000)
        self.assertAlmostEqual(c["real_ratio"], 0.038)
        self.assertAlmostEqual(c["golden_ratio"], 0.071)
        self.assertEqual(c["synthetic"], 1000 - 38 - 71)

    def test_empty_stats_do_not_blow_up(self):
        c = gb.coverage_summary({})
        self.assertEqual(c["total"], 0)
        self.assertEqual(c["real_ratio"], 0.0)
        self.assertEqual(c["synthetic"], 0)

    def test_synthetic_never_negative(self):
        c = gb.coverage_summary({"total": 10, "real": 8, "golden": 7})
        self.assertGreaterEqual(c["synthetic"], 0)


class GoldenBlockRoundTripTest(unittest.TestCase):
    """pick 写出的块必须能被 load_golden 与装配器同口径解析回来。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "g.md"

    def test_pick_block_parses_back(self):
        self.path.write_text(
            "\n## golden-1\n- source: console\n- rating: \n- tags: \n"
            "- status: keep\n- note: \n### 老爹\n我怕冷\n### 元亨\n记下了。\n",
            encoding="utf-8")
        got = gb.load_golden(self.path)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["status"], "keep")
        self.assertEqual(got[0]["user"], "我怕冷")
        self.assertEqual(got[0]["assistant"], "记下了。")

    def test_drop_status_is_recognized(self):
        """老爹手改成 drop 的条目要在装配时被跳过（不然白标）。"""
        self.path.write_text(
            "## golden-2\n- status: 这条不要\n### 老爹\n甲\n### 元亨\n乙\n",
            encoding="utf-8")
        got = gb.load_golden(self.path)
        self.assertEqual(got[0]["status"], "drop")

    def test_broken_block_is_skipped_not_raised(self):
        self.path.write_text("## golden-3\n- status: keep\n### 老爹\n只有一轮\n",
                             encoding="utf-8")
        self.assertEqual(gb.load_golden(self.path), [])


class LatestStatsTest(unittest.TestCase):
    """coverage 读的是"最近一次装配"，不能挑错文件（否则占比数字是旧的）。"""

    def setUp(self):
        import tools.golden_build as mod

        self.mod = mod
        self.tmp = Path(tempfile.mkdtemp())
        self._old_root = mod.ROOT
        mod.ROOT = self.tmp

    def tearDown(self):
        self.mod.ROOT = self._old_root

    def _write(self, name: str, tag: str) -> Path:
        p = self.tmp / name
        p.write_text(json.dumps({"tag": tag, "total": 10}), encoding="utf-8")
        return p

    def test_picks_newest_by_mtime(self):
        import time

        self._write("sft_persona_v5.stats.json", "v5")
        time.sleep(0.02)
        self._write("sft_persona_v6.stats.json", "v6")
        self.assertEqual(self.mod._latest_stats()["tag"], "v6")

    def test_missing_files_return_empty(self):
        self.assertEqual(self.mod._latest_stats(), {})

    def test_corrupt_file_returns_empty_not_raise(self):
        (self.tmp / "sft_persona_vX.stats.json").write_text("{ broken",
                                                           encoding="utf-8")
        self.assertEqual(self.mod._latest_stats(), {})


if __name__ == "__main__":
    unittest.main()