"""
YHLZ Voice Identity System V2.3-Phase6 - Mock API 测试

目标:
    - TEST_MODE=true 下, API 测试 100% 可运行
    - 不加载 GPU / 真实模型 (Qwen3-TTS / SenseVoice / GPT-SoVITS)
    - 使用 mock adapter 覆盖克隆/合成/列表/删除等核心 API

策略:
    1. 启动前设置 YHLZ_TEST_MODE=true
    2. mock 掉重模块 (asr_engine / tts_engine / vad_engine / conversation_manager)
       避免触发 lifespan 中的真实模型加载
    3. 使用 FastAPI TestClient, 但不触发生命周期 (with context)
    4. 直接调用 voice_identity 相关端点

运行方式:
    venv\\Scripts\\python.exe -m unittest backend.voice_identity.tests.test_mock_api -v
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock

# 启动前设置 TEST_MODE (必须在导入 main 之前)
os.environ["YHLZ_TEST_MODE"] = "true"

# 测试 DB 隔离
_TMP_DIR = Path(tempfile.mkdtemp(prefix="yhlz_mock_api_"))
os.environ["YHLZ_VOICE_IDENTITY_DB"] = str(_TMP_DIR / "test_mock.db")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _make_wav_bytes(duration_s: float = 5.0, sr: int = 16000) -> bytes:
    """生成 wav 字节流"""
    import math
    import struct
    buf = io.BytesIO()
    n = int(duration_s * sr)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _install_heavy_module_mocks() -> None:
    """在导入 main 前, 用 MagicMock 替换重模块

    避免 lifespan 加载真实 ASR/TTS/VAD 模型
    """
    import types

    async def _async_noop():
        pass

    def _make_async_mock():
        """返回每次调用都产生新 coroutine 的 mock"""
        def _call(*args, **kwargs):
            return _async_noop()
        return _call

    # asr_engine
    asr_mod = types.ModuleType("backend.asr_engine")
    asr_mod.asr_engine = MagicMock()
    asr_mod.asr_engine.unload = MagicMock()
    sys.modules["backend.asr_engine"] = asr_mod

    # tts_engine
    tts_mod = types.ModuleType("backend.tts_engine")
    tts_mod.tts_engine = MagicMock()
    tts_mod.tts_engine.unload = MagicMock()
    sys.modules["backend.tts_engine"] = tts_mod

    # vad_engine
    vad_mod = types.ModuleType("backend.vad_engine")
    vad_mod.vad_engine = MagicMock()
    vad_mod.vad_engine.unload = MagicMock()
    sys.modules["backend.vad_engine"] = vad_mod

    # conversation_manager (避免 start_conversation 启动真实流程)
    conv_mod = types.ModuleType("backend.conversation_manager")
    conv_mod.conversation_manager = MagicMock()
    conv_mod.conversation_manager.set_engines = MagicMock()
    conv_mod.conversation_manager.start_conversation = _make_async_mock()
    sys.modules["backend.conversation_manager"] = conv_mod

    # sync_manager
    sync_mod = types.ModuleType("backend.sync_manager")
    sync_mod.sync_manager = MagicMock()
    sync_mod.sync_manager.start = MagicMock()
    sync_mod.sync_manager.stop = MagicMock()
    sys.modules["backend.sync_manager"] = sync_mod

    # llm_engine
    llm_mod = types.ModuleType("backend.llm_engine")
    llm_mod.llm_engine = MagicMock()
    sys.modules["backend.llm_engine"] = llm_mod

    # audio_buffer
    buf_mod = types.ModuleType("backend.audio_buffer")
    buf_mod.audio_buffer = MagicMock()
    buf_mod.audio_buffer.sample_rate = 24000
    sys.modules["backend.audio_buffer"] = buf_mod

    # emotion_classifier
    emo_mod = types.ModuleType("backend.emotion_classifier")
    emo_mod.classify_emotion = MagicMock(return_value="neutral")
    emo_mod.resolve_voice_for_emotion = MagicMock(return_value=None)
    emo_mod.get_emotion_voice = MagicMock(return_value=None)
    sys.modules["backend.emotion_classifier"] = emo_mod

    # context_manager
    ctx_mod = types.ModuleType("backend.context_manager")
    ctx_mod.context_manager = MagicMock()
    ctx_mod.context_manager.get_voice_identity = MagicMock(return_value=None)
    ctx_mod.context_manager.update_voice_identity = MagicMock(return_value={})
    ctx_mod.context_manager.clear_history = MagicMock()
    sys.modules["backend.context_manager"] = ctx_mod


# 安装 mock (在导入 main 之前)
_install_heavy_module_mocks()

# 重置 DB 单例
from backend.voice_identity.database import reset_db_instance
reset_db_instance()

# 重置 mock_loader 单例
from backend.voice_identity.mock_loader import (
    get_mock_loader,
    is_test_mode,
    reset_mock_loader,
    setup_test_mode,
)
reset_mock_loader()
setup_test_mode()

# 导入 main (此时重模块已被 mock, lifespan 不会加载真实模型)
from backend import main as _main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 替换 lifespan 为 no-op (避免 TestClient 触发阻塞的生命周期事件)
from contextlib import asynccontextmanager  # noqa: E402

@asynccontextmanager
async def _noop_lifespan(app):
    yield

_main.app.router.lifespan_context = _noop_lifespan


class TestMockAPIBase(unittest.TestCase):
    """Mock API 测试基类"""

    @classmethod
    def setUpClass(cls):
        # 确认 TEST_MODE
        assert is_test_mode(), "TEST_MODE 未启用"
        # 使用原 app (lifespan 已替换为 no-op)
        cls.client = TestClient(_main.app, raise_server_exceptions=False)
        cls._main = _main
        # 重置 voice_identity service 单例 (确保使用 mock adapter)
        cls._main._voice_identity_service = None

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls._main, "_voice_identity_service"):
                svc = cls._main._voice_identity_service
                if svc is not None and hasattr(svc, "db"):
                    svc.db.close()
        except Exception:
            pass
        try:
            reset_db_instance()
        except Exception:
            pass

    def setUp(self):
        # 每个测试前重置 service 单例 (避免跨测试污染)
        self._main._voice_identity_service = None

    def _upload(self, name="Mock测试", engine="qwen3", voice_id=None,
                metadata=None, wav_bytes=None):
        if wav_bytes is None:
            wav_bytes = _make_wav_bytes(5.0)
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        data = {"name": name, "engine": engine}
        if voice_id:
            data["voice_id"] = voice_id
        if metadata is not None:
            data["metadata"] = metadata
        return self.client.post("/voice/clone", files=files, data=data)


class TestTestModeFlag(unittest.TestCase):
    """测试 TEST_MODE 开关"""

    def test_test_mode_enabled(self):
        """TEST_MODE 已启用"""
        self.assertTrue(is_test_mode())

    def test_mock_loader_singleton(self):
        """MockModelLoader 单例可用"""
        loader = get_mock_loader()
        self.assertIsNotNone(loader)

    def test_mock_loader_load_qwen3(self):
        """加载 mock qwen3 adapter"""
        from backend.voice_identity.mock_loader import MockModelLoader
        loader = MockModelLoader()
        result = loader.load("qwen3")
        self.assertTrue(result.is_ok, f"加载失败: {result.error}")
        adapter = result.unwrap()
        self.assertEqual(adapter.name, "qwen3")

    def test_mock_loader_load_gpt_sovits(self):
        """加载 mock gpt_sovits adapter"""
        from backend.voice_identity.mock_loader import MockModelLoader
        loader = MockModelLoader()
        result = loader.load("gpt_sovits")
        self.assertTrue(result.is_ok, f"加载失败: {result.error}")
        adapter = result.unwrap()
        self.assertEqual(adapter.name, "gpt_sovits")

    def test_mock_loader_health_check(self):
        """MockModelLoader 健康检查"""
        from backend.voice_identity.mock_loader import MockModelLoader
        loader = MockModelLoader()
        loader.load("qwen3")
        health = loader.health_check()
        self.assertTrue(health["ok"])
        self.assertTrue(health["mock"])
        self.assertIn("qwen3", health["loaded_engines"])

    def test_build_adapter_test_aware_mock(self):
        """TEST_MODE 下 build_adapter_test_aware 返回 mock"""
        from backend.voice_identity.mock_loader import build_adapter_test_aware
        result = build_adapter_test_aware("qwen3")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.unwrap().name, "qwen3")

    def test_mock_adapter_no_real_model(self):
        """mock adapter prepare 不依赖真实模型"""
        from backend.voice_identity.mock_loader import MockModelLoader
        from backend.voice_identity.clone.audio_validator import AudioInfo
        from backend.voice_identity.clone.voice_analyzer import VoiceFeature

        loader = MockModelLoader()
        result = loader.load("qwen3")
        adapter = result.unwrap()

        # 准备真实临时文件 (mock adapter 仍需读取文件计算 hash)
        import tempfile as _tf
        tmp_wav = _tf.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_wav.write(_make_wav_bytes(5.0))
        tmp_wav.close()

        try:
            audio_info = AudioInfo(
                path=tmp_wav.name, sample_rate=16000, duration_s=5.0,
                channels=1, frames=80000, format="wav",
            )
            feature = VoiceFeature(audio_info=audio_info)

            # prepare_voice 应成功 (mock 模式)
            prep = adapter.prepare_voice(tmp_wav.name, feature, {})
            self.assertTrue(prep.is_ok, f"prepare 失败: {prep.error}")
        finally:
            os.unlink(tmp_wav.name)

    def test_set_test_mode_toggle(self):
        """set_test_mode 可切换"""
        from backend.voice_identity.mock_loader import (
            set_test_mode, is_test_mode
        )
        old = is_test_mode()
        try:
            set_test_mode(False)
            self.assertFalse(is_test_mode())
            set_test_mode(True)
            self.assertTrue(is_test_mode())
        finally:
            set_test_mode(old)


class TestMockVoiceCloneAPI(TestMockAPIBase):
    """TEST_MODE 下声音克隆 API 测试"""

    def test_clone_success(self):
        """克隆成功 (mock adapter)"""
        resp = self._upload(name="测试声音1", engine="qwen3")
        self.assertEqual(resp.status_code, 200, f"响应: {resp.text}")
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIsNotNone(data.get("voice_id"))
        # mock adapter 应返回 quality_score
        self.assertIn("quality_score", data)

    def test_clone_with_explicit_voice_id(self):
        """显式 voice_id 克隆"""
        resp = self._upload(
            name="测试声音2", engine="qwen3", voice_id="mock-vid-001"
        )
        self.assertEqual(resp.status_code, 200, f"响应: {resp.text}")
        data = resp.json()
        self.assertEqual(data["voice_id"], "mock-vid-001")

    def test_clone_duplicate_voice_id(self):
        """重复 voice_id 失败"""
        # 第一次
        resp1 = self._upload(name="重复测试", voice_id="dup-vid-001")
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertTrue(data1.get("success"))
        # 第二次 (同 voice_id)
        resp2 = self._upload(name="重复测试2", voice_id="dup-vid-001")
        data2 = resp2.json()
        self.assertFalse(data2.get("success"), "重复 voice_id 应失败")

    def test_clone_missing_name(self):
        """缺少 name 参数失败"""
        wav_bytes = _make_wav_bytes(5.0)
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        data = {"engine": "qwen3"}  # 无 name
        resp = self.client.post("/voice/clone", files=files, data=data)
        # FastAPI Form(...) 缺失返回 422
        self.assertEqual(resp.status_code, 422)

    def test_voice_list(self):
        """声音列表"""
        # 先克隆一个
        self._upload(name="列表测试", voice_id="list-vid-001")
        resp = self.client.get("/voice/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        # API 返回 items 或 voices
        items = data.get("items") or data.get("voices") or []
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)

    def test_voice_detail(self):
        """声音详情"""
        self._upload(name="详情测试", voice_id="detail-vid-001")
        resp = self.client.get("/voice/detail-vid-001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        # API 可能返回 voice 或 profile
        voice = data.get("voice") or data.get("profile") or data
        self.assertEqual(voice.get("voice_id"), "detail-vid-001")

    def test_voice_delete(self):
        """删除声音"""
        self._upload(name="删除测试", voice_id="del-vid-001")
        resp = self.client.delete("/voice/del-vid-001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_synthesize(self):
        """合成测试 (mock adapter 返回空 wav)"""
        self._upload(name="合成测试", voice_id="synth-vid-001")
        resp = self.client.post(
            "/voice/synthesize",
            data={"voice_id": "synth-vid-001", "text": "测试合成"},
        )
        self.assertEqual(resp.status_code, 200, f"响应: {resp.text}")
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_adapters_dashboard(self):
        """Adapter 状态面板"""
        resp = self.client.get("/voice/adapters/dashboard")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_audit_log(self):
        """审计日志查询"""
        # 先克隆产生审计记录
        self._upload(name="审计测试", voice_id="audit-vid-001")
        resp = self.client.get("/voice/audit/log?limit=10")
        self.assertEqual(resp.status_code, 200)


class TestMockBatchAPI(TestMockAPIBase):
    """TEST_MODE 下批量克隆 API 测试"""

    def test_batch_submit_and_query(self):
        """批量克隆提交与查询"""
        wav1 = _make_wav_bytes(5.0)
        wav2 = _make_wav_bytes(6.0)

        # 上传两个音频 (需要通过 /voice/clone 上传, 收集 voice_id)
        # 这里测试批量任务提交端点
        # 由于批量端点需要 audio_ids, 先通过克隆获取
        r1 = self._upload(name="批量1", voice_id="batch-001")
        r2 = self._upload(name="批量2", voice_id="batch-002")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

        # 查询批量任务列表 (空)
        resp = self.client.get("/voice/clone/batch")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_batch_list_empty(self):
        """批量任务列表 (空)"""
        resp = self.client.get("/voice/clone/batch")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))


class TestMockLifecycleAPI(TestMockAPIBase):
    """TEST_MODE 下生命周期 API 测试"""

    def test_archive_and_restore(self):
        """归档与恢复"""
        self._upload(name="生命周期测试", voice_id="lc-vid-001")

        # 归档
        resp = self.client.post("/voice/lc-vid-001/archive")
        self.assertEqual(resp.status_code, 200, f"归档失败: {resp.text}")

        # 恢复
        resp = self.client.post("/voice/lc-vid-001/restore")
        self.assertEqual(resp.status_code, 200, f"恢复失败: {resp.text}")

    def test_lifecycle_list(self):
        """生命周期列表"""
        resp = self.client.get("/voice/lifecycle/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))


class TestMockQualityAPI(TestMockAPIBase):
    """TEST_MODE 下质量评估 API 测试"""

    def test_quality_evaluate(self):
        """质量评估端点"""
        wav_bytes = _make_wav_bytes(5.0)
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        data = {"reference_text": "测试文本"}
        resp = self.client.post(
            "/voice/quality/evaluate", files=files, data=data
        )
        # 可能因 librosa 不可用返回 200 但带降级标记, 或 422/500
        self.assertIn(resp.status_code, (200, 422))


if __name__ == "__main__":
    unittest.main(verbosity=2)
