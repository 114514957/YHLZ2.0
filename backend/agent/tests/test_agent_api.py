"""
测试: Agent V3.0 API 端点 (/agent/*)
覆盖: chat / chat/stream / plan / tools / status / memory CRUD

策略:
    1. 启动前设置 YHLZ_TEST_MODE=true (强制 MockLLMAdapter)
    2. mock 掉重模块 (asr_engine / tts_engine / vad_engine / conversation_manager)
       避免 lifespan 中的真实模型加载
    3. 使用 FastAPI TestClient, lifespan 替换为 no-op
    4. 内存 DB 隔离 (:memory:)
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# 启动前设置 TEST_MODE (必须在导入 main 之前)
os.environ["YHLZ_TEST_MODE"] = "true"
os.environ["YHLZ_AGENT_TEST_MODE"] = "true"
os.environ["YHLZ_AGENT_MEMORY_DB"] = ":memory:"

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _install_heavy_module_mocks() -> None:
    """在导入 main 前, 用 MagicMock 替换重模块"""
    import types

    async def _async_noop():
        pass

    def _make_async_mock():
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

    # conversation_manager
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

# 导入 main (此时重模块已被 mock)
from backend import main as _main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 替换 lifespan 为 no-op
from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):
    yield


_main.app.router.lifespan_context = _noop_lifespan

# 重置 Agent 全局单例 (确保使用 mock)
from backend.agent.service import reset_all  # noqa: E402
reset_all()


class TestAgentAPIBase(unittest.TestCase):
    """Agent API 测试基类"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(_main.app, raise_server_exceptions=False)
        cls._main = _main

    def setUp(self):
        # 每个测试前重置 Agent 单例
        reset_all()


class TestAgentStatus(TestAgentAPIBase):
    """/agent/status 端点"""

    def test_status_returns_200(self):
        """状态接口返回 200"""
        r = self.client.get("/agent/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["version"], "3.0.0")
        self.assertIn("llm_mode", data)
        self.assertIn("tools_count", data)
        self.assertIn("builtin_tools", data)

    def test_status_llm_mode_mock(self):
        """TEST_MODE 下 llm_mode 应为 mock"""
        r = self.client.get("/agent/status")
        data = r.json()
        self.assertEqual(data["llm_mode"], "mock")


class TestAgentTools(TestAgentAPIBase):
    """/agent/tools 端点"""

    def test_list_tools(self):
        """列出所有工具"""
        r = self.client.get("/agent/tools")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("success"))
        names = [t["name"] for t in data["tools"]]
        self.assertIn("get_time", names)
        self.assertIn("calculator", names)

    def test_list_tools_by_category(self):
        """按类别列出工具"""
        r = self.client.get("/agent/tools?category=builtin")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for t in data["tools"]:
            self.assertEqual(t["category"], "builtin")

    def test_get_tool_detail(self):
        """获取工具详情"""
        r = self.client.get("/agent/tools/get_time")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["tool"]["name"], "get_time")

    def test_get_tool_nonexistent(self):
        """获取不存在的工具 → 404"""
        r = self.client.get("/agent/tools/nonexistent_tool_xyz")
        self.assertEqual(r.status_code, 404)


class TestAgentChat(TestAgentAPIBase):
    """/agent/chat 端点"""

    def test_chat_simple(self):
        """简单对话"""
        r = self.client.post("/agent/chat", json={
            "query": "你好",
            "use_tools": False,
            "use_memory": False,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["answer"]), 0)

    def test_chat_with_tool(self):
        """带工具调用对话"""
        r = self.client.post("/agent/chat", json={
            "query": "现在几点",
            "use_tools": True,
            "use_memory": False,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        # 应有工具调用
        self.assertGreater(len(data["tool_calls"]), 0)

    def test_chat_empty_query(self):
        """空查询 → success=False"""
        r = self.client.post("/agent/chat", json={
            "query": "",
            "use_tools": False,
            "use_memory": False,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["success"])

    def test_chat_with_history(self):
        """带历史消息"""
        r = self.client.post("/agent/chat", json={
            "query": "继续",
            "use_tools": False,
            "use_memory": False,
            "history": [
                {"role": "user", "content": "之前问题"},
                {"role": "assistant", "content": "之前回答"},
            ],
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])

    def test_chat_stream(self):
        """流式对话 (SSE)"""
        with self.client.stream("POST", "/agent/chat/stream", json={
            "query": "你好",
            "use_tools": False,
            "use_memory": False,
        }) as r:
            self.assertEqual(r.status_code, 200)
            chunks = []
            for line in r.iter_lines():
                if line:
                    chunks.append(line)
            self.assertGreater(len(chunks), 0)


class TestAgentPlan(TestAgentAPIBase):
    """/agent/plan 端点"""

    def test_plan(self):
        """生成执行计划"""
        r = self.client.post("/agent/plan", json={
            "goal": "查询当前时间",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(len(data["plan"]["steps"]), 1)


class TestAgentMemoryAPI(TestAgentAPIBase):
    """/agent/memory 端点"""

    def test_add_and_list_memory(self):
        """添加并列出记忆"""
        # 添加
        r = self.client.post("/agent/memory", json={
            "content": "测试记忆API",
            "category": "fact",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        mid = data["memory_id"]
        self.assertTrue(mid)

        # 列出
        r = self.client.get("/agent/memory?limit=10")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["memories"]), 1)

    def test_search_memory(self):
        """搜索记忆"""
        # 添加
        self.client.post("/agent/memory", json={
            "content": "用户喜欢喝咖啡",
            "category": "preference",
        })
        # 搜索
        r = self.client.get("/agent/memory/search?query=咖啡&limit=5")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["memories"]), 1)

    def test_get_memory_detail(self):
        """获取记忆详情"""
        # 添加
        r = self.client.post("/agent/memory", json={
            "content": "详情测试",
            "category": "fact",
        })
        mid = r.json()["memory_id"]
        # 获取
        r = self.client.get(f"/agent/memory/{mid}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["memory"]["id"], mid)
        self.assertEqual(data["memory"]["content"], "详情测试")

    def test_get_memory_nonexistent(self):
        """获取不存在的记忆 → 404"""
        r = self.client.get("/agent/memory/nonexistent_id")
        self.assertEqual(r.status_code, 404)

    def test_short_term_memory(self):
        """短期记忆接口"""
        r = self.client.get("/agent/memory/short-term?limit=10")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
