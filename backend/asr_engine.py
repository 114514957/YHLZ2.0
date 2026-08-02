"""
YHLZ 2.0 ASR引擎模块
使用faster-whisper进行离线语音识别（支持BatchedInferencePipeline批量处理）
参考NachoBot的Perception API实现和IndexTTS的网络检测机制
优化：批量处理加速、温度调度、动态beam_size、热词支持、置信度过滤
软件增益：音频增强、文本后处理、多pass重识别策略
"""

import logging
import numpy as np
from typing import Optional, Generator, AsyncGenerator, Tuple
import sys
import os
from pathlib import Path
import time
import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor
import queue
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.config import config
from backend.audio_enhancer import audio_enhancer
from backend.text_postprocessor import text_postprocessor

logger = logging.getLogger(__name__)

_network_detection_cache = None
_selected_hf_endpoint = None


def _tcp_latency(host: str, port: int = 443, timeout: float = 3.0):
    try:
        start = time.perf_counter()
        sock = socket.create_connection((host, port), timeout=timeout)
        latency = time.perf_counter() - start
        sock.close()
        return latency
    except (socket.timeout, socket.error, OSError):
        return None


def _test_hf_endpoint(endpoint: str, timeout: float = 5.0) -> tuple:
    """测试HF端点是否可用，返回(可用, 延迟, 下载速度)"""
    try:
        import requests
        url = f"{endpoint}/FunAudioLLM/SenseVoiceSmall/resolve/main/config.yaml"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        start = time.perf_counter()
        response = requests.get(url, timeout=timeout, headers=headers)
        latency = time.perf_counter() - start
        
        if response.status_code == 200:
            content_length = len(response.content)
            download_speed = content_length / latency / 1024 if latency > 0 else 0
            return True, latency, download_speed
        else:
            return False, latency, 0
    except Exception as e:
        return False, timeout, 0


def _select_hf_endpoint() -> str:
    """选择最优的HF端点"""
    global _selected_hf_endpoint
    if _selected_hf_endpoint is not None:
        return _selected_hf_endpoint
    
    env_override = os.environ.get("HF_ENDPOINT", "").strip()
    if env_override:
        logger.info(f"网络检测: 强制使用端点 (HF_ENDPOINT={env_override})")
        _selected_hf_endpoint = env_override
        return env_override
    
    endpoints = [
        ("HF-Mirror", "https://hf-mirror.com"),
        ("ModelScope", "https://modelscope.cn"),
        ("HuggingFace", "https://huggingface.co"),
        ("FastGit", "https://hf.fastgit.org"),
    ]
    
    logger.info("网络检测: 正在测试可用的HF端点...")
    
    results = []
    for name, endpoint in endpoints:
        try:
            available, latency, speed = _test_hf_endpoint(endpoint, timeout=5.0)
            if available:
                logger.info(f"网络检测: {name} ({endpoint}) - 延迟: {latency:.2f}s, 速度: {speed:.2f} KB/s")
                results.append((speed, latency, name, endpoint))
            else:
                logger.debug(f"网络检测: {name} ({endpoint}) - 不可用")
        except Exception as e:
            logger.debug(f"网络检测: {name} ({endpoint}) - 测试失败: {e}")
    
    if results:
        results.sort(key=lambda x: (-x[0], x[1]))
        best_speed, best_latency, best_name, best_endpoint = results[0]
        logger.info(f"网络检测: 选择 {best_name} ({best_endpoint}) - 最优速度: {best_speed:.2f} KB/s")
        _selected_hf_endpoint = best_endpoint
        return best_endpoint
    else:
        logger.warning("网络检测: 所有端点都不可用，使用默认值")
        _selected_hf_endpoint = "https://huggingface.co"
        return "https://huggingface.co"


def _need_proxy(timeout: float = 3.0) -> bool:
    endpoint = _select_hf_endpoint()
    return endpoint != "https://huggingface.co"


