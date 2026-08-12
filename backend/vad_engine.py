"""
YHLZ 2.0 VAD引擎模块（简化版）
移除Silero VAD依赖，使用纯能量检测方案
配合SenseVoice内置VAD完成语音活动检测
"""

import logging
import numpy as np
from typing import List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.config import config

logger = logging.getLogger(__name__)


class VADEngine:
    """VAD引擎 - 纯能量检测方案，用于实时打断检测"""

    def __init__(self):
        self.is_loaded = False
        
        self.energy_threshold = 0.015
        
        self.enabled = True
        self.interrupt_enabled = True
        self.frame_size = 1600
        
        self.min_voiced_frames = 2
        self.min_unvoiced_frames = 2
        self.hangover_frames = 1
        self.noise_floor = 0.0
        self.noise_adapt_rate = 0.02
        
        self.noise_estimate_history = []
        self.noise_estimate_window = 30
        self.speech_energy_ratio = 3.0
        
        self._state = 'silence'
        self._voiced_count = 0
        self._unvoiced_count = 0
        self._hangover_count = 0
        self._speaking_frames = 0
        
        self._speech_start_time = 0
        self._speech_detected = False
        
        self._confidence_history = []
        self._confidence_threshold = 0.5
        
        self._init_engine()

    def _init_engine(self):
        """初始化VAD引擎（纯能量检测，无需模型加载）"""
        logger.info("VAD引擎初始化完成（纯能量检测模式）")
        self.is_loaded = True

    def _update_noise_floor(self, audio: np.ndarray):
        """更新噪声底噪估计"""
        rms = np.sqrt(np.mean(audio ** 2))
        
        if self._state == 'silence':
            self.noise_estimate_history.append(rms)
            
            if len(self.noise_estimate_history) > self.noise_estimate_window:
                self.noise_estimate_history = self.noise_estimate_history[-self.noise_estimate_window:]
            
            if len(self.noise_estimate_history) > 5:
                median_noise = np.median(self.noise_estimate_history)
                self.noise_floor = (1 - self.noise_adapt_rate) * self.noise_floor + self.noise_adapt_rate * median_noise

    def _energy_based_detection(self, audio: np.ndarray, threshold: float = 0.015) -> bool:
        """
        高级能量检测
        
        1. RMS计算
        2. 自适应噪声底噪
        3. 信噪比阈值
        4. 多帧融合
        """
        if len(audio) == 0:
            return False
        
        rms = np.sqrt(np.mean(audio ** 2))
        
        self._update_noise_floor(audio)
        
        adjusted_threshold = max(threshold, self.noise_floor * self.speech_energy_ratio)
        
        is_speech = rms > adjusted_threshold

        if is_speech:
            logger.debug(f"能量检测：检测到语音，RMS: {rms:.4f}, 阈值: {adjusted_threshold:.4f}, 底噪: {self.noise_floor:.4f}")

        return is_speech

    def detect_speech(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        threshold: float = 0.55
    ) -> bool:
        """
        使用状态机检测语音活动
        
        返回值：当前是否正在说话（用于中断判断）
        """
        if not self.enabled:
            return False

        is_voiced = self._energy_based_detection(audio, threshold=self.energy_threshold)
        confidence = 0.7 if is_voiced else 0.3

        self._confidence_history.append(confidence)
        if len(self._confidence_history) > 10:
            self._confidence_history = self._confidence_history[-10:]

        return self._state_machine(is_voiced)

    def _state_machine(self, is_voiced: bool) -> bool:
        """状态机处理逻辑"""
        if self._state == 'silence':
            if is_voiced:
                self._voiced_count += 1
                if self._voiced_count >= self.min_voiced_frames:
                    self._state = 'speaking'
                    self._voiced_count = 0
                    self._speaking_frames = 0
                    self._speech_detected = True
                    logger.info("VAD状态机：检测到语音开始")
                    return True
            else:
                self._voiced_count = 0
            return False
            
        elif self._state == 'speaking':
            self._speaking_frames += 1
            if is_voiced:
                self._unvoiced_count = 0
                return True
            else:
                self._unvoiced_count += 1
                if self._unvoiced_count >= self.min_unvoiced_frames:
                    self._state = 'hangover'
                    self._unvoiced_count = 0
                    self._hangover_count = 0
                    logger.debug("VAD状态机：进入尾音缓冲")
                return True
                
        elif self._state == 'hangover':
            if is_voiced:
                self._state = 'speaking'
                self._hangover_count = 0
                return True
            else:
                self._hangover_count += 1
                dynamic_hangover = self.hangover_frames
                if self._speaking_frames < 15:
                    dynamic_hangover = max(self.hangover_frames, 3)
                if self._hangover_count >= dynamic_hangover:
                    self._state = 'silence'
                    self._hangover_count = 0
                    self._speech_detected = False
                    self._speaking_frames = 0
                    logger.info("VAD状态机：检测到语音结束")
                    return False
                return True
                
        return False

    def is_speaking(self) -> bool:
        """检查当前是否正在说话"""
        return self._state == 'speaking' or self._state == 'hangover'

    def reset(self):
        """重置状态机"""
        self._state = 'silence'
        self._voiced_count = 0
        self._unvoiced_count = 0
        self._hangover_count = 0
        self._speaking_frames = 0
        self._speech_detected = False
        self._confidence_history = []
        logger.debug("VAD状态机已重置")

    def detect_speech_frames(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        frame_size: int = 1600,
        threshold: float = 0.55
    ) -> List[bool]:
        """分帧检测语音活动"""
        results = []
        num_frames = len(audio) // frame_size

        for i in range(num_frames):
            start = i * frame_size
            end = start + frame_size
            frame = audio[start:end]
            results.append(self.detect_speech(frame, sample_rate, threshold))

        return results

    def unload(self):
        """卸载引擎（兼容接口）"""
        self.is_loaded = False
        logger.info("VAD引擎已卸载")
    
    def get_config(self):
        """获取当前VAD配置"""
        return {
            "enabled": self.enabled,
            "interrupt_enabled": self.interrupt_enabled,
            "energy_threshold": self.energy_threshold,
            "frame_size": self.frame_size,
            "min_voiced_frames": self.min_voiced_frames,
            "min_unvoiced_frames": self.min_unvoiced_frames,
            "hangover_frames": self.hangover_frames,
            "use_fallback": True,
            "vad_type": "energy",
            "current_state": self._state,
            "noise_floor": self.noise_floor,
            "speech_energy_ratio": self.speech_energy_ratio
        }
    
    def set_config(self, config_dict):
        """设置VAD配置"""
        if "enabled" in config_dict:
            self.enabled = config_dict["enabled"]
        if "interrupt_enabled" in config_dict:
            self.interrupt_enabled = config_dict["interrupt_enabled"]
        if "energy_threshold" in config_dict:
            self.energy_threshold = config_dict["energy_threshold"]
        if "frame_size" in config_dict:
            self.frame_size = config_dict["frame_size"]
        if "min_voiced_frames" in config_dict:
            self.min_voiced_frames = config_dict["min_voiced_frames"]
        if "min_unvoiced_frames" in config_dict:
            self.min_unvoiced_frames = config_dict["min_unvoiced_frames"]
        if "hangover_frames" in config_dict:
            self.hangover_frames = config_dict["hangover_frames"]
        if "speech_energy_ratio" in config_dict:
            self.speech_energy_ratio = config_dict["speech_energy_ratio"]
        logger.info(f"VAD配置已更新: {config_dict}")
    
    def load_model(self):
        """加载VAD模型（兼容接口）"""
        if not self.is_loaded:
            self._init_engine()
        return self.is_loaded

    def detect_speech_segment(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        frame_size: int = 1600
    ) -> Optional[np.ndarray]:
        """
        检测并提取语音段
        
        Returns:
            语音段音频数据，如果未检测到语音则返回None
        """
        frames = []
        start_idx = None
        
        num_frames = len(audio) // frame_size
        
        for i in range(num_frames):
            start = i * frame_size
            end = start + frame_size
            frame = audio[start:end]
            
            is_speech = self.detect_speech(frame, sample_rate)
            
            if is_speech and start_idx is None:
                start_idx = max(0, (i - 1) * frame_size)
            
            if is_speech:
                frames.append(frame)
            
            if not is_speech and start_idx is not None and len(frames) > 0:
                break
        
        if frames:
            end_idx = min(len(audio), (num_frames - 1) * frame_size + frame_size)
            speech_segment = audio[start_idx:end_idx]
            logger.info(f"提取语音段: {len(speech_segment)} samples")
            return speech_segment
        
        return None


vad_engine = VADEngine()