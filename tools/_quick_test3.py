"""快速验证 mock API 测试 - 用 TestClient + lifespan 替换"""
import os
import sys
import types
import tempfile
import io
import wave
import struct
import math
from pathlib import Path
from unittest.mock import MagicMock
from contextlib import asynccontextmanager

os.environ["YHLZ_TEST_MODE"] = "true"
os.environ["YHLZ_VOICE_IDENTITY_DB"] = os.path.join(tempfile.mkdtemp(), "quick3.db")

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

print("1. mocks installed", flush=True)

from backend.voice_identity.mock_loader import setup_test_mode
setup_test_mode()
print("2. test_mode set", flush=True)

from backend.voice_identity.database import reset_db_instance
reset_db_instance()
print("3. db reset", flush=True)

from backend import main
print("4. main imported", flush=True)

@asynccontextmanager
async def _noop_lifespan(app):
    yield
main.app.router.lifespan_context = _noop_lifespan
print("5. lifespan replaced", flush=True)

from fastapi.testclient import TestClient
c = TestClient(main.app, raise_server_exceptions=False)
print("6. TestClient created", flush=True)

r = c.get("/voice/list")
print(f"7. GET /voice/list: {r.status_code}", flush=True)

# 测试克隆
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
r = c.post("/voice/clone", files=files, data=data)
print(f"8. POST /voice/clone: {r.status_code} {r.text[:300]}", flush=True)

r = c.get("/voice/list")
print(f"9. GET /voice/list: {r.status_code} {r.text[:200]}", flush=True)
print("10. done", flush=True)