class ASREngine:
    def __init__(self):
        self.model = None
        self.pipeline = None
        self.is_loaded = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ASR")
        
        self._stream_buffer = deque(maxlen=15)
        self._stream_queue = queue.Queue(maxsize=100)
        self._stream_active = False
        self._last_recognized_text = ""
        self._stream_start_time = 0
        self._segment_count = 0
        self._context_history = []
        self._context_max_length = 5
        
        self._is_recognizing = False
        self._recognition_task = None
        
        self._incremental_buffer = np.array([], dtype=np.float32)
        self._incremental_overlap = 2400
        self._min_chunk_size = 1600
        
        self._fast_mode = config.asr_fast_mode if hasattr(config, 'asr_fast_mode') else False
        
        self._hotwords = []
        self._language = config.asr_language
        
        self._mode = config.asr_mode
        self._beam_size = config.asr_beam_size
        self._best_of = config.asr_best_of
        self._patience = config.asr_patience
        
        temp_str = config.asr_temperature
        try:
            self._temperature = tuple(float(t) for t in temp_str.split(','))
        except:
            self._temperature = (0.0, 0.1, 0.2)
        
        self._compression_ratio_threshold = config.asr_compression_ratio_threshold
        self._no_speech_threshold = config.asr_no_speech_threshold
        self._log_prob_threshold = config.asr_log_prob_threshold
        self._suppress_tokens = [-1]
        
        self._enable_audio_enhancement = config.asr_audio_enhancement_enabled
        self._enable_text_postprocessing = config.asr_text_postprocessing_enabled
        self._enable_multi_pass = config.asr_multi_pass_enabled
        self._multi_pass_confidence_threshold = config.asr_multi_pass_confidence_threshold
        
        logger.info(f"ASR精度配置已加载: mode={self._mode}, language={self._language}, beam_size={self._beam_size}, best_of={self._best_of}, patience={self._patience}")
        
        self._load_errors = []
    
    def load_model(self, max_retries: int = 3, direct_gpu: bool = False) -> bool:
        if self.is_loaded:
            logger.info("ASR模型已加载，跳过")
            return True
        
        self._load_errors = []
        strategies = ["direct_gpu", "cpu_then_gpu"] if direct_gpu else ["cpu_then_gpu", "direct_gpu"]
        
        for attempt in range(1, max_retries + 1):
            strategy = strategies[attempt % len(strategies)]
            
            logger.info(f"=" * 60)
            logger.info(f"ASR模型加载第 {attempt}/{max_retries} 次尝试")
            logger.info(f"策略: {strategy}")
            logger.info(f"=" * 60)
            
            try:
                self._log_memory_status(f"加载前 (尝试{attempt})")
                
                self._init_model(strategy=strategy)
                
                if self.is_loaded:
                    self._log_memory_status(f"加载成功后 (尝试{attempt})")
                    logger.info(f"[OK] ASR模型加载成功（第{attempt}次尝试，策略: {strategy}）")
                    return True
                
                raise RuntimeError("模型加载后is_loaded仍为False")
            
            except Exception as e:
                import traceback
                error_msg = f"尝试{attempt}失败(策略:{strategy}): {type(e).__name__}: {str(e)}"
                logger.error(f"[FAILED] {error_msg}")
                logger.error(f"详细错误:\n{traceback.format_exc()}")
                
                self._load_errors.append(error_msg)
                
                if attempt < max_retries:
                    self._cleanup_model()
                    wait_time = attempt * 2
                    logger.info(f"等待 {wait_time} 秒后进行第 {attempt + 1} 次尝试...")
                    time.sleep(wait_time)
        
        logger.error(f"=" * 60)
        logger.error(f"ASR模型加载失败（已重试{max_retries}次）")
        logger.error(f"错误列表:")
        for i, err in enumerate(self._load_errors, 1):
            logger.error(f"  {i}. {err}")
        logger.error(f"=" * 60)
        
        return False
    
    def _cleanup_model(self):
        if self.model is not None:
            try:
                del self.model
                import gc
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                logger.info("模型资源已清理")
            except Exception as e:
                logger.warning(f"清理模型资源失败: {e}")
        self.model = None
        self.is_loaded = False
    
    def _log_memory_status(self, context: str = ""):
        try:
            import torch
            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
                reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
                total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                logger.info(f"显存状态 {context}: 已分配={allocated:.2f}GB, 已保留={reserved:.2f}GB, 总量={total:.2f}GB")
        except Exception as e:
            logger.debug(f"获取显存状态失败: {e}")
    
    def _init_model(self, strategy: str = "cpu_then_gpu"):
        asr_model_config = config.asr_model
        
        logger.info(f"ASR模型配置: {asr_model_config}")
        logger.info(f"是否以funasr-开头: {asr_model_config.startswith('funasr-')}")
        
        if asr_model_config.startswith("funasr-"):
            self._init_funasr_model(asr_model_config)
        else:
            self._init_whisper_model(asr_model_config, strategy=strategy)
    
    def _init_funasr_model(self, asr_model_config: str):
        try:
            logger.info("正在初始化FunASR ASR引擎...")
            
            project_cache_dir = Path(__file__).parent.parent / "cache" / "funasr"
            if not project_cache_dir.exists():
                project_cache_dir.mkdir(parents=True, exist_ok=True)
            
            hf_endpoint = _select_hf_endpoint()
            os.environ["HF_ENDPOINT"] = hf_endpoint
            logger.info(f"网络检测: 使用端点 {hf_endpoint}")
            
            os.environ["MODEL_SCOPE_CACHE"] = str(project_cache_dir)
            
            from funasr import AutoModel
            logger.info("FunASR导入成功")
            
            model_name = asr_model_config.replace("funasr-", "")
            if "/" not in model_name:
                model_name = f"iic/{model_name}"

            device = "cuda" if self._check_cuda_available() else "cpu"
            logger.info(f"使用设备: {device}")

            # 优先使用本地缓存的模型
            local_model_paths = [
                Path(f"D:/ModelScope_Models/models/iic--SenseVoiceSmall/snapshots/master"),
                Path.home() / ".cache" / "funasr" / model_name.replace("/", "--"),
                project_cache_dir / model_name.replace("/", "--"),
            ]
            local_model_path = None
            for p in local_model_paths:
                if (p / "model.pt").exists():
                    local_model_path = str(p)
                    logger.info(f"找到本地缓存模型: {local_model_path}")
                    break

            use_fp16 = config.use_fp16 and device == "cuda"

            model_arg = local_model_path if local_model_path else model_name
            logger.info(f"正在加载FunASR模型: {model_arg}")

            self.model = AutoModel(
                model=model_arg,
                model_revision="v2.0.4" if not local_model_path else None,
                vad_model=None,
                punc_model=None,
                device=device,
                download_dir=str(project_cache_dir),
                disable_update=True
            )
            logger.info("已禁用FunASR内置VAD，使用外部Silero VAD进行语音活动检测")
            
            if use_fp16:
                try:
                    self.model.half()
                    logger.info("已启用FP16混合精度，显存占用减少约50%")
                except Exception as e:
                    logger.warning(f"FP16转换失败: {e}")
            
            self.model_name = model_name
            self.device = device
            self.is_loaded = True
            
            logger.info(f"FunASR模型加载成功: {model_name} (设备: {device})")
            logger.info("ASR引擎初始化完成（优化版：极低延迟流式识别）")
            
            self._warmup()
            
        except Exception as e:
            import traceback
            logger.error(f"FunASR模型加载失败: {e}")
            logger.error(f"详细错误: {traceback.format_exc()}")
            logger.warning("回退到openai-whisper模式")
            self._init_whisper_model("openai-whisper-medium")
    
    def _init_whisper_model(self, asr_model_config: str, strategy: str = "cpu_then_gpu"):
        try:
            if asr_model_config.startswith("openai-whisper-"):
                model_size = asr_model_config.replace("openai-whisper-", "")
            else:
                model_size = "medium"
            
            valid_models = ["tiny", "base", "small", "medium", "large", "turbo", "large-v3", "large-v3-turbo"]
            if model_size not in valid_models:
                model_size = "medium"
            
            project_cache_dir = Path(__file__).parent.parent / "cache" / "whisper"
            if not project_cache_dir.exists():
                project_cache_dir.mkdir(parents=True, exist_ok=True)
            
            os.environ["XDG_CACHE_HOME"] = str(Path(__file__).parent.parent / "cache")
            
            import whisper
            logger.info(f"whisper库导入成功")
            
            fallback_models = ["medium", "small", "base", "tiny"]
            if model_size not in fallback_models:
                fallback_models.insert(0, model_size)
            
            loaded_size = None
            loaded_device = None
            
            for fallback_size in fallback_models:
                try:
                    logger.info(f"尝试加载模型: {fallback_size}")
                    
                    has_cuda = self._check_cuda_available()
                    target_device = "cuda" if has_cuda else "cpu"
                    
                    if strategy == "direct_gpu" and has_cuda:
                        logger.info(f"策略: 直接加载到GPU")
                        logger.info(f"开始加载模型到GPU: {fallback_size}")
                        self.model = whisper.load_model(fallback_size, device='cuda')
                        logger.info(f"GPU加载成功")
                        device = "cuda"
                    else:
                        logger.info(f"策略: 先在CPU加载，再迁移到GPU")
                        logger.info(f"开始加载模型到CPU: {fallback_size}")
                        self.model = whisper.load_model(fallback_size, device='cpu')
                        logger.info(f"CPU加载成功")
                        
                        if has_cuda:
                            try:
                                logger.info(f"开始迁移模型到GPU...")
                                self.model = self.model.to('cuda')
                                logger.info(f"GPU迁移成功")
                                device = "cuda"
                            except Exception as e:
                                logger.warning(f"GPU迁移失败，保持CPU模式: {e}")
                                device = "cpu"
                        else:
                            device = "cpu"
                    
                    loaded_size = fallback_size
                    loaded_device = device
                    self.is_loaded = True
                    logger.info(f"openai-whisper模型加载成功: {fallback_size} (设备: {device})")
                    
                    logger.info(f"开始预热...")
                    self._warmup()
                    logger.info(f"预热完成")
                    
                    break
                
                except Exception as e:
                    logger.error(f"模型 {fallback_size} 加载失败: {e}")
                    if self.model is not None:
                        del self.model
                        self.model = None
                    import gc
                    gc.collect()
            
            if self.is_loaded:
                self.model_type = "whisper"
                self.model_size = loaded_size
                self.device = loaded_device
            else:
                logger.error(f"所有模型都加载失败")
            
        except Exception as e:
            logger.error(f"ASR模型加载失败: {e}")
            try:
                import whisper
                logger.info("回退到openai-whisper...")
                model_size = asr_model_config.replace("openai-whisper-", "") if asr_model_config.startswith("openai-whisper-") else "medium"
                device = "cuda" if self._check_cuda_available() else "cpu"
                self.model = whisper.load_model(model_size, device=device)
                self.model_type = "whisper"
                self.model_size = model_size
                self.device = device
                self.is_loaded = True
                logger.info(f"openai-whisper模型加载成功: {model_size} (设备: {device})")
                self._warmup()
            except Exception as fallback_e:
                logger.error(f"openai-whisper也加载失败: {fallback_e}")
                logger.warning("将使用模拟模式")
                self.is_loaded = False
    
    def _check_cuda_available(self) -> bool:
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                logger.info(f"GPU可用: {gpu_name} ({gpu_memory:.1f}GB)")
                return True
        except Exception as e:
            logger.warning(f"GPU检查失败: {e}")
        return False
    
    def _warmup(self):
        if not self.is_loaded or self.model is None:
            return
        
        logger.info("跳过ASR引擎预热（避免崩溃）")
    
    def _update_context(self, text: str):
        if not text or len(text.strip()) < 2:
            return
        
        if self._context_history and self._context_history[-1] == text.strip():
            return
        
        if text.strip() in self._context_history:
            return
        
        self._context_history.append(text.strip())
        if len(self._context_history) > self._context_max_length:
            self._context_history = self._context_history[-self._context_max_length:]
        logger.debug(f"上下文已更新，当前长度: {len(self._context_history)}")
    
    def _get_initial_prompt(self) -> str:
        if not self._context_history:
            return ""
        return " ".join(self._context_history)
    
    def set_hotwords(self, hotwords: list):
        """设置热词列表，提高特定词汇的识别率"""
        self._hotwords = hotwords
        logger.info(f"热词已更新: {hotwords}")
    
    def set_language(self, language: str):
        """设置识别语言"""
        valid_languages = ["zh", "en", "ja", "ko", "yue", "auto"]
        if language in valid_languages:
            self._language = language
            logger.info(f"识别语言已设置为: {language}")
    
    def set_mode(self, mode: str):
        """设置识别模式：speed(速度优先)/balanced(平衡)/accuracy(精度优先)"""
        valid_modes = ["speed", "balanced", "accuracy"]
        if mode in valid_modes:
            self._mode = mode
            if mode == "speed":
                self._beam_size = 1
                self._best_of = 1
                self._temperature = (0.0,)
                self._patience = 0.0
                self._compression_ratio_threshold = 2.4
                self._no_speech_threshold = 0.6
                self._enable_multi_pass = False
                logger.info("识别模式已切换为：速度优先 (beam_size=1, best_of=1, temperature=0.0, 禁用多pass)")
            elif mode == "balanced":
                self._beam_size = 5
                self._best_of = 5
                self._temperature = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
                self._patience = 1.0
                self._compression_ratio_threshold = 2.4
                self._no_speech_threshold = 0.6
                self._enable_multi_pass = True
                logger.info("识别模式已切换为：平衡模式 (beam_size=5, best_of=5, 温度调度, 启用多pass)")
            elif mode == "accuracy":
                self._beam_size = 10
                self._best_of = 10
                self._temperature = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
                self._patience = 1.5
                self._compression_ratio_threshold = 2.4
                self._no_speech_threshold = 0.6
                self._enable_multi_pass = True
                logger.info("识别模式已切换为：精度优先 (beam_size=10, best_of=10, 温度调度, patience=1.5, 启用多pass)")
    
    def _audio_preprocessing(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if sample_rate != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)

        original_audio = audio.copy()

        if self._enable_audio_enhancement:
            try:
                audio = audio_enhancer.enhance(
                    audio,
                    sample_rate=16000,
                    enable_vad=True,
                    enable_noise_suppression=True,
                    enable_compression=True,
                    enable_normalization=True,
                    enable_rnnoise=True,
                    enable_noise_gate=True,
                    fast_mode=self._fast_mode
                )
            except Exception as e:
                logger.warning(f"音频增强失败，使用原始音频: {e}")
                audio = original_audio.copy()

            try:
                from backend.noise_suppression import noise_suppression_module
                audio = noise_suppression_module.process_audio(audio, sample_rate=16000)
            except Exception as e:
                logger.debug(f"降噪模块不可用: {e}")
        else:
            try:
                from backend.noise_suppression import noise_suppression_module
                audio = noise_suppression_module.process_audio(audio, sample_rate=16000)
            except Exception as e:
                energy = np.mean(np.abs(audio))
                if energy < 0.005:
                    gain = min(10.0, 0.005 / (energy + 1e-10))
                    audio = audio * gain

                max_val = np.max(np.abs(audio))
                if max_val > 0:
                    audio = audio / max_val

                try:
                    from scipy import signal
                    b, a = signal.butter(2, 80, 'high', fs=16000)
                    audio = signal.filtfilt(b, a, audio)
                    max_val = np.max(np.abs(audio))
                    if max_val > 0:
                        audio = audio / max_val
                except ImportError:
                    logger.debug("scipy不可用，跳过降噪预处理")
        
        min_samples = 8000
        if len(audio) < min_samples:
            audio = np.pad(audio, (0, min_samples - len(audio)), mode='constant')

        # NaN 安全检查：预处理可能产生 NaN，回退到原始音频
        if np.any(np.isnan(audio)) or np.any(np.isinf(audio)):
            logger.warning("音频预处理产生 NaN/Inf，回退到原始音频")
            audio = original_audio
            if len(audio) < min_samples:
                audio = np.pad(audio, (0, min_samples - len(audio)), mode='constant')

        audio = np.ascontiguousarray(audio, dtype=np.float32)

        return audio
    
    def _noise_gate(self, audio: np.ndarray, threshold: float = 0.003) -> np.ndarray:
        mask = np.abs(audio) >= threshold
        return audio * mask.astype(np.float32)
    
    def _dynamic_range_compression(self, audio: np.ndarray, threshold: float = 0.5, ratio: float = 2.0) -> np.ndarray:
        compressed = np.copy(audio)
        mask = np.abs(audio) > threshold
        compressed[mask] = threshold + (compressed[mask] - threshold) / ratio
        return compressed
    
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str = None) -> str:
        if not self.is_loaded:
            return self._get_mock_transcription()
        
        try:
            future = self._executor.submit(self._transcribe_sync, audio, sample_rate, language)
            text = future.result(timeout=30)
            return text
        except Exception as e:
            logger.error(f"语音识别失败: {type(e).__name__}: {e}")
            return ""
    
    def _estimate_noise_level(self, audio: np.ndarray) -> float:
        frame_size = int(16000 * 0.03)
        hop_size = int(16000 * 0.015)
        
        energies = []
        for i in range(0, len(audio), hop_size):
            frame = audio[i:i+frame_size]
            if len(frame) > 0:
                energies.append(np.mean(frame ** 2))
        
        if energies:
            return np.percentile(energies, 30)
        return 0.0
    
    def _transcribe_sync(self, audio: np.ndarray, sample_rate: int, language: str = None) -> str:
        try:
            audio = self._audio_preprocessing(audio, sample_rate)
            
            noise_level = self._estimate_noise_level(audio)
            if noise_level > 0.005:
                logger.debug(f"检测到较高噪声水平({noise_level:.6f})，应用增强降噪")
                audio = audio_enhancer.enhance(
                    audio, 
                    sample_rate=16000,
                    enable_vad=True,
                    enable_noise_suppression=True,
                    enable_compression=True,
                    enable_normalization=True,
                    enable_rnnoise=True,
                    enable_noise_gate=True,
                    fast_mode=False
                )
            
            target_language = language or self._language
            
            if hasattr(self.model, 'generate'):
                result = self._transcribe_funasr(audio, target_language)
                confidence = None
            elif self.model_type == "faster-whisper" or self.model_type == "whisper":
                result, segments, avg_log_prob = self._transcribe_with_multi_pass(audio, target_language)
                confidence = avg_log_prob
            else:
                result = self._transcribe_with_multi_pass(audio, target_language)
                confidence = None
            
            if confidence is not None and confidence < -0.5:
                logger.debug(f"首次识别置信度过低({confidence:.2f})，尝试增强重识别")
                enhanced_audio = audio_enhancer.enhance(
                    audio,
                    sample_rate=16000,
                    enable_vad=True,
                    enable_noise_suppression=True,
                    enable_compression=True,
                    enable_normalization=True,
                    enable_rnnoise=True,
                    enable_noise_gate=True,
                    fast_mode=False
                )
                
                if hasattr(self.model, 'generate'):
                    retry_result = self._transcribe_funasr(enhanced_audio, target_language)
                else:
                    retry_result, _, retry_confidence = self._transcribe_with_multi_pass(enhanced_audio, target_language)
                
                if retry_result and (not result or len(retry_result) > len(result) * 0.5):
                    logger.debug(f"增强重识别成功，结果更新")
                    result = retry_result
            
            if self._enable_text_postprocessing and result:
                post_result = text_postprocessor.postprocess(result, confidence=confidence)
                result = post_result["cleaned_text"]
                if post_result["suggestions"]:
                    logger.debug(f"文本后处理建议: {post_result['suggestions']}")
            
            if result:
                self._update_context(result)
            
            logger.debug(f"识别结果: {result[:50] if result else '(空)'}")
            return result
            
        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            return ""
    
    def _get_optimal_batch_size(self, audio_length_samples: int) -> int:
        """根据音频长度动态计算最优batch_size_s"""
        sample_rate = 16000
        audio_duration = audio_length_samples / sample_rate
        
        if audio_duration < 5:
            return 30
        elif audio_duration < 15:
            return 60
        elif audio_duration < 30:
            return 90
        elif audio_duration < 60:
            return 120
        else:
            return 180
    
    def _transcribe_funasr(self, audio: np.ndarray, language: str = "zh") -> str:
        try:
            max_30s_samples = 480000
            
            if len(audio) > max_30s_samples:
                logger.info(f"音频超过30秒({len(audio)/16000:.1f}s)，将进行滑窗切分识别")
                chunk_size = 400000
                overlap_size = 80000
                texts = []
                
                for i in range(0, len(audio), chunk_size - overlap_size):
                    chunk = audio[i:i+chunk_size]
                    if len(chunk) < 16000:
                        break
                    
                    gen_kwargs = {
                        "input": chunk,
                        "language": language,
                        "use_itn": False,
                        "remove_pun": False,
                        "batch_size_s": 60,
                        "cache": {},
                    }
                    
                    if self._hotwords:
                        gen_kwargs["hotwords"] = " ".join(self._hotwords)
                    
                    result = self.model.generate(**gen_kwargs)
                    
                    if result and len(result) > 0:
                        raw_text = result[0].get("text", "").strip()
                        if raw_text:
                            try:
                                from funasr.utils.postprocess_utils import rich_transcription_postprocess
                                clean_text = rich_transcription_postprocess(raw_text)
                            except ImportError:
                                clean_text = self._clean_sensevoice_tags(raw_text)
                            texts.append(clean_text)
                
                if texts:
                    return "".join(texts).strip()
                return ""
            
            gen_kwargs = {
                "input": audio,
                "language": language,
                "use_itn": False,
                "remove_pun": False,
                "batch_size_s": 60,
                "cache": {},
            }
            
            if self._hotwords:
                gen_kwargs["hotwords"] = " ".join(self._hotwords)
                logger.debug(f"使用热词: {self._hotwords}")
            
            logger.debug(f"FunASR识别参数: language={language}, use_itn={gen_kwargs['use_itn']}, batch_size_s={gen_kwargs['batch_size_s']}")
            logger.info(f"FunASR输入: {len(audio)} samples, range=[{audio.min():.4f}, {audio.max():.4f}]")

            result = self.model.generate(**gen_kwargs)

            logger.info(f"FunASR原始返回: {result}")
            if result and len(result) > 0:
                raw_text = result[0].get("text", "").strip()
                
                if raw_text:
                    try:
                        from funasr.utils.postprocess_utils import rich_transcription_postprocess
                        text = rich_transcription_postprocess(raw_text)
                        logger.debug(f"SenseVoice原始输出: {raw_text[:50]}")
                        logger.debug(f"清洗后输出: {text[:50]}")
                    except ImportError:
                        text = self._clean_sensevoice_tags(raw_text)
                else:
                    text = ""
                
                if "scores" in result[0] and result[0]["scores"] is not None:
                    scores = result[0]["scores"]
                    if scores and isinstance(scores, list) and len(scores) > 0:
                        avg_score = np.mean(scores)
                        if avg_score < 0.6:
                            logger.warning(f"识别置信度较低({avg_score:.2f})，结果可能不准确")
                
                return text
            
            return ""
        except Exception as e:
            logger.error(f"FunASR识别失败: {e}")
            return ""
    
    def _clean_sensevoice_tags(self, text: str) -> str:
        tags = [
            "<|zh|>", "<|en|>", "<|yue|>", "<|ja|>", "<|ko|>",
            "<|nospeech|>", "<|HAPPY|>", "<|SAD|>", "<|ANGRY|>", "<|NEUTRAL|>",
            "<|Speech|>", "<|BGM|>", "<|Applause|>", "<|Laughter|>",
            "<|Crying|>", "<|Cough|>", "<|Sneeze|>", "<|Breath|>",
        ]
        for tag in tags:
            text = text.replace(tag, "")
        text = re.sub(r'<\|[A-Z_]+\|>', '', text)
        return text.strip()
    
    def _transcribe_whisper(self, audio: np.ndarray, language: str = "zh", 
                          high_accuracy: bool = False) -> tuple:
        try:
            target_language = language if language != "auto" else None
            
            if self.model_type == "faster-whisper":
                initial_prompt = " ".join(self._context_history) if self._context_history else None
                
                beam_size = self._beam_size if not high_accuracy else max(self._beam_size, 15)
                best_of = self._best_of if not high_accuracy else max(self._best_of, 15)
                
                segments, info = self.model.transcribe(
                    audio,
                    language=target_language,
                    initial_prompt=initial_prompt,
                    temperature=self._temperature,
                    condition_on_previous_text=True,
                    vad_filter=True,
                    beam_size=beam_size,
                    best_of=best_of,
                    patience=self._patience,
                    compression_ratio_threshold=self._compression_ratio_threshold,
                    no_speech_threshold=self._no_speech_threshold,
                    log_prob_threshold=self._log_prob_threshold,
                    suppress_tokens=self._suppress_tokens,
                    vad_parameters=dict(min_silence_duration_ms=500),
                    word_timestamps=True,
                    prepend_punctuations="\"'“‘（【《",
                    append_punctuations="\"'”’）】》，。！？、；：",
                )
                
                segments = list(segments)
                full_text = "".join([segment.text for segment in segments]).strip()
                
                avg_log_prob = np.mean([s.avg_logprob for s in segments]) if segments else -1.0
                
                if full_text and avg_log_prob < self._log_prob_threshold:
                    logger.warning(f"识别置信度过低({avg_log_prob:.2f})，可能不准确")
            
            else:
                use_fp16 = (self.device == "cuda")
                initial_prompt = self._get_initial_prompt()
                
                result = self.model.transcribe(
                    audio,
                    language=target_language,
                    fp16=use_fp16,
                    temperature=self._temperature,
                    condition_on_previous_text=True,
                    initial_prompt=initial_prompt if initial_prompt else None,
                    verbose=False
                )
                
                full_text = result.get("text", "").strip()
                
                segments = result.get("segments", [])
                avg_log_prob = np.mean([s.get("avg_logprob", -1) for s in segments]) if segments else -1.0
                
                if full_text and avg_log_prob < self._log_prob_threshold:
                    logger.warning(f"识别置信度过低({avg_log_prob:.2f})，可能不准确")
            
            return full_text, segments, avg_log_prob
            
        except Exception as e:
            logger.error(f"Whisper识别失败: {e}")
            return "", [], -1.0
    
    def _transcribe_with_multi_pass(self, audio: np.ndarray, language: str = "zh") -> tuple:
        """多pass识别策略：先快速识别，低置信度片段用高精度参数重识别"""
        if not self._enable_multi_pass:
            text, segments, avg_log_prob = self._transcribe_whisper(audio, language)
            return text, segments, avg_log_prob
        
        logger.debug("启用多pass识别策略")
        
        text, segments, avg_log_prob = self._transcribe_whisper(audio, language, high_accuracy=False)
        
        if avg_log_prob >= self._multi_pass_confidence_threshold:
            logger.debug(f"单次识别置信度足够({avg_log_prob:.2f})，跳过重识别")
            return text, segments, avg_log_prob
        
        logger.debug(f"首次识别置信度较低({avg_log_prob:.2f})，执行高精度重识别")
        
        high_text, high_segments, high_avg_log_prob = self._transcribe_whisper(audio, language, high_accuracy=True)
        
        if high_avg_log_prob > avg_log_prob:
            logger.info(f"重识别置信度提升: {avg_log_prob:.2f} -> {high_avg_log_prob:.2f}")
            return high_text, high_segments, high_avg_log_prob
        
        return text, segments, avg_log_prob
    
    def transcribe_batch(self, audio_list: list, sample_rate: int = 16000, language: str = None) -> list:
        """批量转录多个音频片段，使用BatchedInferencePipeline加速"""
        if not self.is_loaded or not self.pipeline:
            return [self.transcribe(audio, sample_rate, language) for audio in audio_list]
        
        try:
            processed_list = [self._audio_preprocessing(a, sample_rate) for a in audio_list]
            
            target_language = language if language != "auto" and language else None
            initial_prompt = " ".join(self._context_history) if self._context_history else None
            
            results = self.pipeline.transcribe(
                processed_list,
                language=target_language,
                initial_prompt=initial_prompt,
                temperature=self._temperature,
                condition_on_previous_text=True,
                vad_filter=True,
                beam_size=self._beam_size,
                best_of=self._best_of,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            
            texts = []
            for i, (segments, info) in enumerate(results):
                text = "".join([seg.text for seg in segments]).strip()
                if text:
                    self._update_context(text)
                texts.append(text)
            
            logger.info(f"批量转录完成，处理{len(audio_list)}个音频片段")
            return texts
            
        except Exception as e:
            logger.error(f"批量转录失败: {e}")
            return [self.transcribe(audio, sample_rate, language) for audio in audio_list]
    
    def _get_mock_transcription(self) -> str:
        import random
        mock_texts = [
            "你好，今天天气怎么样？",
            "给我讲个笑话吧。",
            "播放一首音乐。",
            "设置一个闹钟。",
            "今天有什么新闻？",
            "你叫什么名字？",
            "谢谢",
            "再见",
            "你好",
            "介绍一下你自己",
            "讲个故事",
            "明天天气怎么样",
            "帮我查一下",
            "我想聊天",
            "今天心情不错",
            "有什么好玩的",
            "最近有什么电影推荐",
            "帮我查一下天气",
            "讲个笑话",
            "你会什么"
        ]
        return random.choice(mock_texts)
    
    def unload(self):
        self.stop_streaming()
        if self.model is not None:
            del self.model
            self.model = None
            self.is_loaded = False
        if self._executor:
            self._executor.shutdown(wait=True)
    
    def start_streaming(self):
        logger.info("启动流式ASR识别（极低延迟模式）")
        self._stream_active = True
        self._stream_buffer = deque(maxlen=15)
        self._stream_queue = queue.Queue(maxsize=100)
        self._last_recognized_text = ""
        self._stream_start_time = time.time()
        self._segment_count = 0
        self._incremental_buffer = np.array([], dtype=np.float32)
    
    def stop_streaming(self):
        logger.info("停止流式ASR识别")
        self._stream_active = False
        self._incremental_buffer = np.array([], dtype=np.float32)
        while not self._stream_queue.empty():
            try:
                self._stream_queue.get_nowait()
            except queue.Empty:
                pass
    
    def stream_audio(self, audio_chunk: np.ndarray):
        if not self._stream_active:
            return
        
        self._incremental_buffer = np.concatenate([self._incremental_buffer, audio_chunk])
        
        while len(self._incremental_buffer) >= self._min_chunk_size:
            audio_to_process = self._incremental_buffer[:self._min_chunk_size * 3].copy()
            
            overlap = min(self._incremental_overlap, len(self._incremental_buffer) - self._min_chunk_size)
            self._incremental_buffer = self._incremental_buffer[self._min_chunk_size - overlap:]
            
            future = self._executor.submit(
                self._transcribe_sync, audio_to_process, 16000
            )
            
            def callback(fut):
                try:
                    result = fut.result()
                    if result and result.strip():
                        new_text = self._extract_new_text(result.strip())
                        if new_text:
                            self._stream_queue.put(new_text)
                except Exception as e:
                    logger.error(f"流式识别回调错误: {e}")
            
            future.add_done_callback(callback)
    
    def _extract_new_text(self, full_text: str) -> str:
        if full_text.startswith(self._last_recognized_text):
            new_part = full_text[len(self._last_recognized_text):]
            if new_part:
                self._last_recognized_text = full_text
                return new_part
        self._last_recognized_text = full_text
        return full_text
    
    def get_stream_result(self) -> Optional[str]:
        try:
            return self._stream_queue.get_nowait()
        except queue.Empty:
            return None
    
    async def async_stream_transcribe(self, audio_chunks: AsyncGenerator[np.ndarray, None]):
        self.start_streaming()
        buffer = np.array([], dtype=np.float32)
        accumulated_text = ""
        
        try:
            async for chunk in audio_chunks:
                if not self._stream_active:
                    break
                
                buffer = np.concatenate([buffer, chunk])
                
                while len(buffer) >= self._min_chunk_size:
                    audio_to_process = buffer[:self._min_chunk_size * 3].copy()
                    buffer = buffer[self._min_chunk_size:]
                    
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        self._executor,
                        self._transcribe_sync,
                        audio_to_process,
                        16000
                    )
                    
                    if result and result.strip():
                        if result.strip().startswith(accumulated_text):
                            new_text = result.strip()[len(accumulated_text):]
                            if new_text:
                                accumulated_text = result.strip()
                                yield new_text
                        else:
                            accumulated_text = result.strip()
                            yield result.strip()
            
            if len(buffer) > 500 and self._stream_active:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    self._transcribe_sync,
                    buffer,
                    16000
                )
                
                if result and result.strip():
                    if result.strip().startswith(accumulated_text):
                        new_text = result.strip()[len(accumulated_text):]
                        if new_text:
                            yield new_text
                    else:
                        yield result.strip()
        finally:
            self.stop_streaming()
    
    async def stream_transcribe_continuous(self) -> AsyncGenerator[str, None]:
        while self._stream_active:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._stream_queue.get,
                    True,
                    1.0
                )
                if result:
                    yield result
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"持续流式识别错误: {e}")
                break


asr_engine = ASREngine()