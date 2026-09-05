"""快速验证 mock API 克隆 - 详细调试"""
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
os.environ["YHLZ_VOICE_IDENTITY_DB"] = os.path.join(tempfile.mkdtemp(), "debug.db")

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))

async def _noop():
    pass

def _am():
    def _c(*a, **k):
        return _noop()
    return _c

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

from backend.voice_identity.mock_loader import setup_test_mode
setup_test_mode()
from backend.voice_identity.database import reset_db_instance
reset_db_instance()
from backend import main

@asynccontextmanager
async def _noop_lifespan(app):
    yield
main.app.router.lifespan_context = _noop_lifespan

from fastapi.testclient import TestClient
c = TestClient(main.app, raise_server_exceptions=False)

# 直接测试 pipeline 各步骤
from backend.voice_identity.clone.audio_validator import validate_audio
from backend.voice_identity.clone.voice_analyzer import analyze_voice

# 生成测试 wav
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

# 保存到临时文件
tmp_wav = os.path.join(tempfile.mkdtemp(), "test.wav")
with open(tmp_wav, "wb") as f:
    f.write(wav_bytes)

print(f"STEP 1: validate_audio({tmp_wav})", flush=True)
v = validate_audio(tmp_wav)
print(f"  result: is_err={v.is_err()}", flush=True)
if v.is_err():
    print(f"  error: {v.error}", flush=True)
    sys.exit(1)
audio_info = v.unwrap()
print(f"  duration_s={audio_info.duration_s}", flush=True)

print("STEP 2: analyze_voice", flush=True)
a = analyze_voice(audio_info)
print(f"  result: is_err={a.is_err()}", flush=True)
if a.is_err():
    print(f"  error: {a.error}", flush=True)
    sys.exit(1)
feature = a.unwrap()
print(f"  snr_db={feature.snr_db} mean_energy={feature.mean_energy}", flush=True)

print("STEP 3: service init", flush=True)
svc = main._get_voice_identity_service()
print(f"  service: {svc}", flush=True)

print("STEP 4: build adapter", flush=True)
from backend.voice_identity.mock_loader import build_adapter_from_config_test_aware
adapter_r = build_adapter_from_config_test_aware("qwen3")
print(f"  adapter: is_ok={adapter_r.is_ok}", flush=True)

print("STEP 5: clone_voice_with_adapter", flush=True)
result = svc.clone_voice_with_adapter(
    audio_path=tmp_wav, name="DebugTest", engine="qwen3",
    voice_id="debug-001", auto_prepare=True, adapter=adapter_r.unwrap(),
)
print(f"  result: is_err={result.is_err()}", flush=True)
if result.is_err():
    print(f"  error: {result.error}", flush=True)
else:
    cr = result.unwrap()
    print(f"  voice_id={cr.profile.voice_id} quality_status={cr.quality_status}", flush=True)

print("ALL DONE", flush=True)
