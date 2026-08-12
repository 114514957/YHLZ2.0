"""
M0.3 TTS fallback 链单测: backend/tts/manager.py + backend/tts_engine.py

覆盖:
1. Engine Registry: 全部引擎注册 (qwen3-tts-customvoice / qwen3-tts / gpt-sovits / edge-tts)
2. 激活期降级: 指定引擎加载失败 → 沿链自动切换 (含日志格式断言)
3. 运行期降级: 合成抛异常 → 自动切换 → 下一引擎成功
4. 三级链: Qwen3失败 → GPT-SoVITS失败 → Edge 运行
5. 全链耗尽 → TTSEngineError
6. 真实链路: 本机 venv 缺 qwen 依赖 + 无 Gradio 服务 → 自动降级到 edge-tts

运行: venv\Scripts\python.exe 对话DEMO\test_tts_fallback.py
"""
import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts.base import BaseTTSEngine, TTSEngineError
from backend.tts.manager import TTSManager

FALLBACK_LOG_RE = "TTS Engine .* unavailable.* fallback to .*"


class FakeEngine(BaseTTSEngine):
    """可控假引擎: 可配置 load 失败 / synthesize 抛异常"""

    def __init__(self, name: str, load_ok: bool = True, synth_raises: bool = False):
        super().__init__()
        self.name = name
        self._load_ok = load_ok
        self._synth_raises = synth_raises
        self.load_calls = 0
        self.synth_calls = 0

    def load(self) -> bool:
        self.load_calls += 1
        self.is_loaded = self._load_ok
        return self._load_ok

    def unload(self) -> None:
        self.is_loaded = False

    def synthesize(self, text: str, voice: str = "default", rate: str = "+0%", **kwargs):
        self.synth_calls += 1
        if self._synth_raises:
            raise RuntimeError(f"{self.name} synthesize failed")
        return np.zeros(100, dtype=np.float32), 24000

    async def stream_synthesize_text(self, text: str, voice: str = "default", **kwargs):
        audio, sr = self.synthesize(text, voice=voice)
        yield audio, sr


class FallbackBase(unittest.TestCase):
    def setUp(self):
        self.manager = TTSManager()


# ---------------------------------------------------------------------------
# 1. 激活期降级 (Primary → Secondary)
# ---------------------------------------------------------------------------

class TestActivationFallback(FallbackBase):
    def test_primary_load_fail_auto_switch(self):
        """Qwen3(primary) 加载失败 → 自动切换到 GPT-SoVITS(secondary)"""
        qwen = FakeEngine("qwen3", load_ok=False)
        sovits = FakeEngine("gpt-sovits")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("gpt-sovits", sovits)

        with self.assertLogs("backend.tts.manager", level=logging.WARNING) as cm:
            ok = self.manager.activate("qwen3")

        self.assertTrue(ok)
        self.assertEqual(self.manager._active_name, "gpt-sovits")
        self.assertTrue(self.manager.is_loaded)
        # 明确 fallback 日志格式
        logs = "\n".join(cm.output)
        self.assertRegex(logs, "TTS Engine qwen3 unavailable.*fallback to gpt-sovits")

    def test_three_level_activation_chain(self):
        """Qwen3失败 → GPT-SoVITS失败 → Edge 运行"""
        qwen = FakeEngine("qwen3", load_ok=False)
        sovits = FakeEngine("gpt-sovits", load_ok=False)
        edge = FakeEngine("edge-tts")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("gpt-sovits", sovits)
        self.manager.register_engine("edge-tts", edge)

        with self.assertLogs("backend.tts.manager", level=logging.WARNING) as cm:
            ok = self.manager.activate("qwen3")

        self.assertTrue(ok)
        self.assertEqual(self.manager._active_name, "edge-tts")
        logs = "\n".join(cm.output)
        self.assertRegex(logs, "TTS Engine qwen3 unavailable.*fallback to edge-tts")

    def test_unknown_engine_falls_back(self):
        self.manager.register_engine("edge-tts", FakeEngine("edge-tts"))
        self.assertTrue(self.manager.activate("nonexistent"))
        self.assertEqual(self.manager._active_name, "edge-tts")

    def test_all_load_fail_returns_false(self):
        self.manager.register_engine("qwen3", FakeEngine("qwen3", load_ok=False))
        self.manager.register_engine("edge-tts", FakeEngine("edge-tts", load_ok=False))
        self.assertFalse(self.manager.activate("qwen3"))
        self.assertIsNone(self.manager._active_name)


# ---------------------------------------------------------------------------
# 2. 运行期降级 (合成异常自动切换)
# ---------------------------------------------------------------------------

