"""F2 spawn throttle tests (ledger 0436)."""
import pathlib
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))


class SpawnGuardTest(unittest.TestCase):
    def test_throttle_is_per_key(self):
        import yhlz_launcher as yl

        tmp = pathlib.Path(tempfile.mkdtemp())
        old = yl.SPAWN_GUARD
        yl.SPAWN_GUARD = tmp / "guard.json"
        try:
            self.assertTrue(yl._spawn_allowed("daemon", 120))
            self.assertFalse(yl._spawn_allowed("daemon", 120))
            self.assertTrue(yl._spawn_allowed("llama", 120))
            self.assertTrue(yl._spawn_allowed("daemon", 0))
        finally:
            yl.SPAWN_GUARD = old


if __name__ == "__main__":
    unittest.main()
