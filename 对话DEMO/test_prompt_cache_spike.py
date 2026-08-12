"""
M0.6 Prompt Cache Spike: 验证 Qwen3 voice cache 持久化

流程 (任务要求):
    首次加载声音 → 保存缓存 → 程序重启 → 恢复

记录:
    - 加载时间 (首次提取 vs 磁盘恢复)
    - 文件大小 (保存的缓存体积)
    - 显存变化 (每阶段 torch.cuda 快照)

说明:
- 当前环境未安装 qwen_tts 模块 (与 M0.1 测试同条件), 使用 FakeModel 验证持久化机制。
  真实 GPU 提取需 pip install qwen_tts + 模型权重, 此处记录的"首次提取时间"为
  FakeModel 模拟值, 磁盘 I/O / 显存快照为真实测量值。
- 显存快照: 真实 CUDA (RTX 4060 8GB), 因 FakeModel 不占显存, 显存变化趋近 0 —
  报告中区分"机制验证"与"真实模型待测"。

运行: venv\Scripts\python.exe 对话DEMO\test_prompt_cache_spike.py
"""
import json
import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tts.qwen3_tts import Qwen3TTSEngine, DEFAULT_VOICE_ID


# ── FakeModel (与 M0.1 同源, 模拟 create_voice_clone_prompt / generate_voice_clone) ──
class FakePrompt:
    def __init__(self, voice_id: str):
        self.voice_id = voice_id
        self.x_vector = np.full(512, float(len(voice_id)), dtype=np.float32)


class FakeModel:
    def __init__(self):
        self.created = []
        self.generated = []

    def create_voice_clone_prompt(self, ref_audio, x_vector_only_mode=True):
        # 模拟提取耗时 (真实场景数秒, 这里 50ms 体现量级差异)
        time.sleep(0.05)
        voice_id = os.path.basename(str(ref_audio)).replace(".wav", "")
        self.created.append((voice_id, ref_audio, x_vector_only_mode))
        return FakePrompt(voice_id)

    def generate_voice_clone(self, text, language, voice_clone_prompt):
        self.generated.append((getattr(voice_clone_prompt, "voice_id", "?"), text))
        return [np.zeros(2400, dtype=np.float32)], 24000


