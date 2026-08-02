"""
YHLZ 2.0 回声消除模块 (Acoustic Echo Cancellation)
使用自适应滤波器消除扬声器回声，提高近场语音识别率
"""

import logging
import numpy as np
from typing import Optional, Tuple
import sys
from pathlib import Path
from scipy import signal

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


class AdaptiveEchoCanceller:
    """
    自适应回声消除器
    使用NLMS (Normalized Least Mean Squares) 算法
    """
    
    def __init__(
        self,
        filter_length: int = 4096,
        step_size: float = 0.5,
        leakage: float = 0.99,
        eps: float = 1e-8
    ):
        """
        初始化自适应回声消除器
        
        Args:
            filter_length: 滤波器长度
            step_size: 步长参数 (0 < step_size <= 1)
            leakage: 泄漏因子
            eps: 归一化参数
        """
        self.filter_length = filter_length
        self.step_size = step_size
        self.leakage = leakage
        self.eps = eps
        
        # 滤波器系数
        self.w = np.zeros(filter_length)
        
        # 延迟估计（用于处理因果系统）
        self.delay_estimate = 0
        
        # 状态
        self.is_enabled = True
        self.reference_buffer = np.zeros(filter_length)
        
        logger.info(f"AEC初始化: filter_length={filter_length}, step_size={step_size}")
    
    def process(
        self,
        mic_signal: np.ndarray,
        reference_signal: np.ndarray
    ) -> Tuple[np.ndarray, float]:
        """
        处理音频信号，消除回声
        
        Args:
            mic_signal: 麦克风信号（含回声）
            reference_signal: 参考信号（扬声器输出）
        
        Returns:
            (enhanced_signal, echo_return_loss) - 增强后的信号和回声衰减量
        """
        if not self.is_enabled:
            return mic_signal, 0.0
        
        try:
            # 确保输入是连续的numpy数组
            mic_signal = np.ascontiguousarray(mic_signal, dtype=np.float32)
            reference_signal = np.ascontiguousarray(reference_signal, dtype=np.float32)
            
            output_signal = np.zeros_like(mic_signal)
            erl_values = []
            
            # 逐样本处理
            for i in range(len(mic_signal)):
                # 更新参考信号缓冲区
                self.reference_buffer = np.roll(self.reference_buffer, 1)
                self.reference_buffer[0] = reference_signal[i] if i < len(reference_signal) else 0
                
                # 获取滤波器输入向量
                x = self.reference_buffer[:self.filter_length]
                
                # 计算估计的回声
                echo_estimate = np.dot(self.w, x)
                
                # 计算误差（麦克风信号 - 估计的回声）
                error = mic_signal[i] - echo_estimate
                
                # 更新滤波器系数 (NLMS算法)
                norm = np.dot(x, x) + self.eps
                self.w += self.step_size * error * x / norm
                
                # 应用泄漏
                self.w *= self.leakage
                
                # 输出增强后的信号
                output_signal[i] = error
                
                # 计算回声衰减
                if abs(mic_signal[i]) > self.eps:
                    erl = 10 * np.log10((mic_signal[i] ** 2) / max(error ** 2, self.eps))
                    erl_values.append(erl)
            
            avg_erl = np.mean(erl_values) if erl_values else 0.0
            
            return output_signal, avg_erl
            
        except Exception as e:
            logger.error(f"AEC处理失败: {e}")
            return mic_signal, 0.0
    
    def reset(self):
        """重置滤波器状态"""
        self.w = np.zeros(self.filter_length)
        self.reference_buffer = np.zeros(self.filter_length)
        logger.info("AEC滤波器已重置")
    
    def enable(self):
        """启用AEC"""
        self.is_enabled = True
        logger.info("AEC已启用")
    
    def disable(self):
        """禁用AEC"""
        self.is_enabled = False
        logger.info("AEC已禁用")
    
    def set_parameters(
        self,
        filter_length: Optional[int] = None,
        step_size: Optional[float] = None,
        leakage: Optional[float] = None
    ):
        """动态调整AEC参数"""
        if filter_length is not None:
            if filter_length != self.filter_length:
                old_filter_length = self.filter_length
                self.filter_length = filter_length
                self.w = np.zeros(filter_length)
                self.reference_buffer = np.zeros(filter_length)
                logger.info(f"AEC filter_length: {old_filter_length} -> {filter_length}")
        
        if step_size is not None:
            self.step_size = max(0.0001, min(1.0, step_size))
            logger.info(f"AEC step_size: {self.step_size}")
        
        if leakage is not None:
            self.leakage = max(0.9, min(0.9999, leakage))
            logger.info(f"AEC leakage: {self.leakage}")


