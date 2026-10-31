"""Tests for ChannelAuth (Step 1: daemon channel identity)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.channel_auth import ChannelAuthError, is_owner_channel, validate_channel


class TestValidateChannel(unittest.TestCase):
    def test_console_source(self):
        self.assertEqual(validate_channel("console", "console"), "console")
        self.assertEqual(validate_channel("console", "private"), "console")
        self.assertEqual(validate_channel("console", "default"), "console")

    def test_console_rejects_group(self):
        with self.assertRaisesRegex(ChannelAuthError, "CONSOLE-CHANNEL"):
            validate_channel("console", "qq_g1094579571")

    def test_qq_bridge_owner(self):
        self.assertEqual(validate_channel("qq_bridge", "qq_p2258374446"), "qq_p2258374446")

    def test_qq_bridge_group(self):
        self.assertEqual(validate_channel("qq_bridge", "qq_g1094579571"), "qq_g1094579571")

    def test_qq_bridge_rejects_console(self):
        with self.assertRaisesRegex(ChannelAuthError, "BAD-QQ-CHANNEL"):
            validate_channel("qq_bridge", "console")

    def test_public_source(self):
        self.assertEqual(validate_channel("public", "public"), "public")

    def test_public_rejects_owner(self):
        with self.assertRaisesRegex(ChannelAuthError, "PUBLIC-CHANNEL"):
            validate_channel("public", "qq_p2258374446")

    def test_unknown_source_rejected(self):
        with self.assertRaisesRegex(ChannelAuthError, "UNKNOWN-SOURCE"):
            validate_channel("hacker", "qq_p2258374446")

    def test_empty_source_rejected(self):
        with self.assertRaisesRegex(ChannelAuthError, "UNKNOWN-SOURCE"):
            validate_channel("", "console")

    def test_spoofed_owner_from_group(self):
        """Group trying to impersonate owner via qq_bridge must be rejected
        if the channel is malformed."""
        with self.assertRaisesRegex(ChannelAuthError, "BAD-QQ-CHANNEL"):
            validate_channel("qq_bridge", "qq_p2258")  # too short


class TestIsOwnerChannel(unittest.TestCase):
    def test_console(self):
        self.assertTrue(is_owner_channel("console"))

    def test_qq_p(self):
        self.assertTrue(is_owner_channel("qq_p2258374446"))
        self.assertFalse(is_owner_channel("qq_p123456789"))

    def test_qq_g(self):
        self.assertFalse(is_owner_channel("qq_g1094579571"))

    def test_public(self):
        self.assertFalse(is_owner_channel("public"))

    def test_private(self):
        self.assertFalse(is_owner_channel("private"))  # private=console alias
        self.assertTrue(is_owner_channel("console"))


if __name__ == "__main__":
    unittest.main()
