"""A4 clone-engine routing tests (ledger 0454).

`_synth("clone", ...)` must use generate_voice_clone with the Edge reference;
anything else (0.6B / legacy keys) goes through generate_custom_voice.
No torch / model load involved (engine is faked).
"""
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock

import backend.console_server as cs


class _FakeEngine:
    def __init__(self):
        self.custom = MagicMock(return_value=(["a"], 24000))
        self.clone = MagicMock(return_value=(["b"], 24000))

    def generate_custom_voice(self, **kw):
        return self.custom(**kw)

    def generate_voice_clone(self, **kw):
        return self.clone(**kw)


class CloneRouteTest(unittest.TestCase):
    def setUp(self):
        self.eng = _FakeEngine()
        self._old_engine = cs._get_engine
        cs._get_engine = lambda which: self.eng
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "ref01.wav").write_bytes(b"x")
        (self.tmp / "ref01.txt").write_text("参考文本", encoding="utf-8")
        self._old_cfg = dict(cs.CLONE_CFG)
        cs.CLONE_CFG = dict(cs.CLONE_CFG, ref_dir=self.tmp)

    def tearDown(self):
        cs._get_engine = self._old_engine
        cs.CLONE_CFG = self._old_cfg

    def test_clone_routes_to_voice_clone(self):
        audio, sr = cs._synth("clone", "你好", "Vivian")
        self.assertEqual(sr, 24000)
        self.assertEqual(audio, "b")
        kw = self.eng.clone.call_args.kwargs
        self.assertIn("ref01.wav", kw["ref_audio"])
        self.assertEqual(kw["ref_text"], "参考文本")
        self.assertFalse(self.eng.custom.called)

    def test_default_routes_to_custom_voice(self):
        cs._synth("0.6B", "你好", "Vivian")
        self.assertTrue(self.eng.custom.called)
        self.assertFalse(self.eng.clone.called)

    def test_legacy_key_falls_back_to_custom(self):
        cs._synth("1.7B", "你好")
        kw = self.eng.custom.call_args.kwargs
        self.assertEqual(kw["speaker"], "Vivian")
        self.assertFalse(self.eng.clone.called)


if __name__ == "__main__":
    unittest.main()