class FrequencyDomainEchoCanceller:
    """
    频域回声消除器
    使用频域自适应滤波器(FAF)，适合处理长脉冲响应
    """
    
    def __init__(
        self,
        block_size: int = 512,
        filter_length: int = 4096,
        mu: float = 0.5,
        forgetting_factor: float = 0.98
    ):
        """
        初始化频域回声消除器
        
        Args:
            block_size: 块大小（FFT长度）
            filter_length: 滤波器长度
            mu: 步长
            forgetting_factor: 遗忘因子
        """
        self.block_size = block_size
        self.filter_length = filter_length
        self.mu = mu
        self.forgetting_factor = forgetting_factor
        
        # FFT/IFFT长度
        self.fft_size = block_size * 2
        self.filter_size = filter_length // block_size + 1
        
        # 频域滤波器系数
        self.W = np.zeros(self.filter_size, dtype=np.complex64)
        
        # 功率谱估计
        self.P = np.zeros(self.filter_size)
        
        # 状态
        self.is_enabled = True
        self.buffer = np.zeros(block_size)
        
        logger.info(f"频域AEC初始化: block_size={block_size}, filter_length={filter_length}")
    
    def process_block(
        self,
        mic_block: np.ndarray,
        reference_block: np.ndarray
    ) -> Tuple[np.ndarray, float]:
        """
        块处理模式
        
        Args:
            mic_block: 麦克风音频块
            reference_block: 参考音频块
        
        Returns:
            (enhanced_block, erl)
        """
        if not self.is_enabled or len(mic_block) != self.block_size:
            return mic_block, 0.0
        
        try:
            # 组合输入缓冲
            x = np.concatenate([self.buffer, reference_block])
            
            # FFT
            X = np.fft.rfft(x, self.fft_size)
            
            # 功率谱更新
            self.P = self.forgetting_factor * self.P + (1 - self.forgetting_factor) * np.abs(X) ** 2
            
            # 计算频域误差
            Y = np.fft.rfft(mic_block, self.fft_size)
            E = Y - X[:len(Y)] * self.W
            
            # 更新滤波器系数 (频域NLMS)
            X_power = self.P + 1e-8
            self.W += self.mu * np.conj(X[:len(self.W)]) * E / X_power
            
            # IFFT得到时域误差
            error = np.fft.irfft(E, self.fft_size)[-self.block_size:]
            
            # 更新缓冲区
            self.buffer = reference_block[-self.block_size:]
            
            # 计算回声衰减
            mic_power = np.mean(mic_block ** 2)
            error_power = np.mean(error ** 2)
            erl = 10 * np.log10(max(mic_power, 1e-10) / max(error_power, 1e-10))
            
            return error, erl
            
        except Exception as e:
            logger.error(f"频域AEC处理失败: {e}")
            return mic_block, 0.0
    
    def reset(self):
        """重置滤波器状态"""
        self.W = np.zeros(self.filter_size, dtype=np.complex64)
        self.P = np.zeros(self.filter_size)
        self.buffer = np.zeros(self.block_size)
    
    def enable(self):
        self.is_enabled = True
    
    def disable(self):
        self.is_enabled = False


