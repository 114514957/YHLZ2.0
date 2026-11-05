"""Autonomy gate tests (ledger 1105): fail-closed unless explicitly enabled."""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import backend.target_daemon as td


class AutonomyGateTests(unittest.TestCase):
    def test_default_is_off(self):
        with patch.dict(os.environ, {"YHLZ_AUTONOMY_ENABLE": "",
                                     "YHLZ_AUTONOMY_DISABLED": ""}):
            self.assertTrue(td.autonomy_disabled())

    def test_enable_without_flag_turns_on(self):
        missing = pathlib.Path(tempfile.gettempdir()) / "no-such-autonomy.flag"
        with patch.dict(os.environ, {"YHLZ_AUTONOMY_ENABLE": "1",
                                     "YHLZ_AUTONOMY_DISABLED": ""}), \
                patch.object(td, "AUTONOMY_FLAG", missing):
            self.assertFalse(td.autonomy_disabled())

    def test_flag_still_kills(self):
        with tempfile.NamedTemporaryFile(suffix=".flag", delete=False) as fh:
            flag = pathlib.Path(fh.name)
        try:
            with patch.dict(os.environ, {"YHLZ_AUTONOMY_ENABLE": "1",
                                         "YHLZ_AUTONOMY_DISABLED": ""}), \
                    patch.object(td, "AUTONOMY_FLAG", flag):
                self.assertTrue(td.autonomy_disabled())
        finally:
            flag.unlink(missing_ok=True)

    def test_env_off_wins(self):
        with patch.dict(os.environ, {"YHLZ_AUTONOMY_ENABLE": "1",
                                     "YHLZ_AUTONOMY_DISABLED": "1"}):
            self.assertTrue(td.autonomy_disabled())


if __name__ == "__main__":
    unittest.main()
