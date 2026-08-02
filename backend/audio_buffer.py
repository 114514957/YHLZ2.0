"""
YHLZ 2.0 音频缓冲管理器
支持淡入淡出，消除断层爆音，提供打断功能
"""

import logging
import time
import numpy as np
from typing import List, Optional
from collections import deque
from .config import config

logger = logging.getLogger(__name__)


class AudioBufferManager:
    """音频缓冲管理器
    支持淡入淡出，消除断层爆音，提供打断功能
    蓝图1.3: 流式收尾哨兵 (is_stream_done) — 播放线程消费 done 后再复位口型,
             被 interrupt 打断的流不产生 done, 口型保持张合
    蓝图1.5: 自播窗口 (回声过滤) — 记录本机播放时间窗, 供决策层丢弃自嗨输入
    """
    
    # 自播窗口 (对齐 NachoBot is_self_danmu 双窗口: 2.5s播放中 / 6s余波)
    SELF_PLAY_GRACE_SEC = 2.5
    SELF_PLAY_TAIL_SEC = 6.0
    
    def __init__(self):
        self.buffer = deque()
        self.current_audio: Optional[np.ndarray] = None
        self.play_position = 0
        self.is_interrupted = False
        self.is_stream_done = False
        self.sample_rate = config.sample_rate
        self.buffer_duration = config.tts_buffer_ms / 1000.0  # 转换为秒
        self.fade_samples = int(self.sample_rate * 0.01)  # 10ms淡入淡出
        self._mouth_open = 0.0
        self._mouth_smoothing_alpha = 0.3
        self._audio_energy_callback = None
        self._play_windows: deque = deque(maxlen=64)  # (start, end) 自播时间窗
    
    def add_audio(self, audio: np.ndarray, sample_rate: int):
        """
        添加音频到缓冲队列
        
        Args:
            audio: 音频数据
            sample_rate: 采样率
        """
        if audio is None or len(audio) == 0:
            return
        
        if sample_rate != self.sample_rate:
            audio = self._resample(audio, sample_rate, self.sample_rate)
        
        self.buffer.append(audio)
        logger.info(f"音频已添加到缓冲，缓冲大小: {len(self.buffer)}")
    
    def get_next_audio(self) -> Optional[np.ndarray]:
        """
        获取下一个要播放的音频
        
        Returns:
            音频数据，如果缓冲为空则返回None
        """
        if self.is_interrupted:
            logger.info(f"音频缓冲被打断，重置状态")
            self.is_interrupted = False
            return None
        
        if self.current_audio is None or self.play_position >= len(self.current_audio):
            if len(self.buffer) > 0:
                self.current_audio = self.buffer.popleft()
                self.play_position = 0
                logger.info(f"从缓冲获取音频: {len(self.current_audio)} samples，缓冲剩余: {len(self.buffer)}")
            else:
                logger.debug(f"缓冲为空，返回None")
                return None
        
        remaining = self.current_audio[self.play_position:]
        self.play_position = len(self.current_audio)
        logger.info(f"返回音频: {len(remaining)} samples")
        return remaining
    
    def interrupt(self):
        """打断当前播放，清空缓冲
        被中断的流不产生 done 哨兵 (蓝图1.3: 口型保持张合, 前端不误复位)
        同时清空自播窗口 (蓝图1.5: 用户已接管说话, 后续输入不再过滤)
        """
        self.is_interrupted = True
        self.is_stream_done = False
        self.buffer.clear()
        self.current_audio = None
        self.play_position = 0
        self.clear_play_windows()
        logger.info("音频播放已打断，缓冲已清空")

    def reset_interrupt(self):
        """重置打断状态"""
        self.is_interrupted = False
    
    # ---------- 流式收尾哨兵 (蓝图1.3) ----------
    
    def mark_stream_done(self):
        """标记当前语音流已正常结束 (TTS生产者每轮合成完成后调用)"""
        self.is_stream_done = True
        logger.info("语音流已标记结束(done哨兵)")
    
    def reset_stream_done(self):
        """清除结束标记 (播放线程消费后复位)"""
        self.is_stream_done = False
    
    # ---------- 自播窗口 / 回声过滤 (蓝图1.5) ----------
    
    def record_play_window(self, duration_sec: float):
        """播放线程每段播放开始时记录自播窗口"""
        now = time.time()
        self._play_windows.append((now, now + max(duration_sec, 0.0)))
    
    def is_within_self_play_window(self, now: Optional[float] = None) -> bool:
        """
        当前时间是否落在本机自播窗口内 (双窗口: 播放前2.5s余量 + 播放结束后6s余波)
        用于丢弃扬声器声音触发的麦克风输入, 防止AI回应自己
        """
        now = now or time.time()
        for start, end in self._play_windows:
            if (start - self.SELF_PLAY_GRACE_SEC) <= now <= (end + self.SELF_PLAY_TAIL_SEC):
                return True
        return False
    
    def clear_play_windows(self):
        """清空自播窗口"""
        self._play_windows.clear()
    
    def clear_buffer(self):
        """清空缓冲"""
        self.buffer.clear()
        self.current_audio = None
        self.play_position = 0
        self.is_stream_done = False
        logger.debug("音频缓冲已清空")
    
    def has_pending_audio(self) -> bool:
        """检查是否有待播放的音频"""
        return (len(self.buffer) > 0 or 
                (self.current_audio is not None and 
                 self.play_position < len(self.current_audio)))
    
    def _apply_fade(self, audio: np.ndarray) -> np.ndarray:
        """
        应用淡入淡出效果
        
        Args:
            audio: 原始音频
        
        Returns:
            处理后的音频
        """
        if len(audio) < self.fade_samples * 2:
            # 音频太短，不应用淡入淡出
            return audio
        
        # 创建副本，避免修改原始数组
        audio_copy = audio.copy()
        
        # 创建淡入淡出窗口
        fade_in = np.linspace(0, 1, self.fade_samples)
        fade_out = np.linspace(1, 0, self.fade_samples)
        
        # 应用淡入
        audio_copy[:self.fade_samples] *= fade_in
        
        # 应用淡出
        audio_copy[-self.fade_samples:] *= fade_out
        
        return audio_copy
    
    def _resample(self, audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
        """
        重采样音频
        
        Args:
            audio: 原始音频
            from_sr: 原采样率
            to_sr: 目标采样率
        
        Returns:
            重采样后的音频
        """
        if from_sr == to_sr:
            return audio
        
        try:
            import scipy.signal
            from math import ceil
            
            # 计算重采样率
            ratio = to_sr / from_sr
            
            # 使用scipy进行重采样
            resampled = scipy.signal.resample(
                audio,
                int(ceil(len(audio) * ratio))
            )
            
            return resampled
            
        except ImportError:
            # 如果没有scipy，使用简单的线性插值
            logger.warning("未安装scipy，使用简单重采样")
            return self._simple_resample(audio, from_sr, to_sr)
    
    def _simple_resample(self, audio: np.ndarray, from_sr: int, to_sr: int) -> np.ndarray:
        """简单重采样（备用方案）"""
        ratio = to_sr / from_sr
        old_len = len(audio)
        new_len = int(old_len * ratio)
        
        # 线性插值
        old_indices = np.linspace(0, old_len - 1, old_len)
        new_indices = np.linspace(0, old_len - 1, new_len)
        
        resampled = np.interp(new_indices, old_indices, audio)
        return resampled
    
    def concat_with_crossfade(self, audio1: np.ndarray, audio2: np.ndarray, crossfade_samples: int) -> np.ndarray:
        """
        交叉淡入淡出拼接两个音频
        
        Args:
            audio1: 第一个音频
            audio2: 第二个音频
            crossfade_samples: 交叉淡入淡出的样本数
        
        Returns:
            拼接后的音频
        """
        if len(audio1) < crossfade_samples or len(audio2) < crossfade_samples:
            return np.concatenate([audio1, audio2])
        
        # 创建交叉淡入淡出窗口
        fade_out = np.linspace(1, 0, crossfade_samples)
        fade_in = np.linspace(0, 1, crossfade_samples)
        
        # 拼接音频
        result = np.zeros(len(audio1) + len(audio2) - crossfade_samples)
        
        # 前一部分
        result[:len(audio1) - crossfade_samples] = audio1[:len(audio1) - crossfade_samples]
        
        # 交叉淡入淡出部分
        result[len(audio1) - crossfade_samples:len(audio1)] = (
            audio1[-crossfade_samples:] * fade_out + audio2[:crossfade_samples] * fade_in
        )
        
        # 后一部分
        result[len(audio1):] = audio2[crossfade_samples:]
        
        return result
    
    def set_audio_energy_callback(self, callback):
        """
        设置音频能量回调函数，用于口型同步
        
        Args:
            callback: 回调函数，接收mouth_open值(0-1)
        """
        self._audio_energy_callback = callback
        logger.info("音频能量回调已设置")
    
    def calculate_mouth_open(self, audio_chunk: np.ndarray) -> float:
        """
        根据音频能量计算口型开合度
        
        Args:
            audio_chunk: 音频数据块
            
        Returns:
            口型开合度 (0-1)
        """
        if audio_chunk is None or len(audio_chunk) == 0:
            return 0.0
        
        energy = np.abs(audio_chunk).mean()
        max_energy = 0.5
        
        raw_mouth_open = min(energy / max_energy, 1.0)
        
        self._mouth_open = self._mouth_open * (1 - self._mouth_smoothing_alpha) + raw_mouth_open * self._mouth_smoothing_alpha
        
        if self._audio_energy_callback:
            try:
                self._audio_energy_callback(self._mouth_open)
            except Exception as e:
                logger.error(f"音频能量回调失败: {e}")
        
        return self._mouth_open
    
    def get_current_mouth_open(self) -> float:
        """获取当前口型开合度"""
        return self._mouth_open
    
    def reset_mouth_open(self):
        """重置口型开合度"""
        self._mouth_open = 0.0


# 全局音频缓冲管理器实例
audio_buffer = AudioBufferManager()