class EchoSuppression:
    """
    回声抑制器
    使用谱减法和动态阈值抑制残留回声
    """
    
    def __init__(
        self,
        frame_size: int = 1024,
        hop_size: int = 256,
        noise_floor: float = -60.0
    ):
        """
        初始化回声抑制器
        
        Args:
            frame_size: 帧大小
            hop_size: 跳步大小
            noise_floor: 噪声地板(dB)
        """
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.noise_floor_db = noise_floor
        self.noise_floor = 10 ** (noise_floor / 20)
        
        self.is_enabled = True
        logger.info(f"回声抑制初始化: frame_size={frame_size}, noise_floor={self.noise_floor_db}dB")
    
    def process(self, audio: np.ndarray, vad_mask: Optional[np.ndarray] = None) -> np.ndarray:
        """
        处理音频信号，抑制残留回声
        
        Args:
            audio: 输入音频
            vad_mask: VAD掩码（可选）
        
        Returns:
            抑制后的音频
        """
        if not self.is_enabled:
            return audio
        
        try:
            # 计算帧数
            n_frames = (len(audio) - self.frame_size) // self.hop_size + 1
            
            if n_frames <= 0:
                return audio
            
            # 初始化输出
            output = np.zeros(len(audio) + self.frame_size)
            window = signal.hann(self.frame_size)
            
            for i in range(n_frames):
                start = i * self.hop_size
                end = start + self.frame_size
                
                # 获取帧
                frame = audio[start:end] * window
                
                # FFT
                spectrum = np.fft.rfft(frame)
                magnitude = np.abs(spectrum)
                phase = np.angle(spectrum)
                
                # 计算功率谱
                power = magnitude ** 2
                
                # 谱减法
                subtracted = power - self.noise_floor ** 2
                subtracted = np.maximum(subtracted, self.noise_floor ** 2)
                
                # 应用掩码（如果有VAD）
                if vad_mask is not None:
                    mask_value = vad_mask[i] if i < len(vad_mask) else 1.0
                    subtracted *= mask_value
                
                # 重构频谱
                new_spectrum = np.sqrt(subtracted) * np.exp(1j * phase)
                
                # IFFT
                new_frame = np.fft.irfft(new_spectrum, self.frame_size)
                
                # 叠加
                output[start:end] += new_frame
            
            # 归一化
            output = output[:len(audio)]
            max_val = np.max(np.abs(output))
            if max_val > 1.0:
                output = output / max_val
            
            return output
            
        except Exception as e:
            logger.error(f"回声抑制处理失败: {e}")
            return audio
    
    def enable(self):
        self.is_enabled = True
    
    def disable(self):
        self.is_enabled = False


