"""
M0.4 端点 smoke test: 验证 main.py 中新增的 /personality/voice-identity 路由已注册

策略: mock 掉重量级引擎模块 (asr/tts/llm/vad/audio_buffer 等) 后 import main,
检查 FastAPI app.routes 是否含新路径, 并验证 Pydantic 模型字段。

运行: venv\Scripts\python.exe 对话DEMO\test_m04_endpoints_smoke.py
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# mock 掉重量级引擎模块, 防止 import main 时触发模型加载
_HEAVY_MODS = [
    "backend.asr_engine",
    "backend.tts_engine",
    "backend.llm_engine",
    "backend.vad_engine",
    "backend.audio_buffer",
    "backend.conversation_manager",
    "backend.sync_manager",
    "backend.emotion_classifier",
    "sounddevice",
]
for mod in _HEAVY_MODS:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


class TestEndpointRegistration(unittest.TestCase):
    """M0.4 新增端点路由注册验证"""

    @classmethod
    def setUpClass(cls):
        # import main 后, app 已构造, 路由已注册
        from backend import main as main_module
        cls.main = main_module
        cls.app = main_module.app

    def _get_paths(self):
        return {route.path for route in self.app.routes if hasattr(route, "path")}

    def test_get_personality_voice_identity_route_registered(self):
        self.assertIn("/personality/voice-identity", self._get_paths())

    def test_post_personality_voice_identity_route_registered(self):
        # 同一路径 GET/POST 共享 path, 只检查路径存在
        paths = self._get_paths()
        self.assertIn("/personality/voice-identity", paths)

    def test_personality_route_still_present(self):
        """旧 /personality 端点保留 (兼容性)"""
        paths = self._get_paths()
        self.assertIn("/personality", paths)
        self.assertIn("/personality/reset", paths)


class TestPydanticModels(unittest.TestCase):
    """M0.4 Pydantic 模型字段验证"""

    @classmethod
    def setUpClass(cls):
        from backend import main as main_module
        cls.main = main_module

    def test_personality_update_has_voice_identity_field(self):
        """PersonalityUpdate 含 voice_identity 可选字段"""
        fields = self.main.PersonalityUpdate.model_fields
        self.assertIn("voice_identity", fields)
        # 默认 None (可选)
        update = self.main.PersonalityUpdate()
        self.assertIsNone(update.voice_identity)

    def test_personality_update_accepts_voice_identity_dict(self):
        """PersonalityUpdate 接受 voice_identity dict"""
        update = self.main.PersonalityUpdate(voice_identity={"voice_id": "v1", "engine": "qwen3"})
        self.assertEqual(update.voice_identity, {"voice_id": "v1", "engine": "qwen3"})

    def test_voice_identity_update_model_fields(self):
        """VoiceIdentityUpdate 含 voice_id + engine 两个可选字段"""
        fields = self.main.VoiceIdentityUpdate.model_fields
        self.assertIn("voice_id", fields)
        self.assertIn("engine", fields)
        # 默认 None
        m = self.main.VoiceIdentityUpdate()
        self.assertIsNone(m.voice_id)
        self.assertIsNone(m.engine)

    def test_voice_identity_update_exclude_none(self):
        """VoiceIdentityUpdate.dict(exclude_none=True) 只含传入字段"""
        m = self.main.VoiceIdentityUpdate(voice_id="clone_v1")
        d = m.dict(exclude_none=True)
        self.assertEqual(d, {"voice_id": "clone_v1"})
        # 不含 engine
        self.assertNotIn("engine", d)

    def test_voice_identity_update_both_none_yields_empty_dict(self):
        """两个都 None → 空 dict (端点会拒绝)"""
        m = self.main.VoiceIdentityUpdate()
        d = m.dict(exclude_none=True)
        self.assertEqual(d, {})


class TestContextManagerIntegrationWithMain(unittest.TestCase):
    """main.py 与 context_manager 的接口一致性"""

    @classmethod
    def setUpClass(cls):
        from backend import main as main_module
        cls.main = main_module

    def test_context_manager_exposes_voice_identity_methods(self):
        """context_manager 单例提供 get/update_voice_identity"""
        cm = self.main.context_manager
        self.assertTrue(hasattr(cm, "get_voice_identity"))
        self.assertTrue(hasattr(cm, "update_voice_identity"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