class TestRuntimeFallback(FallbackBase):
    def test_synthesize_failure_auto_switch(self):
        """Qwen3 合成抛异常 → 自动切换 GPT-SoVITS 成功"""
        qwen = FakeEngine("qwen3", synth_raises=True)
        sovits = FakeEngine("gpt-sovits")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("gpt-sovits", sovits)
        self.manager.activate("qwen3")

        with self.assertLogs("backend.tts.manager", level=logging.WARNING) as cm:
            audio, sr = self.manager.synthesize("测试")

        self.assertEqual(sr, 24000)
        self.assertEqual(qwen.synth_calls, 1)
        self.assertEqual(sovits.synth_calls, 1)
        self.assertEqual(self.manager._active_name, "gpt-sovits")  # 状态持久化
        logs = "\n".join(cm.output)
        # 运行期日志: "TTS Engine qwen3 synthesize 失败, fallback to gpt-sovits"
        self.assertRegex(logs, r"TTS Engine qwen3 .*fallback to gpt-sovits")

    def test_runtime_three_level_degradation(self):
        """Qwen3失败 → GPT-SoVITS失败 → Edge 运行 (运行期三级链)"""
        qwen = FakeEngine("qwen3", synth_raises=True)
        sovits = FakeEngine("gpt-sovits", synth_raises=True)
        edge = FakeEngine("edge-tts")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("gpt-sovits", sovits)
        self.manager.register_engine("edge-tts", edge)
        self.manager.activate("qwen3")

        audio, sr = self.manager.synthesize("测试")

        self.assertEqual(sr, 24000)
        self.assertEqual(qwen.synth_calls, 1)
        self.assertEqual(sovits.synth_calls, 1)
        self.assertEqual(edge.synth_calls, 1)
        self.assertEqual(self.manager._active_name, "edge-tts")

    def test_runtime_all_fail_raises(self):
        qwen = FakeEngine("qwen3", synth_raises=True)
        edge = FakeEngine("edge-tts", synth_raises=True)
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("edge-tts", edge)
        self.manager.activate("qwen3")

        with self.assertRaises(TTSEngineError):
            self.manager.synthesize("测试")
        self.assertEqual(self.manager._active_name, "edge-tts")  # 链已走完

    def test_stream_fallback(self):
        qwen = FakeEngine("qwen3", synth_raises=True)
        edge = FakeEngine("edge-tts")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("edge-tts", edge)
        self.manager.activate("qwen3")

        chunks = []

        async def run():
            async for audio, sr in self.manager.stream_synthesize_text("测试"):
                chunks.append((audio, sr))

        asyncio.run(run())
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][1], 24000)
        self.assertEqual(self.manager._active_name, "edge-tts")

    def test_load_method_falls_back(self):
        qwen = FakeEngine("qwen3", load_ok=False)
        edge = FakeEngine("edge-tts")
        self.manager.register_engine("qwen3", qwen)
        self.manager.register_engine("edge-tts", edge)
        self.manager.activate("qwen3")  # 激活时已回退到 edge

        # 人为清空激活态, 验证 load() 沿链恢复
        self.manager._active_name = None
        self.assertTrue(self.manager.load())
        self.assertEqual(self.manager._active_name, "edge-tts")


# ---------------------------------------------------------------------------
# 3. 真实链路 (Engine Registry + 本机自动降级)
# ---------------------------------------------------------------------------

class TestRealChain(unittest.TestCase):
    """真实引擎注册表验证: 本机 venv 缺 qwen 依赖 + 无 Gradio 服务
    → qwen3-tts-customvoice 失败 → qwen3-tts 失败 → gpt-sovits 失败 → edge-tts 运行"""

    @classmethod
    def setUpClass(cls):
        from backend.tts_engine import tts_manager, ENGINE_REGISTRY
        cls.manager = tts_manager
        cls.registry = ENGINE_REGISTRY

    def test_all_engines_registered(self):
        """Engine Registry: 4 个引擎全部注册, 无遗漏"""
        names = list(self.manager._engines.keys())
        self.assertEqual(
            names,
            ["qwen3-tts-customvoice", "qwen3-tts", "gpt-sovits", "edge-tts"],
        )
        self.assertEqual([n for n, _ in self.registry], names)

    def test_fallback_chain_order(self):
        """回退链顺序: Qwen3(primary) → GPT-SoVITS(secondary) → Edge(fallback)"""
        chain = self.manager.describe_chain()
        self.assertEqual(chain[0], "qwen3-tts-customvoice")
        self.assertLess(chain.index("qwen3-tts"), chain.index("gpt-sovits"))
        self.assertLess(chain.index("gpt-sovits"), chain.index("edge-tts"))
        self.assertEqual(chain[-1], "edge-tts")  # Edge 是最终兜底

    def test_real_auto_degradation_to_edge(self):
        """本机环境: qwen 依赖缺失 + Gradio 不可达 → 自动降级到 edge-tts"""
        self.assertEqual(self.manager._active_name, "edge-tts")
        self.assertTrue(self.manager.is_loaded)

    def test_real_synthesize_via_chain(self):
        """激活的 edge-tts 可正常合成 (在线服务不可达时返回兜底音频, 不抛异常)"""
        try:
            audio, sr = self.manager.synthesize("回退链测试")
            self.assertEqual(sr, 24000)
            self.assertGreater(len(audio), 0)
        except Exception as e:
            self.fail(f"回退链合成不应抛异常: {e}")

    def test_switch_api_still_works(self):
        """activate() 签名不变: 显式切换不可用引擎 → 回退而非报错"""
        self.assertTrue(self.manager.activate("qwen3-tts"))  # 本机加载失败 → 回退
        self.assertEqual(self.manager._active_name, "edge-tts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
