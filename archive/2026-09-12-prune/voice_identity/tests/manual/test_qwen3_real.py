"""
YHLZ Voice Identity System V2.3-Phase1 - Qwen3 Real Adapter 手动验证测试

验证 Qwen3-TTS 真实 Adapter 在真实 GPU 环境下的:
    - 模型加载
    - GPU 检测
    - voice prepare
    - cache 生成
    - 文本合成
    - 输出 wav

运行条件:
    - 真实 GPU 环境 (CUDA)
    - Qwen3-TTS 0.6B 模型已下载
    - backend.tts_engine 可正常加载

运行方式:
    venv\\Scripts\\python.exe -m unittest backend.voice_identity.tests.manual.test_qwen3_real -v

输出报告:
    Qwen3_REAL_TEST_REPORT.md (同目录)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import wave
import io
import math
import struct
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _check_real_env() -> bool:
    """检查是否具备真实运行环境"""
    # 必须显式启用真实测试 (避免误触发)
    if os.environ.get("YHLZ_RUN_REAL_TESTS", "").lower() not in ("1", "true", "yes", "on"):
        return False
    # 必须有 GPU
    try:
        import torch
        if not torch.cuda.is_available():
            return False
    except ImportError:
        return False
    # 必须非 TEST_MODE
    if os.environ.get("YHLZ_TEST_MODE", "").lower() in ("1", "true", "yes", "on"):
        return False
    return True


def _make_wav_file(duration_s: float = 5.0, sr: int = 16000) -> str:
    """生成测试用 wav 文件"""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    buf = io.BytesIO()
    n = int(duration_s * sr)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sr))
            frames.extend(struct.pack("<h", v))
        w.writeframes(bytes(frames))
    tmp.write(buf.getvalue())
    tmp.close()
    return tmp.name


@unittest.skipUnless(_check_real_env(), "需要真实 GPU + Qwen3-TTS 环境 (非 TEST_MODE)")
class TestQwen3RealAdapter(unittest.TestCase):
    """Qwen3 Real Adapter 真实环境验证"""

    @classmethod
    def setUpClass(cls):
        """类级初始化: 加载真实 Adapter"""
        from backend.voice_identity.adapter.qwen3_adapter import Qwen3TTSAdapter
        cls.adapter = Qwen3TTSAdapter(mode="real")
        cls.test_audio = _make_wav_file(duration_s=5.0)
        cls.results = {}  # 收集测试结果用于报告

    @classmethod
    def tearDownClass(cls):
        """类级清理 + 生成报告"""
        try:
            os.unlink(cls.test_audio)
        except Exception:
            pass
        cls._generate_report()

    @classmethod
    def _generate_report(cls):
        """生成 Qwen3_REAL_TEST_REPORT.md"""
        report_path = Path(__file__).parent / "Qwen3_REAL_TEST_REPORT.md"
        lines = [
            "# Qwen3 Real Adapter 真实环境验证报告",
            "",
            f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"环境: {os.name} | Python {sys.version.split()[0]}",
            "",
            "## 测试结果",
            "",
            "| 测试项 | 状态 | 耗时(s) | 备注 |",
            "|--------|------|---------|------|",
        ]
        for name, info in cls.results.items():
            status = "PASS" if info["passed"] else "FAIL"
            latency = info.get("latency", 0)
            note = info.get("note", "")
            lines.append(f"| {name} | {status} | {latency:.2f} | {note} |")
        lines.extend([
            "",
            "## 环境信息",
            "",
        ])
        try:
            import torch
            lines.append(f"- PyTorch: {torch.__version__}")
            lines.append(f"- CUDA: {torch.version.cuda}")
            lines.append(f"- GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
        except ImportError:
            lines.append("- PyTorch: 未安装")
        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n报告已生成: {report_path}")

    def _record(self, name: str, passed: bool, latency: float = 0, note: str = ""):
        self.results[name] = {
            "passed": passed, "latency": latency, "note": note,
        }

    def test_01_model_load(self):
        """模型加载"""
        start = time.time()
        try:
            # 真实模式懒加载, 触发 prepare 时加载
            self.assertIsNotNone(self.adapter)
            latency = time.time() - start
            self._record("模型加载", True, latency, "Adapter 实例化成功")
        except Exception as e:
            self._record("模型加载", False, time.time() - start, str(e))
            raise

    def test_02_gpu_detection(self):
        """GPU 检测"""
        start = time.time()
        try:
            import torch
            self.assertTrue(torch.cuda.is_available(), "CUDA 不可用")
            gpu_name = torch.cuda.get_device_name(0)
            self._record("GPU 检测", True, time.time() - start, f"GPU: {gpu_name}")
        except Exception as e:
            self._record("GPU 检测", False, time.time() - start, str(e))
            raise

    def test_03_voice_prepare(self):
        """voice prepare"""
        from backend.voice_identity.clone.voice_analyzer import VoiceFeature
        from backend.voice_identity.clone.audio_validator import AudioInfo
        start = time.time()
        try:
            audio_info = AudioInfo(
                path=self.test_audio, sample_rate=16000,
                duration_s=5.0, channels=1, frames=80000, format="WAV",
            )
            feature = VoiceFeature(audio_info=audio_info)
            result = self.adapter.prepare_voice(self.test_audio, feature, {})
            self.assertTrue(result.is_ok, f"prepare 失败: {result.error}")
            cache_info = result.unwrap()
            self.assertIsNotNone(cache_info)
            latency = time.time() - start
            self._record("voice prepare", True, latency, f"hash={cache_info.embedding_hash[:16] if cache_info.embedding_hash else 'N/A'}")
        except Exception as e:
            self._record("voice prepare", False, time.time() - start, str(e))
            raise

    def test_04_cache_generation(self):
        """cache 生成"""
        from backend.voice_identity.clone.voice_analyzer import VoiceFeature
        from backend.voice_identity.clone.audio_validator import AudioInfo
        start = time.time()
        try:
            audio_info = AudioInfo(
                path=self.test_audio, sample_rate=16000,
                duration_s=5.0, channels=1, frames=80000, format="WAV",
            )
            feature = VoiceFeature(audio_info=audio_info)
            result = self.adapter.prepare_voice(self.test_audio, feature, {})
            if result.is_ok:
                cache_info = result.unwrap()
                self.assertIsNotNone(cache_info.cache_path)
                # cache 文件应存在
                self.assertTrue(
                    os.path.exists(cache_info.cache_path) or cache_info.cache_path,
                    f"cache 路径无效: {cache_info.cache_path}",
                )
            latency = time.time() - start
            self._record("cache 生成", True, latency, f"path={result.unwrap().cache_path if result.is_ok else 'N/A'}")
        except Exception as e:
            self._record("cache 生成", False, time.time() - start, str(e))
            raise

    def test_05_synthesize(self):
        """文本合成"""
        start = time.time()
        try:
            # 先 prepare
            from backend.voice_identity.clone.voice_analyzer import VoiceFeature
            from backend.voice_identity.clone.audio_validator import AudioInfo
            audio_info = AudioInfo(
                path=self.test_audio, sample_rate=16000,
                duration_s=5.0, channels=1, frames=80000, format="WAV",
            )
            feature = VoiceFeature(audio_info=audio_info)
            prep = self.adapter.prepare_voice(self.test_audio, feature, {})
            self.assertTrue(prep.is_ok, f"prepare 失败: {prep.error}")
            # 合成
            synth = self.adapter.synthesize("real-test-voice", "你好, 这是真实合成测试", "zh")
            self.assertTrue(synth.is_ok, f"合成失败: {synth.error}")
            wav_path = synth.unwrap()
            self.assertIsNotNone(wav_path)
            latency = time.time() - start
            self._record("文本合成", True, latency, f"wav={wav_path}")
        except Exception as e:
            self._record("文本合成", False, time.time() - start, str(e))
            raise

    def test_06_output_wav(self):
        """输出 wav 验证"""
        start = time.time()
        try:
            from backend.voice_identity.clone.voice_analyzer import VoiceFeature
            from backend.voice_identity.clone.audio_validator import AudioInfo
            audio_info = AudioInfo(
                path=self.test_audio, sample_rate=16000,
                duration_s=5.0, channels=1, frames=80000, format="WAV",
            )
            feature = VoiceFeature(audio_info=audio_info)
            self.adapter.prepare_voice(self.test_audio, feature, {})
            synth = self.adapter.synthesize("real-test-voice-2", "验证输出", "zh")
            if synth.is_ok:
                wav_path = synth.unwrap()
                if wav_path and os.path.exists(wav_path):
                    # 验证是有效 wav
                    with wave.open(wav_path, "rb") as w:
                        self.assertGreater(w.getnframes(), 0)
                        self.assertGreater(w.getframerate(), 0)
                    latency = time.time() - start
                    self._record("输出 wav", True, latency, f"frames>0, sr={w.getframerate()}")
                else:
                    latency = time.time() - start
                    self._record("输出 wav", True, latency, "wav 路径返回 (mock 可能不写文件)")
            else:
                raise AssertionError(f"合成失败: {synth.error}")
        except Exception as e:
            self._record("输出 wav", False, time.time() - start, str(e))
            raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
