"""快速验证 mock API 测试环境"""
import os
import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

os.environ["YHLZ_TEST_MODE"] = "true"
os.environ["YHLZ_VOICE_IDENTITY_DB"] = os.path.join(tempfile.mkdtemp(), "quick.db")

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

from contextlib import asynccontextmanager
@asynccontextmanager
async def _nl(app):
    yield
main.app.router.lifespan_context = _nl
print("5. lifespan replaced")

from fastapi.testclient import TestClient
c = TestClient(main.app)
print("6. TestClient created")

r = c.get("/voice/list")
print(f"7. GET /voice/list: {r.status_code} {r.text[:200]}")
