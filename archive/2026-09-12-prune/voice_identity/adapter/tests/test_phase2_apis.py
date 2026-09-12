"""
YHLZ Voice Identity System - 工程化项 + Phase 2.1 API 测试

覆盖:
    - 数据隔离: DEFAULT_DB_PATH 读环境变量 + reset_db_instance
    - 并发安全: clone_voice_with_adapter 不污染全局 _adapter
    - Phase 2.1 API: GET /voice/list, GET /voice/{id}, DELETE /voice/{id}
    - 上传清理 API: POST /voice/uploads/cleanup, DELETE /voice/uploads/cleanup-all
    - Phase 2.3 API: GET /voice/adapters/dashboard
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import wave
import math
import struct
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))


def _make_wav_bytes(duration_s: float = 5.0, sr: int = 16000) -> bytes:
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


class TestDbIsolation(unittest.TestCase):
    """数据隔离: 环境变量 + reset_db_instance"""

    def test_default_db_path_reads_env(self):
        """DEFAULT_DB_PATH 应读取环境变量"""
        # 重新导入 database 模块以应用环境变量
        import importlib
        old_env = os.environ.get("YHLZ_VOICE_IDENTITY_DB")
        try:
            os.environ["YHLZ_VOICE_IDENTITY_DB"] = "/tmp/test_isolation.db"
            import backend.voice_identity.database as db_mod
            importlib.reload(db_mod)
            self.assertEqual(db_mod.DEFAULT_DB_PATH, "/tmp/test_isolation.db")
        finally:
            if old_env is None:
                os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)
            else:
                os.environ["YHLZ_VOICE_IDENTITY_DB"] = old_env
            # 恢复模块
            import backend.voice_identity.database as db_mod
            importlib.reload(db_mod)

    def test_reset_db_instance(self):
        """reset_db_instance 应清空单例"""
        from backend.voice_identity.database import reset_db_instance, get_db, _db_instance
        # 先确保有单例 (用临时 DB)
        old_env = os.environ.get("YHLZ_VOICE_IDENTITY_DB")
        tmp_dir = tempfile.mkdtemp()
        tmp_db = os.path.join(tmp_dir, "reset_test.db")
        try:
            os.environ["YHLZ_VOICE_IDENTITY_DB"] = tmp_db
            import backend.voice_identity.database as db_mod
            importlib.reload(db_mod)
            db_mod.reset_db_instance()
            db = db_mod.get_db()
            self.assertIsNotNone(db_mod._db_instance)
            db_mod.reset_db_instance()
            self.assertIsNone(db_mod._db_instance)
        finally:
            import backend.voice_identity.database as db_mod
            db_mod.reset_db_instance()
            if old_env is None:
                os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)
            else:
                os.environ["YHLZ_VOICE_IDENTITY_DB"] = old_env
            importlib.reload(db_mod)
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestCloneWithAdapterConcurrency(unittest.TestCase):
    """并发安全: clone_voice_with_adapter 不污染全局 _adapter"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="yhlz_concurrency_")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = self.db_path
        from backend.voice_identity.database import reset_db_instance
        reset_db_instance()

        from backend.voice_identity import VoiceIdentityService, VoiceIdentityDB
        from backend.voice_identity.adapter import Qwen3TTSAdapter
        self.svc = VoiceIdentityService.create_default(db=VoiceIdentityDB(self.db_path))
        self.global_adapter = Qwen3TTSAdapter(mode="mock")
        self.svc.set_adapter(self.global_adapter)

        # 生成测试音频
        self.audio_path = os.path.join(self.tmp_dir, "ref.wav")
        with wave.open(self.audio_path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            frames = bytearray()
            for i in range(16000 * 5):
                v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / 16000))
                frames.extend(struct.pack("<h", v))
            w.writeframes(bytes(frames))

    def tearDown(self):
        import shutil
        from backend.voice_identity.database import reset_db_instance
        reset_db_instance()
        os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_clone_with_adapter_does_not_mutate_global(self):
        """请求级 adapter 不应修改全局 _adapter"""
        from backend.voice_identity.adapter import GPTSoVITSAdapter
        request_adapter = GPTSoVITSAdapter(mode="mock")
        # 全局是 Qwen3, 请求级用 GPT-SoVITS
        self.assertEqual(self.svc.get_adapter().name, "qwen3")
        r = self.svc.clone_voice_with_adapter(
            audio_path=self.audio_path, name="并发测试",
            engine="gpt_sovits", auto_prepare=True, adapter=request_adapter,
        )
        self.assertTrue(r.is_ok, r.error)
        # 全局 _adapter 应保持 qwen3 不变
        self.assertEqual(self.svc.get_adapter().name, "qwen3")
        # 但 clone 结果应使用请求级 adapter (gpt_sovits)
        clone_result = r.unwrap()
        self.assertEqual(clone_result.adapter, "gpt_sovits")

    def test_clone_with_adapter_none_falls_back(self):
        """adapter=None 退化为全局 adapter 行为"""
        r = self.svc.clone_voice_with_adapter(
            audio_path=self.audio_path, name="fallback测试",
            engine="qwen3", auto_prepare=True, adapter=None,
        )
        self.assertTrue(r.is_ok, r.error)
        self.assertEqual(r.unwrap().adapter, "qwen3")


