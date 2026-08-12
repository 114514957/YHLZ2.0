"""
M0.6 显存策略单测: backend/memory_policy.py

覆盖:
1. EnginePolicy / MemoryPolicy: 默认策略 / can_coexist / from_dict / to_dict 往返
2. voice_engine.can_coexist=false 验收 (任务要求): 与 ASR 不可共存
3. MemoryController.acquire: 释放冲突引擎 → 激活目标
4. MemoryController.release: 释放指定引擎
5. MemoryController.switch: 模型切换 (释放冲突 + 激活新引擎)
6. can_acquire 预检: 策略冲突 + 显存预算
7. get_snapshot: 含 active_engines / vram / policy
8. 回调注册: load_fn / release_fn 被正确调用

运行: venv\Scripts\python.exe 对话DEMO\test_memory_policy.py
（不依赖 GPU 真实加载, 使用 mock 回调）
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.memory_policy import (
    ASR_ENGINE,
    VOICE_TTS_ENGINE,
    STREAM_TTS_ENGINE,
    LLM_ENGINE,
    EnginePolicy,
    MemoryPolicy,
    MemoryController,
    DEFAULT_POLICY,
)


class TestEnginePolicy(unittest.TestCase):

    def test_default_voice_engine_cannot_coexist(self):
        """验收: voice_engine.can_coexist = false (任务要求)"""
        policy = DEFAULT_POLICY[VOICE_TTS_ENGINE]
        self.assertFalse(policy.can_coexist)
        self.assertIn(ASR_ENGINE, policy.release_on_conflict)

    def test_to_dict_roundtrip(self):
        ep = EnginePolicy(can_coexist=False, vram_estimate_gb=3.0, release_on_conflict=["asr"])
        d = ep.to_dict()
        self.assertEqual(d["can_coexist"], False)
        self.assertEqual(d["vram_estimate_gb"], 3.0)
        self.assertEqual(d["release_on_conflict"], ["asr"])


class TestMemoryPolicy(unittest.TestCase):

    def test_default_policy_has_four_engines(self):
        mp = MemoryPolicy()
        for e in [ASR_ENGINE, VOICE_TTS_ENGINE, STREAM_TTS_ENGINE, LLM_ENGINE]:
            self.assertIn(e, mp.policies)

    def test_voice_engine_cannot_coexist_with_asr(self):
        """voice_engine 与 ASR 不可共存"""
        mp = MemoryPolicy()
        self.assertFalse(mp.can_coexist_with(VOICE_TTS_ENGINE, [ASR_ENGINE]))

    def test_voice_engine_cannot_coexist_with_stream_tts(self):
        mp = MemoryPolicy()
        self.assertFalse(mp.can_coexist_with(VOICE_TTS_ENGINE, [STREAM_TTS_ENGINE]))

    def test_asr_can_coexist_with_llm(self):
        """ASR 可与 LLM (云端, 不占显存) 共存"""
        mp = MemoryPolicy()
        self.assertTrue(mp.can_coexist_with(ASR_ENGINE, [LLM_ENGINE]))

    def test_unknown_engine_returns_permissive_policy(self):
        mp = MemoryPolicy()
        ep = mp.get("nonexistent_engine")
        self.assertTrue(ep.can_coexist)  # 默认允许共存, 不阻塞

    def test_from_dict_roundtrip(self):
        d = {
            "voice_engine": {
                "can_coexist": False,
                "vram_estimate_gb": 3.0,
                "release_on_conflict": ["asr"],
            }
        }
        mp = MemoryPolicy.from_dict(d)
        ep = mp.get("voice_engine")
        self.assertFalse(ep.can_coexist)
        self.assertEqual(ep.vram_estimate_gb, 3.0)
        self.assertEqual(ep.release_on_conflict, ["asr"])
        # to_dict 可序列化
        out = mp.to_dict()
        self.assertIn("voice_engine", out)


class TestMemoryControllerAcquire(unittest.TestCase):
    """验收: acquire 释放冲突引擎 → 激活目标"""

    def _make_controller(self):
        ctl = MemoryController()
        # 注册 mock 回调
        asr_load = MagicMock(return_value=True)
        asr_release = MagicMock()
        voice_load = MagicMock(return_value=True)
        voice_release = MagicMock()
        ctl.register_handler(ASR_ENGINE, asr_load, asr_release)
        ctl.register_handler(VOICE_TTS_ENGINE, voice_load, voice_release)
        return ctl, asr_load, asr_release, voice_load, voice_release

    def test_acquire_asr_then_voice_releases_asr(self):
        """ASR 激活 → 获取 voice_engine 时应释放 ASR (can_coexist=false)"""
        ctl, asr_load, asr_release, voice_load, voice_release = self._make_controller()
        # 先激活 ASR
        self.assertTrue(ctl.acquire(ASR_ENGINE))
        self.assertTrue(ctl.is_active(ASR_ENGINE))
        asr_load.assert_called_once()

        # 激活 voice_engine → 应释放 ASR
        self.assertTrue(ctl.acquire(VOICE_TTS_ENGINE))
        self.assertTrue(ctl.is_active(VOICE_TTS_ENGINE))
        self.assertFalse(ctl.is_active(ASR_ENGINE))  # ASR 被释放
        asr_release.assert_called_once()
        voice_load.assert_called_once()

    def test_acquire_load_failure_returns_false(self):
        """load_fn 返回 False → acquire 失败, 不计入 active"""
        ctl = MemoryController()
        ctl.register_handler(VOICE_TTS_ENGINE, load_fn=MagicMock(return_value=False), release_fn=MagicMock())
        self.assertFalse(ctl.acquire(VOICE_TTS_ENGINE))
        self.assertFalse(ctl.is_active(VOICE_TTS_ENGINE))

    def test_acquire_unknown_engine_without_handler_still_records(self):
        """无 handler 的引擎 acquire 仍记入 active (策略允许时)"""
        ctl = MemoryController()
        self.assertTrue(ctl.acquire(LLM_ENGINE))  # LLM 可共存, 无 handler
        self.assertTrue(ctl.is_active(LLM_ENGINE))

    def test_acquire_idempotent_when_already_active(self):
        ctl = MemoryController()
        voice_load = MagicMock(return_value=True)
        ctl.register_handler(VOICE_TTS_ENGINE, voice_load, MagicMock())
        ctl.acquire(VOICE_TTS_ENGINE)
        ctl.acquire(VOICE_TTS_ENGINE)  # 再次 acquire
        # load_fn 应被调用两次 (当前实现不短路); 但 active 集合不重复
        self.assertEqual(len(ctl.active_engines), 1)


class TestMemoryControllerRelease(unittest.TestCase):

    def test_release_active_engine(self):
        ctl = MemoryController()
        release_fn = MagicMock()
        ctl.register_handler(VOICE_TTS_ENGINE, MagicMock(return_value=True), release_fn)
        ctl.acquire(VOICE_TTS_ENGINE)
        ctl.release(VOICE_TTS_ENGINE)
        self.assertFalse(ctl.is_active(VOICE_TTS_ENGINE))
        release_fn.assert_called_once()

    def test_release_inactive_engine_noop(self):
        ctl = MemoryController()
        release_fn = MagicMock()
        ctl.register_handler(VOICE_TTS_ENGINE, MagicMock(return_value=True), release_fn)
        # 未激活直接 release
        ctl.release(VOICE_TTS_ENGINE)
        release_fn.assert_not_called()


class TestMemoryControllerSwitch(unittest.TestCase):
    """模型切换: 释放所有冲突引擎 → 激活新引擎"""

    def test_switch_from_voice_to_asr(self):
        ctl = MemoryController()
        asr_load = MagicMock(return_value=True)
        asr_release = MagicMock()
        voice_load = MagicMock(return_value=True)
        voice_release = MagicMock()
        ctl.register_handler(ASR_ENGINE, asr_load, asr_release)
        ctl.register_handler(VOICE_TTS_ENGINE, voice_load, voice_release)

        # 先激活 voice_engine
        ctl.acquire(VOICE_TTS_ENGINE)
        self.assertTrue(ctl.is_active(VOICE_TTS_ENGINE))

        # 切换到 ASR (voice_engine 在 ASR 的 release_on_conflict? 默认 ASR 可共存, 不含 voice)
        # 但 voice_engine 不能与 ASR 共存 → ASR acquire 时, 检查 voice 是否在 asr.release_on_conflict
        # 默认 ASR.release_on_conflict=[] (空), 但 can_coexist_with 会反向检查 voice 的策略
        ctl.switch(ASR_ENGINE)
        self.assertTrue(ctl.is_active(ASR_ENGINE))
        # voice_engine 应被释放 (因为 voice 不能与 asr 共存, acquire asr 时检测到冲突)
        self.assertFalse(ctl.is_active(VOICE_TTS_ENGINE))
        voice_release.assert_called_once()

    def test_switch_from_asr_to_voice_releases_asr(self):
        ctl = MemoryController()
        asr_release = MagicMock()
        voice_load = MagicMock(return_value=True)
        ctl.register_handler(ASR_ENGINE, MagicMock(return_value=True), asr_release)
        ctl.register_handler(VOICE_TTS_ENGINE, voice_load, MagicMock())
        ctl.acquire(ASR_ENGINE)
        ctl.switch(VOICE_TTS_ENGINE)
        self.assertTrue(ctl.is_active(VOICE_TTS_ENGINE))
        self.assertFalse(ctl.is_active(ASR_ENGINE))
        asr_release.assert_called_once()


class TestCanAcquire(unittest.TestCase):

    def test_can_acquire_llm_always(self):
        ctl = MemoryController()
        self.assertTrue(ctl.can_acquire(LLM_ENGINE))

    def test_cannot_acquire_voice_when_asr_active_and_budget_tight(self):
        """voice_engine 不能与 ASR 共存 → can_acquire 返回 False"""
        ctl = MemoryController()
        ctl.register_handler(ASR_ENGINE, MagicMock(return_value=True), MagicMock())
        ctl.acquire(ASR_ENGINE)
        self.assertFalse(ctl.can_acquire(VOICE_TTS_ENGINE))

    def test_can_acquire_voice_when_no_conflict(self):
        ctl = MemoryController()
        self.assertTrue(ctl.can_acquire(VOICE_TTS_ENGINE))


class TestSnapshot(unittest.TestCase):

    def test_snapshot_contains_required_fields(self):
        ctl = MemoryController()
        ctl.acquire(LLM_ENGINE)
        snap = ctl.get_snapshot()
        self.assertIn("active_engines", snap)
        self.assertIn("vram_total_gb", snap)
        self.assertIn("vram_allocated_gb", snap)
        self.assertIn("vram_reserved_gb", snap)
        self.assertIn("policy", snap)
        self.assertIn(LLM_ENGINE, snap["active_engines"])

    def test_snapshot_policy_serializable(self):
        """snapshot.policy 可序列化 (供 REST 端点返回)"""
        import json
        ctl = MemoryController()
        snap = ctl.get_snapshot()
        # policy 是 dict of dict, 应可 JSON 序列化
        json.dumps(snap["policy"])
        json.dumps(snap)  # 整个快照可序列化


class TestVramDetection(unittest.TestCase):
    """真实 GPU 检测 (RTX 4060 Laptop 8GB)"""

    def test_detects_8gb_gpu(self):
        ctl = MemoryController()
        if ctl._vram_total_gb is None:
            self.skipTest("无 CUDA GPU, 跳过真实显存检测")
        # RTX 4060 Laptop 应为 8GB (允许 7.9~8.1 容差)
        self.assertAlmostEqual(ctl._vram_total_gb, 8.0, delta=0.2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
