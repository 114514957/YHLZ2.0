"""快速验证 mock API 测试 - 用 httpx 直接测试"""
import os
import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

os.environ["YHLZ_TEST_MODE"] = "true"
os.environ["YHLZ_VOICE_IDENTITY_DB"] = os.path.join(tempfile.mkdtemp(), "quick2.db")

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

async def _noop():
    pass

def _am():
    def _c(*a, **k):
        return _noop()
    return _c

# 安装 mock
for mod_name, attr in [("asr_engine", "asr_engine"), ("tts_engine", "tts_engine"),
                        ("vad_engine", "vad_engine"), ("conversation_manager", "conversation_manager"),
                        ("sync_manager", "sync_manager"), ("llm_engine", "llm_engine"),
                        ("audio_buffer", "audio_buffer"), ("context_manager", "context_manager")]:
    m = types.ModuleType(f"backend.{mod_name}")
    setattr(m, attr, MagicMock())
    sys.modules[f"backend.{mod_name}"] = m

emo = types.ModuleType("backend.emotion_classifier")
emo.classify_emotion = MagicMock(return_value="neutral")
emo.resolve_voice_for_emotion = MagicMock(return_value=None)
emo.get_emotion_voice = MagicMock(return_value=None)
sys.modules["backend.emotion_classifier"] = emo

sys.modules["backend.conversation_manager"].conversation_manager.start_conversation = _am()
sys.modules["backend.audio_buffer"].audio_buffer.sample_rate = 24000

print("1. mocks installed")

from backend.voice_identity.mock_loader import setup_test_mode
setup_test_mode()
print("2. test_mode set")

from backend.voice_identity.database import reset_db_instance
reset_db_instance()
print("3. db reset")

from backend import main
print("4. main imported")

# 创建无 lifespan 的测试 app
from fastapi import FastAPI
_test_app = FastAPI(title="Test No Lifespan")
for route in main.app.routes:
    if hasattr(route, "path") and not route.path.startswith(("/openapi", "/docs", "/redoc")):
        _test_app.router.routes.append(route)
_test_app.dependency_overrides = main.app.dependency_overrides
print(f"5. test app created with {len(_test_app.routes)} routes")

# 用 httpx.AsyncClient + ASGITransport (不触发 lifespan)
import httpx
import asyncio
from httpx._transports.asgi import ASGITransport

async def _test():
    transport = ASGITransport(app=_test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        print("6. client created")
        r = await client.get("/voice/list")
        print(f"7. GET /voice/list: {r.status_code} {r.text[:200]}")
        
        # 测试克隆
        import io, wave, struct, math
        buf = io.BytesIO()
        sr = 16000
        n = int(5.0 * sr)
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            frames = bytearray()
            for i in range(n):
                v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
                frames.extend(struct.pack("<h", v))
            w.writeframes(bytes(frames))
        wav_bytes = buf.getvalue()
        
        files = {"audio": ("test.wav", wav_bytes, "audio/wav")}
        data = {"name": "QuickTest", "engine": "qwen3", "voice_id": "quick-001"}
        r = await client.post("/voice/clone", files=files, data=data)
        print(f"8. POST /voice/clone: {r.status_code} {r.text[:300]}")
        
        r = await client.get("/voice/list")
        print(f"9. GET /voice/list: {r.status_code} {r.text[:200]}")

asyncio.run(_test())
print("10. done")
