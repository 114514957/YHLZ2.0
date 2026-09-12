"""
YHLZ Voice Identity System V2.2 - Voice Clone REST API 测试

覆盖 (对齐 V2.2 测试 Prompt):
    1. 上传正常 wav → 200 + voice_id + status=ready
    2. 参数缺失 (无 name) → 失败响应
    3. 重复 voice_id → 失败响应 (stage=create_voice)
    4. engine 不存在 → 失败响应 (stage=validate)
    5. 合成测试端点
    6. metadata JSON 解析失败 → 失败响应

运行方式:
    venv\\Scripts\\python.exe -m unittest backend.voice_identity.adapter.tests.test_voice_clone_api -v

不依赖真实后端服务; 使用 FastAPI TestClient 直接调 main:app 路由。
mock adapter 不需要 GPU, 完全本地可跑。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))


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


class TestVoiceCloneAPI(unittest.TestCase):
    """测试 POST /voice/clone 与 POST /voice/synthesize"""

    @classmethod
    def setUpClass(cls):
        """启动 FastAPI TestClient"""
        import fastapi.testclient as _tc  # type: ignore
        # 延迟导入 main, 避免副作用
        import importlib
        # 用独立 DB 路径避免污染生产数据
        cls.tmp_dir = tempfile.mkdtemp(prefix="yhlz_v22_api_")
        cls.db_path = os.path.join(cls.tmp_dir, "api_test.db")
        # 临时覆盖 voice_identity 默认 DB 路径 (database.py 读取此环境变量)
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = cls.db_path
        # 重置 DB 单例, 确保以新路径重建
        from backend.voice_identity.database import reset_db_instance
        reset_db_instance()

        from backend import main as _main
        importlib.reload(_main)
        cls.client = _tc.TestClient(_main.app)
        cls._main = _main

    @classmethod
    def tearDownClass(cls):
        import shutil
        try:
            if hasattr(cls, "_main") and hasattr(cls._main, "_voice_identity_service"):
                svc = cls._main._voice_identity_service
                if svc is not None:
                    svc.db.close()
        except Exception:
            pass
        # 重置 DB 单例, 释放对临时 DB 文件的句柄
        try:
            from backend.voice_identity.database import reset_db_instance
            reset_db_instance()
        except Exception:
            pass
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)

    def _upload(self, name="API测试", engine="qwen3", voice_id=None,
                metadata=None, wav_bytes=None):
        """辅助: 发起 /voice/clone 请求"""
        if wav_bytes is None:
            wav_bytes = _make_wav_bytes(5.0)
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        data = {"name": name, "engine": engine}
        if voice_id:
            data["voice_id"] = voice_id
        if metadata is not None:
            data["metadata"] = metadata
        return self.client.post("/voice/clone", files=files, data=data)

    # ------------------------------------------------------------------
    # 正常路径
    # ------------------------------------------------------------------

    def test_upload_normal_wav(self):
        """上传正常 wav → 200 + success=True + status=ready"""
        resp = self._upload(name="API正常测试")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("success"), f"应成功: {body}")
        self.assertEqual(body["status"], "ready")
        self.assertIsNotNone(body["voice_id"])
        self.assertEqual(body["engine"], "qwen3")
        # mock adapter 应填充
        self.assertEqual(body["adapter"], "qwen3")
        self.assertIsNotNone(body["embedding_hash"])
        self.assertIsNotNone(body["quality_score"])

    def test_synthesize_after_clone(self):
        """克隆后调 /voice/synthesize → 200 + audio_path"""
        # 先克隆
        r1 = self._upload(name="合成测试源")
        self.assertTrue(r1.json().get("success"), r1.text)
        vid = r1.json()["voice_id"]
        # 再合成
        resp = self.client.post(
            "/voice/synthesize",
            data={"voice_id": vid, "text": "你好", "language": "zh"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body.get("success"), f"合成应成功: {body}")
        self.assertTrue(os.path.exists(body["audio_path"]))

    # ------------------------------------------------------------------
    # 参数错误
    # ------------------------------------------------------------------

    def test_missing_name(self):
        """缺少 name → 失败 (FastAPI Form 必填返 422)"""
        wav_bytes = _make_wav_bytes(5.0)
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        # 不传 name
        data = {"engine": "qwen3"}
        resp = self.client.post("/voice/clone", files=files, data=data)
        # FastAPI Form 必填字段缺失返 422
        self.assertEqual(resp.status_code, 422)

    def test_missing_audio(self):
        """缺少 audio → 失败 (FastAPI File 必填返 422)"""
        data = {"name": "无音频", "engine": "qwen3"}
        resp = self.client.post("/voice/clone", data=data)
        self.assertEqual(resp.status_code, 422)

    def test_invalid_engine(self):
        """engine 不存在 → success=False + stage=validate"""
        resp = self._upload(name="坏engine", engine="nonexistent")
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["stage"], "validate")
        self.assertIn("engine", body["error"])

    def test_duplicate_voice_id(self):
        """重复 voice_id → 失败 + stage=create_voice"""
        # 用 uuid 避免跨测试运行残留 (DEFAULT_DB_PATH 不读环境变量)
        import uuid
        vid = f"dup_api_{uuid.uuid4().hex[:8]}"
        r1 = self._upload(name="第一次", voice_id=vid)
        self.assertTrue(r1.json().get("success"), r1.text)
        r2 = self._upload(name="第二次", voice_id=vid)
        body = r2.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["stage"], "create_voice")

    def test_invalid_metadata_json(self):
        """metadata JSON 解析失败 → stage=validate"""
        resp = self._upload(name="坏metadata", metadata="{invalid json")
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["stage"], "validate")
        self.assertIn("metadata", body["error"])

    # ------------------------------------------------------------------
    # 音频内容错误
    # ------------------------------------------------------------------

    def test_empty_audio_bytes(self):
        """空音频字节 → stage=validate"""
        files = {"audio": ("empty.wav", b"", "audio/wav")}
        data = {"name": "空音频", "engine": "qwen3"}
        resp = self.client.post("/voice/clone", files=files, data=data)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["stage"], "validate")

    def test_short_audio_rejected(self):
        """超短音频 (<3s) → stage=validate"""
        short_wav = _make_wav_bytes(1.0)  # 1 秒
        resp = self._upload(name="短音频", wav_bytes=short_wav)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["stage"], "validate")
        self.assertIn("过短", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
