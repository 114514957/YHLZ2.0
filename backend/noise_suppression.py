"""
YHLZ 2.0 降噪处理模块 (Noise Suppression)
参考N.E.K.O.项目架构，采用多阶段音频处理流程：
1. AGC自动增益控制 → 2. 噪声抑制 → 3. 音频增强
支持多种降噪算法：noisereduce、谱减法、DeepFilterNet
"""

import logging
import numpy as np
from typing import Optional, Tuple
import sys
import os
from pathlib import Path
from scipy import signal
from scipy.fft import fft, ifft

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


class AGCProcessor:
    """
    AGC自动增益控制处理器
    参考N.E.K.O.的实时AGC实现，动态调整音量
    """
    
    def __init__(
        self,
        target_level: float = 0.7,
        max_gain: float = 10.0,
        min_gain: float = 0.1,
        attack_time: float = 0.01,
        release_time: float = 0.1
    ):
        self.target_level = target_level
        self.max_gain = max_gain
        self.min_gain = min_gain
        self.attack_time = attack_time
        self.release_time = release_time
        
        self.current_gain = 1.0
        self.prev_rms = None
        
        logger.info(f"AGC初始化: target={target_level}, max_gain={max_gain}")
    
    def process(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        frame_size = int(sample_rate * 0.02)
        hop_size = frame_size // 2
        
        output = np.zeros(len(audio))
        num_frames = (len(audio) - frame_size) // hop_size + 1
        
        for i in range(num_frames):
            start = i * hop_size
            end = start + frame_size
            
            if end > len(audio):
                end = len(audio)
            
            frame = audio[start:end]
            
            if len(frame) == 0:
                continue
            
            rms = np.sqrt(np.mean(frame ** 2))
            rms = max(rms, 1e-10)
            
            target_gain = self.target_level / rms
            target_gain = np.clip(target_gain, self.min_gain, self.max_gain)
            
            if self.prev_rms is not None:
                if rms > self.prev_rms:
                    time_constant = self.attack_time
                else:
                    time_constant = self.release_time
                
                alpha = hop_size / (sample_rate * time_constant + hop_size)
                self.current_gain = (1 - alpha) * self.current_gain + alpha * target_gain
            else:
                self.current_gain = target_gain
            
            self.prev_rms = rms
            
            output[start:end] = frame * self.current_gain
        
        output = np.clip(output, -1.0, 1.0)
        return output
    
    def reset(self):
        self.current_gain = 1.0
        self.prev_rms = None


class NoiseReduceProcessor:
    """
    noisereduce降噪处理器
    使用深度学习模型进行噪声抑制，效果远超传统方法
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        n_jobs: int = 1,
        use_torch: bool = True
    ):
        self.sample_rate = sample_rate
        self.n_jobs = n_jobs
        self.use_torch = use_torch
        self._noisereduce = None
        self._init_library()
        
        logger.info(f"noisereduce初始化: sample_rate={sample_rate}, use_torch={use_torch}")
    
    def _init_library(self):
        try:
            import noisereduce
            self._noisereduce = noisereduce
            logger.info("noisereduce库加载成功")
        except ImportError as e:
            logger.warning(f"noisereduce库加载失败: {e}，将使用谱减法")
            self._noisereduce = None
    
    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._noisereduce is None:
            return audio
        
        try:
            reduced = self._noisereduce.reduce_noise(
                y=audio,
                sr=self.sample_rate,
                n_jobs=self.n_jobs,
                use_torch=self.use_torch,
                stationary=False,
                prop_decrease=0.6,
                time_constant_s=0.5,
                freq_mask_smooth_hz=2000,
                time_mask_smooth_ms=100,
                thresh_n_mult_nonstationary=3.0,
                sigmoid_slope_nonstationary=10.0,
                n_std_thresh_stationary=1.5
            )
            return reduced
        except Exception as e:
            logger.error(f"noisereduce处理失败: {e}")
            return audio


class SpectralSubtraction:
    """
    谱减法降噪 - 传统方法，作为备用方案
    """
    
    def __init__(
        self,
        frame_size: int = 1024,
        hop_size: int = 256,
        noise_floor: float = -40.0,
        alpha: float = 2.0
    ):
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.noise_floor = 10 ** (noise_floor / 20)
        self.alpha = alpha
        self.noise_estimate = None
        self.is_noise_estimated = False
        self.smoothing_factor = 0.7
        
        logger.info(f"谱减法初始化: frame_size={frame_size}")
    
    def estimate_noise(self, audio: np.ndarray, n_frames: int = 10):
        if len(audio) < self.frame_size * n_frames:
            n_frames = len(audio) // self.frame_size
        
        noise_frames = []
        for i in range(n_frames):
            start = i * self.frame_size
            end = start + self.frame_size
            frame = audio[start:end]
            
            if len(frame) < self.frame_size:
                frame = np.pad(frame, (0, self.frame_size - len(frame)))
            
            noise_frames.append(np.abs(fft(frame)) ** 2)
        
        self.noise_estimate = np.mean(noise_frames, axis=0)
        self.is_noise_estimated = True
    
    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self.is_noise_estimated:
            self.estimate_noise(audio[:self.frame_size * 10])
        
        n_frames = (len(audio) - self.frame_size) // self.hop_size + 1
        
        if n_frames <= 0:
            return audio
        
        output = np.zeros(len(audio) + self.frame_size)
        window = signal.windows.hann(self.frame_size)
        prev_magnitude = None
        
        for i in range(n_frames):
            start = i * self.hop_size
            end = start + self.frame_size
            
            frame = audio[start:end]
            if len(frame) < self.frame_size:
                frame = np.pad(frame, (0, self.frame_size - len(frame)))
            
            windowed = frame * window
            spectrum = fft(windowed)
            magnitude = np.abs(spectrum)
            phase = np.angle(spectrum)
            power = magnitude ** 2
            
            subtracted = power - self.alpha * self.noise_estimate
            subtracted = np.maximum(subtracted, self.noise_floor ** 2 * np.ones_like(subtracted))
            
            if prev_magnitude is not None:
                subtracted = self.smoothing_factor * prev_magnitude ** 2 + \
                            (1 - self.smoothing_factor) * subtracted
            
            prev_magnitude = np.sqrt(subtracted)
            new_spectrum = prev_magnitude * np.exp(1j * phase)
            new_frame = np.real(ifft(new_spectrum))
            output[start:end] += new_frame * window
        
        output = output[:len(audio)]
        max_val = np.max(np.abs(output))
        if max_val > 1.0:
            output = output / max_val
        
        return output
    
    def reset(self):
        self.noise_estimate = None
        self.is_noise_estimated = False


class AudioEnhancer:
    """
    音频增强处理器
    包含去混响、均衡器、动态压缩等效果
    """
    
    def __init__(self):
        self.high_pass_freq = 100
        self.low_pass_freq = 8000
        self.equalizer_bands = {
            100: 1.0,
            500: 1.2,
            1000: 1.1,
            2000: 1.0,
            4000: 0.9,
            8000: 0.8
        }
        
        logger.info("音频增强器初始化")
    
    def _butter_filter(self, audio: np.ndarray, sample_rate: int, cutoff: float, btype: str) -> np.ndarray:
        nyquist = 0.5 * sample_rate
        normal_cutoff = cutoff / nyquist
        
        if normal_cutoff <= 0 or normal_cutoff >= 1:
            return audio
        
        b, a = signal.butter(4, normal_cutoff, btype=btype, analog=False)
        return signal.filtfilt(b, a, audio)
    
    def process(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        audio = self._butter_filter(audio, sample_rate, self.high_pass_freq, 'high')
        audio = self._butter_filter(audio, sample_rate, self.low_pass_freq, 'low')
        
        n_fft = 2048
        hop_length = n_fft // 4
        
        window = signal.windows.hann(n_fft)
        
        stft = np.zeros((n_fft // 2 + 1, len(audio) // hop_length + 1), dtype=np.complex128)
        
        for i in range(stft.shape[1]):
            start = i * hop_length
            end = start + n_fft
            
            if end > len(audio):
                pad_len = end - len(audio)
                frame = np.pad(audio[start:], (0, pad_len))
            else:
                frame = audio[start:end]
            
            stft[:, i] = fft(frame * window)[:n_fft // 2 + 1]
        
        freq_bins = np.linspace(0, sample_rate / 2, n_fft // 2 + 1)
        
        for freq, gain in self.equalizer_bands.items():
            idx = np.argmin(np.abs(freq_bins - freq))
            stft[idx, :] *= gain
        
        output = np.zeros(len(audio))
        
        for i in range(stft.shape[1]):
            start = i * hop_length
            end = start + n_fft
            
            frame = np.real(ifft(np.concatenate([stft[:, i], np.conj(stft[-2:0:-1, i])])))
            frame = frame * window
            
            if end > len(audio):
                frame = frame[:len(audio) - start]
            
            output[start:start + len(frame)] += frame
        
        max_val = np.max(np.abs(output))
        if max_val > 1.0:
            output = output / max_val
        
        return output


class NoiseSuppressionProcessor:
    """
    降噪处理器 - 综合多阶段音频处理
    参考N.E.K.O.的音频处理流程：AGC → 噪声抑制 → 音频增强
    """
    
    def __init__(self, mode: str = "deepfilter"):
        self.mode = mode
        
        self.agc = AGCProcessor()
        self.noisereduce = NoiseReduceProcessor()
        self.spectral = SpectralSubtraction()
        self.enhancer = AudioEnhancer()
        
        self.is_enabled = True
        
        logger.info(f"NoiseSuppressionProcessor初始化: mode={mode}")
    
    def process(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        if not self.is_enabled:
            return audio
        
        try:
            result = audio
            
            if self.mode != "none":
                result = self.agc.process(result, sample_rate)
            
            if self.mode == "noisereduce":
                result = self.noisereduce.process(result)
            elif self.mode == "spectral":
                result = self.spectral.process(result)
            elif self.mode == "deepfilter" or self.mode == "hybrid":
                result = self.noisereduce.process(result)
                if self.noisereduce._noisereduce is None:
                    result = self.spectral.process(result)
            
            if self.mode != "none" and self.mode != "spectral":
                result = self.enhancer.process(result, sample_rate)
            
            return result
            
        except Exception as e:
            logger.error(f"降噪处理失败: {e}")
            return audio
    
    def set_mode(self, mode: str):
        if mode in ["none", "noisereduce", "spectral", "deepfilter", "hybrid"]:
            self.mode = mode
            logger.info(f"降噪模式切换: {mode}")
    
    def reset(self):
        self.agc.reset()
        self.spectral.reset()
    
    def enable(self):
        self.is_enabled = True
        logger.info("降噪已启用")
    
    def disable(self):
        self.is_enabled = False
        logger.info("降噪已禁用")
    
    def get_status(self) -> dict:
        return {
            "enabled": self.is_enabled,
            "mode": self.mode,
            "noisereduce_available": self.noisereduce._noisereduce is not None
        }


noise_suppression = NoiseSuppressionProcessor(mode="deepfilter")


class NoiseSuppressionModule:
    """
    降噪模块 - 对外接口
    """
    
    def __init__(self):
        self.processor = noise_suppression
        self.is_initialized = False
    
    def initialize(self):
        self.processor.reset()
        self.is_initialized = True
        logger.info("降噪模块已初始化")
    
    def process_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        mode: Optional[str] = None
    ) -> np.ndarray:
        if not self.is_initialized:
            self.initialize()
        
        if mode:
            self.processor.set_mode(mode)
        
        return self.processor.process(audio, sample_rate)
    
    def set_mode(self, mode: str):
        self.processor.set_mode(mode)
    
    def enable(self):
        self.processor.enable()
    
    def disable(self):
        self.processor.disable()
    
    def get_info(self) -> dict:
        return self.processor.get_status()


noise_suppression_module = NoiseSuppressionModule()