"""Tests for snapshot/rollback (design v1 §2)."""
import tempfile
import unittest
from pathlib import Path

from backend import snapshots


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._dir = snapshots.SNAP_DIR
        self._targets = snapshots._targets
        snapshots.SNAP_DIR = self.tmp / "snaps"
        self.state = self.tmp / "state.txt"
        self.state.write_text("v1", encoding="utf-8")
        snapshots._targets = lambda: {"state": self.state}

    def tearDown(self):
        snapshots.SNAP_DIR = self._dir
        snapshots._targets = self._targets

    def test_create_and_restore(self):
        d = snapshots.create("before")
        self.assertTrue(Path(d).exists())
        snaps = snapshots.list_snapshots()
        self.assertEqual(len(snaps), 1)
        self.state.write_text("v2", encoding="utf-8")
        res = snapshots.restore(snaps[0]["ts"])
        self.assertTrue(res["ok"])
        self.assertIn("state", res["restored"])
        self.assertEqual(self.state.read_text(encoding="utf-8"), "v1")

    def test_restore_missing_ts(self):
        self.assertFalse(snapshots.restore("nope")["ok"])


if __name__ == "__main__":
    unittest.main()