class TestPhase2APIs(unittest.TestCase):
    """Phase 2.1 + 工程化项 + 2.3 API 测试"""

    @classmethod
    def setUpClass(cls):
        import fastapi.testclient as _tc
        cls.tmp_dir = tempfile.mkdtemp(prefix="yhlz_phase2_api_")
        cls.db_path = os.path.join(cls.tmp_dir, "phase2_test.db")
        os.environ["YHLZ_VOICE_IDENTITY_DB"] = cls.db_path
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
        try:
            from backend.voice_identity.database import reset_db_instance
            reset_db_instance()
        except Exception:
            pass
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        os.environ.pop("YHLZ_VOICE_IDENTITY_DB", None)

    def _upload(self, name="测试", engine="qwen3", voice_id=None):
        files = {"audio": ("test.wav", _make_wav_bytes(5.0), "audio/wav")}
        data = {"name": name, "engine": engine}
        if voice_id:
            data["voice_id"] = voice_id
        return self.client.post("/voice/clone", files=files, data=data)

    def test_voice_list_empty_then_clone_then_list(self):
        """GET /voice/list: 空列表 → 克隆 → 非空"""
        # 清理可能残留 (隔离 DB 应为空)
        r0 = self.client.get("/voice/list")
        self.assertEqual(r0.status_code, 200)
        body0 = r0.json()
        self.assertTrue(body0["success"])
        # 克隆一个
        r1 = self._upload(name="列表测试", voice_id=f"list_test_{os.getpid()}")
        self.assertTrue(r1.json().get("success"), r1.text)
        vid = r1.json()["voice_id"]
        # 再查列表
        r2 = self.client.get("/voice/list")
        body2 = r2.json()
        self.assertTrue(body2["success"])
        self.assertGreaterEqual(body2["total"], 1)
        ids = [it["voice_id"] for it in body2["items"]]
        self.assertIn(vid, ids)

    def test_voice_detail(self):
        """GET /voice/{id}"""
        import uuid
        vid = f"detail_test_{uuid.uuid4().hex[:8]}"
        r1 = self._upload(name="详情测试", voice_id=vid)
        self.assertTrue(r1.json().get("success"), r1.text)
        r2 = self.client.get(f"/voice/{vid}")
        self.assertEqual(r2.status_code, 200)
        body = r2.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["voice_id"], vid)
        self.assertEqual(body["name"], "详情测试")

    def test_voice_detail_not_exist(self):
        """GET /voice/{id} 不存在"""
        r = self.client.get("/voice/nonexistent_id")
        body = r.json()
        self.assertFalse(body["success"])
        self.assertIn("不存在", body["error"])

    def test_voice_delete(self):
        """DELETE /voice/{id}"""
        import uuid
        vid = f"del_test_{uuid.uuid4().hex[:8]}"
        r1 = self._upload(name="删除测试", voice_id=vid)
        self.assertTrue(r1.json().get("success"), r1.text)
        r2 = self.client.delete(f"/voice/{vid}")
        body2 = r2.json()
        self.assertTrue(body2["success"])
        # 再查应不存在
        r3 = self.client.get(f"/voice/{vid}")
        self.assertFalse(r3.json()["success"])

    def test_voice_delete_not_exist(self):
        """DELETE /voice/{id} 不存在"""
        r = self.client.delete("/voice/nonexistent_del_id")
        # V2.3-Phase3: 权限校验可能返回 404 HTTPException ({"detail": "..."})
        # 或端点返回 {"success": False, "error": "..."}
        body = r.json()
        self.assertIn(r.status_code, (200, 404))
        if r.status_code == 404:
            # HTTPException 格式
            self.assertIn("detail", body)
        else:
            self.assertFalse(body["success"])

    def test_uploads_cleanup_ttl(self):
        """POST /voice/uploads/cleanup"""
        r = self.client.post("/voice/uploads/cleanup")
        body = r.json()
        self.assertTrue(body["success"])
        self.assertIn("stats", body)

    def test_uploads_cleanup_all(self):
        """DELETE /voice/uploads/cleanup-all"""
        r = self.client.delete("/voice/uploads/cleanup-all")
        body = r.json()
        self.assertTrue(body["success"])
        self.assertIn("stats", body)

    def test_adapters_dashboard(self):
        """GET /voice/adapters/dashboard"""
        r = self.client.get("/voice/adapters/dashboard")
        body = r.json()
        self.assertTrue(body["success"])
        self.assertIn("adapters", body)
        names = [a["name"] for a in body["adapters"]]
        self.assertIn("qwen3", names)
        self.assertIn("gpt_sovits", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