class AECProcessor:
    """
    AEC处理器 - 综合回声消除解决方案
    结合时域和频域方法，提供完整的回声处理流程
    """
    
    def __init__(self, mode: str = "adaptive"):
        """
        初始化AEC处理器
        
        Args:
            mode: 处理模式 ("adaptive", "frequency", "hybrid")
        """
        self.mode = mode
        self.is_enabled = True
        
        # 创建各个处理器
        self.adaptive_aec = AdaptiveEchoCanceller()
        self.frequency_aec = FrequencyDomainEchoCanceller()
        self.echo_suppression = EchoSuppression()
        
        # 双讲检测
        self.double_talk_threshold = 0.3
        self.is_double_talk = False
        
        logger.info(f"AECProcessor初始化: mode={mode}")
    
    def process(
        self,
        mic_signal: np.ndarray,
        reference_signal: np.ndarray,
        sample_rate: int = 16000
    ) -> np.ndarray:
        """
        处理麦克风信号，消除回声
        
        Args:
            mic_signal: 麦克风信号
            reference_signal: 参考信号（扬声器输出）
            sample_rate: 采样率
        
        Returns:
            增强后的音频信号
        """
        if not self.is_enabled:
            return mic_signal
        
        try:
            # 双讲检测
            mic_level = np.mean(np.abs(mic_signal))
            ref_level = np.mean(np.abs(reference_signal))
            
            if mic_level > 0 and ref_level > 0:
                ratio = mic_level / ref_level
                self.is_double_talk = ratio > self.double_talk_threshold
            
            if self.mode == "adaptive":
                enhanced, erl = self.adaptive_aec.process(mic_signal, reference_signal)
            elif self.mode == "frequency":
                # 分块处理
                enhanced = np.zeros_like(mic_signal)
                block_size = self.frequency_aec.block_size
                n_blocks = len(mic_signal) // block_size
                
                for i in range(n_blocks):
                    mic_block = mic_signal[i * block_size:(i + 1) * block_size]
                    ref_block = reference_signal[i * block_size:(i + 1) * block_size]
                    enhanced_block, _ = self.frequency_aec.process_block(mic_block, ref_block)
                    enhanced[i * block_size:(i + 1) * block_size] = enhanced_block
                
                # 处理剩余部分
                remaining = len(mic_signal) % block_size
                if remaining > 0:
                    mic_block = mic_signal[-remaining:]
                    ref_block = reference_signal[-remaining:]
                    enhanced_block, _ = self.frequency_aec.process_block(mic_block, ref_block)
                    enhanced[-remaining:] = enhanced_block
                    
            else:  # hybrid
                # 时域处理
                enhanced, erl = self.adaptive_aec.process(mic_signal, reference_signal)
                
                # 如果双讲，跳过频域处理
                if not self.is_double_talk:
                    # 分块处理
                    block_size = self.frequency_aec.block_size
                    n_blocks = len(enhanced) // block_size
                    
                    for i in range(n_blocks):
                        mic_block = enhanced[i * block_size:(i + 1) * block_size]
                        ref_block = reference_signal[i * block_size:(i + 1) * block_size]
                        enhanced_block, _ = self.frequency_aec.process_block(mic_block, ref_block)
                        enhanced[i * block_size:(i + 1) * block_size] = enhanced_block
            
            # 回声抑制
            if not self.is_double_talk:
                enhanced = self.echo_suppression.process(enhanced)
            
            return enhanced
            
        except Exception as e:
            logger.error(f"AEC处理失败: {e}")
            return mic_signal
    
    def reset(self):
        """重置所有处理器"""
        self.adaptive_aec.reset()
        self.frequency_aec.reset()
        self.is_double_talk = False
        logger.info("AECProcessor已重置")
    
    def enable(self):
        self.is_enabled = True
        self.adaptive_aec.enable()
        self.frequency_aec.enable()
        self.echo_suppression.enable()
    
    def disable(self):
        self.is_enabled = False
        self.adaptive_aec.disable()
        self.frequency_aec.disable()
        self.echo_suppression.disable()
    
    def set_mode(self, mode: str):
        """设置处理模式"""
        if mode in ["adaptive", "frequency", "hybrid"]:
            self.mode = mode
            logger.info(f"AEC模式切换: {mode}")
    
    def get_status(self) -> dict:
        """获取AEC状态"""
        return {
            "enabled": self.is_enabled,
            "mode": self.mode,
            "double_talk": self.is_double_talk,
            "adaptive_filter_length": self.adaptive_aec.filter_length,
            "frequency_block_size": self.frequency_aec.block_size
        }


# 全局AEC处理器实例
aec_processor = AECProcessor(mode="hybrid")


class EchoCancellationModule:
    """
    回声消除模块 - 对外接口
    集成到YHLZ2.0的音频处理流程中
    """
    
    def __init__(self):
        self.processor = aec_processor
        self.reference_audio = None
        self.is_initialized = False
    
    def initialize(self, reference_audio: Optional[np.ndarray] = None):
        """
        初始化AEC
        
        Args:
            reference_audio: 参考音频样本（可选）
        """
        self.processor.reset()
        self.is_initialized = True
        logger.info("回声消除模块已初始化")
    
    def process_audio(
        self,
        mic_audio: np.ndarray,
        speaker_audio: Optional[np.ndarray] = None,
        sample_rate: int = 16000
    ) -> np.ndarray:
        """
        处理音频，消除回声
        
        Args:
            mic_audio: 麦克风音频
            speaker_audio: 扬声器音频（参考）
            sample_rate: 采样率
        
        Returns:
            处理后的音频
        """
        if not self.is_initialized:
            self.initialize()
        
        # 如果没有提供参考信号，返回原始音频
        if speaker_audio is None:
            if self.reference_audio is not None:
                speaker_audio = self.reference_audio
            else:
                return mic_audio
        
        # 确保长度一致
        min_len = min(len(mic_audio), len(speaker_audio))
        mic_audio = mic_audio[:min_len]
        speaker_audio = speaker_audio[:min_len]
        
        return self.processor.process(mic_audio, speaker_audio, sample_rate)
    
    def set_reference(self, reference_audio: np.ndarray):
        """设置参考音频"""
        self.reference_audio = reference_audio
    
    def enable(self):
        self.processor.enable()
    
    def disable(self):
        self.processor.disable()
    
    def get_info(self) -> dict:
        """获取AEC信息"""
        return self.processor.get_status()


# 全局回声消除模块
echo_cancellation = EchoCancellationModule()