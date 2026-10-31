"""A4 clone-engine routing tests (ledger 0454).

`_synth("clone", ...)` must use generate_voice_clone with the Edge reference;
anything else (0.6B / legacy keys) goes through generate_custom_voice.
No torch / model load involved (engine is faked).
"""
import os
import pathlib
import shutil
import tempfile
import unittest
import uuid
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
        base = pathlib.Path(os.environ.get("YHLZ_TEST_TMP") or tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        # 不用 mkdtemp：部分沙箱会把它建的目录当受保护临时目录，子进程写不进。
        self.tmp = base / f"clone_route_{uuid.uuid4().hex[:8]}"
        self.tmp.mkdir()
        (self.tmp / "ref01.wav").write_bytes(b"x")
        (self.tmp / "ref01.txt").write_text("参考文本", encoding="utf-8")
        bright = self.tmp / "bright"
        bright.mkdir()
        (bright / "ref01.wav").write_bytes(b"x")
        (bright / "ref01.txt").write_text("亮参考", encoding="utf-8")
        self.bright = bright
        # ledger 0846: 元亨本音 v2（02）成为默认嗓，情绪不再换嗓。
        yh = self.tmp / "yuanheng"
        yh.mkdir()
        (yh / "ref01.wav").write_bytes(b"x")
        (yh / "ref01.txt").write_text("元亨参考", encoding="utf-8")
        self._old_cfg = dict(cs.CLONE_CFG)
        self._old_voices = cs.CLONE_VOICES
        cs.CLONE_CFG = dict(cs.CLONE_CFG, ref_dir=self.tmp)
        cs.CLONE_VOICES = {
            "yuanheng": dict(cs.CLONE_CFG, ref_dir=yh, label="yuanheng"),
            "xiaoyi": dict(cs.CLONE_CFG, ref_dir=self.tmp),
            "bright": dict(cs.CLONE_CFG, ref_dir=bright, label="bright"),
        }

    def tearDown(self):
        cs._get_engine = self._old_engine
        cs.CLONE_CFG = self._old_cfg
        cs.CLONE_VOICES = self._old_voices
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clone_routes_to_voice_clone(self):
        audio, sr = cs._synth("clone", "你好", "Vivian")
        self.assertEqual(sr, 24000)
        self.assertEqual(audio, "b")
        kw = self.eng.clone.call_args.kwargs
        self.assertIn("ref01.wav", kw["ref_audio"])
        self.assertIn("bright", kw["ref_audio"])
        self.assertEqual(kw["ref_text"], "亮参考")
        self.assertFalse(self.eng.custom.called)

    def test_default_routes_to_custom_voice(self):
        cs._synth("0.6B", "你好", "Vivian")
        self.assertTrue(self.eng.custom.called)
        self.assertFalse(self.eng.clone.called)

    def test_emotion_picks_bright_voice(self):
        """ledger 0463/0829: happy lines use the designed bright voice."""
        import backend.emotion_classifier as ec

        old = ec.classify_emotion
        ec.classify_emotion = lambda t: {"emotion": "happy",
                                         "confidence": 1.0}
        try:
            cs._synth("clone", "哇哈哈哈，今天太开心了！", "Vivian")
        finally:
            ec.classify_emotion = old
        kw = self.eng.clone.call_args.kwargs
        self.assertIn("bright", kw["ref_audio"])
        self.assertEqual(kw["ref_text"], "亮参考")

    def test_explicit_voice_overrides_emotion(self):
        import backend.emotion_classifier as ec

        old = ec.classify_emotion
        ec.classify_emotion = lambda t: {"emotion": "happy",
                                         "confidence": 1.0}
        try:
            cs._synth("clone:xiaoyi", "太开心了", "Vivian")
        finally:
            ec.classify_emotion = old
        kw = self.eng.clone.call_args.kwargs
        self.assertNotIn("bright", kw["ref_audio"])
        self.assertEqual(kw["ref_text"], "参考文本")

    def test_legacy_key_falls_back_to_custom(self):
        cs._synth("1.7B", "你好")
        kw = self.eng.custom.call_args.kwargs
        self.assertEqual(kw["speaker"], "Vivian")
        self.assertFalse(self.eng.clone.called)


if __name__ == "__main__":
    unittest.main()