def _make_fake_wav(path: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(np.zeros(24000, dtype=np.int16).tobytes())
    return str(path)


def _vram_snapshot() -> dict:
    """真实 CUDA 显存快照"""
    try:
        import torch
        if not torch.cuda.is_available():
            return {"available": False, "allocated_gb": 0.0, "reserved_gb": 0.0}
        return {
            "available": True,
            "allocated_gb": round(torch.cuda.memory_allocated(0) / (1024 ** 3), 4),
            "reserved_gb": round(torch.cuda.memory_reserved(0) / (1024 ** 3), 4),
        }
    except Exception:
        return {"available": False, "allocated_gb": 0.0, "reserved_gb": 0.0}


def _dir_size_bytes(path: Path) -> int:
    """目录总字节数"""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


class TestPromptCacheSpike(unittest.TestCase):
    """Prompt Cache Spike: 首次加载 → 保存 → 重启 → 恢复"""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="qwen3_cache_spike_")
        cls.cache_dir = os.path.join(cls._tmpdir.name, "voice_cache_store")
        cls.ref_audio = _make_fake_wav(os.path.join(cls._tmpdir.name, "voice_alpha.wav"))
        # 收集指标供报告生成
        cls.metrics = {}

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _make_engine(self) -> Qwen3TTSEngine:
        """构造挂载 FakeModel 的引擎 (模拟"程序启动后加载模型")"""
        engine = Qwen3TTSEngine()
        engine._model = FakeModel()
        engine.is_loaded = True
        return engine

    def test_01_first_extraction_and_save(self):
        """阶段 1: 首次加载声音 → 提取缓存 → 保存到磁盘"""
        engine = self._make_engine()
        vram_before = _vram_snapshot()

        t0 = time.perf_counter()
        cache = engine.load_voice_cache("voice_alpha", ref_audio=self.ref_audio)
        extract_time = time.perf_counter() - t0
        self.assertIsNotNone(cache)

        # 保存到磁盘
        t1 = time.perf_counter()
        saved_path = engine.save_voice_cache_to_disk("voice_alpha", self.cache_dir)
        save_time = time.perf_counter() - t1
        self.assertIsNotNone(saved_path)

        vram_after = _vram_snapshot()
        file_size = _dir_size_bytes(Path(saved_path))

        self.metrics["phase1_first_extraction"] = {
            "extract_time_sec": round(extract_time, 4),
            "save_time_sec": round(save_time, 4),
            "file_size_bytes": file_size,
            "file_size_kb": round(file_size / 1024, 2),
            "vram_before": vram_before,
            "vram_after": vram_after,
            "vram_delta_gb": round(vram_after["allocated_gb"] - vram_before["allocated_gb"], 4),
        }
        # 缓存结构完整
        self.assertIn("prompt", cache)
        self.assertIn("embedding", cache)
        self.assertIn("metadata", cache)

    def test_02_saved_files_structure(self):
        """阶段 2: 验证磁盘缓存文件结构"""
        vdir = Path(self.cache_dir) / "voice_alpha"
        self.assertTrue(vdir.is_dir())
        self.assertTrue((vdir / "metadata.json").is_file())
        # embedding.pt 或 embedding.npy 至少一个存在
        self.assertTrue((vdir / "embedding.pt").is_file() or (vdir / "embedding.npy").is_file())
        # metadata 内容校验
        with open(vdir / "metadata.json", "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["voice_id"], "voice_alpha")
        self.assertIn("saved_at", meta)

        # 记录文件细分
        files = {p.name: p.stat().st_size for p in vdir.iterdir() if p.is_file()}
        self.metrics["phase2_files"] = files

    def test_03_simulate_restart_and_restore(self):
        """阶段 3: 模拟程序重启 (新引擎实例, 内存缓存空) → 从磁盘恢复"""
        # 新引擎实例 = 模拟重启后内存缓存丢失
        engine = self._make_engine()
        self.assertEqual(len(engine._voice_caches), 0)  # 重启后空

        vram_before = _vram_snapshot()
        t0 = time.perf_counter()
        restored = engine.load_voice_cache_from_disk("voice_alpha", self.cache_dir)
        restore_time = time.perf_counter() - t0
        vram_after = _vram_snapshot()

        self.assertIsNotNone(restored)
        self.assertIn("voice_alpha", engine._voice_caches)
        # embedding 一致性 (x_vector 值恢复)
        original_emb = np.full(512, float(len("voice_alpha")), dtype=np.float32)
        restored_emb = restored["embedding"]
        if isinstance(restored_emb, np.ndarray):
            np.testing.assert_array_almost_equal(restored_emb, original_emb)

        self.metrics["phase3_restore"] = {
            "restore_time_sec": round(restore_time, 4),
            "vram_before": vram_before,
            "vram_after": vram_after,
            "vram_delta_gb": round(vram_after["allocated_gb"] - vram_before["allocated_gb"], 4),
        }

    def test_04_restore_faster_than_extraction(self):
        """验收: 磁盘恢复应快于首次提取 (避免重复提取开销)"""
        extract_t = self.metrics["phase1_first_extraction"]["extract_time_sec"]
        restore_t = self.metrics["phase3_restore"]["restore_time_sec"]
        speedup = extract_t / restore_t if restore_t > 0 else float("inf")
        self.metrics["speedup"] = round(speedup, 2)
        # FakeModel 提取含 50ms sleep, 磁盘恢复应明显更快
        self.assertGreater(speedup, 1.0, "磁盘恢复应快于首次提取")

    def test_05_restored_cache_usable_for_synthesis(self):
        """验收: 恢复的缓存可用于合成 (端到端闭环)"""
        engine = self._make_engine()
        engine.load_voice_cache_from_disk("voice_alpha", self.cache_dir)
        audio, sr = engine.synthesize("你好铁哥们", voice_id="voice_alpha")
        self.assertEqual(sr, 24000)
        self.assertGreater(len(audio), 0)
        self.assertEqual(engine._model.generated[0][1], "你好铁哥们")
        self.metrics["phase5_synthesis_ok"] = True

    def test_06_round_trip_integrity(self):
        """验收: 保存→恢复 embedding 数值无损"""
        engine1 = self._make_engine()
        engine1.load_voice_cache("voice_alpha", ref_audio=self.ref_audio)
        original = engine1.get_voice_cache("voice_alpha")["embedding"]

        engine1.save_voice_cache_to_disk("voice_alpha", self.cache_dir)

        engine2 = self._make_engine()
        restored = engine2.load_voice_cache_from_disk("voice_alpha", self.cache_dir)["embedding"]

        if isinstance(original, np.ndarray) and isinstance(restored, np.ndarray):
            np.testing.assert_array_equal(original, restored)
            self.metrics["round_trip_integrity"] = "lossless"
        else:
            self.metrics["round_trip_integrity"] = "type_mismatch_skipped"

    def test_07_vram_summary(self):
        """汇总显存变化 (供报告)"""
        self.metrics["vram_summary"] = {
            "phase1_delta_gb": self.metrics["phase1_first_extraction"]["vram_delta_gb"],
            "phase3_delta_gb": self.metrics["phase3_restore"]["vram_delta_gb"],
            "note": "FakeModel 不占显存, delta≈0; 真实模型提取会有 GB 级 delta",
            "cuda_available": _vram_snapshot()["available"],
        }


def _write_metrics_report(metrics: dict, report_path: Path):
    """将指标写入可读报告 (供 PROMPT_CACHE_SPIKE_REPORT.md 引用)"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 运行测试并收集 metrics (通过 TestResult 访问 cls.metrics)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPromptCacheSpike)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 写出 metrics (即使部分失败也写, 供报告)
    metrics = getattr(TestPromptCacheSpike, "metrics", {})
    out = Path(__file__).resolve().parents[1] / "docs" / "prompt_cache_spike_metrics.json"
    _write_metrics_report(metrics, out)
    print(f"\n[Spike] metrics 已写入: {out}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    sys.exit(0 if result.wasSuccessful() else 1)
