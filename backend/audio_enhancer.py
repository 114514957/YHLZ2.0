import numpy as np
import logging
from scipy import signal
from scipy.fft import rfft, irfft, rfftfreq

logger = logging.getLogger(__name__)


class AudioEnhancer:
    def __init__(self):
        self._sample_rate = 16000
        self._window_size = 512
        self._hop_size = 256
        self._fft_size = 512
        self._noise_floor = None
        self._frame_energy_threshold = 0.003
        self._silence_frames_threshold = 10
        
        self._rnnoise_model = None
        self._webrtc_vad = None
        self._vad_enabled = True
        
        self._noise_gate_threshold = 0.002
        self._noise_gate_attack = 0.02
        self._noise_gate_release = 0.1
        self._noise_gate_hold = 0.1
    
    def set_sample_rate(self, sample_rate: int):
        self._sample_rate = sample_rate
        self._recalculate_params()
    
    def _recalculate_params(self):
        self._window_size = int(self._sample_rate * 0.032)
        self._hop_size = int(self._sample_rate * 0.016)
        self._fft_size = self._window_size
    
    def spectral_subtraction(self, audio: np.ndarray, noise_estimate: np.ndarray = None, 
                           alpha: float = 1.0, beta: float = 0.001) -> np.ndarray:
        if noise_estimate is None:
            noise_estimate = self._estimate_noise(audio)
        
        noise_spec = np.abs(rfft(noise_estimate, self._fft_size)) ** 2
        
        num_frames = int((len(audio) - self._window_size) / self._hop_size) + 1
        enhanced = np.zeros(len(audio), dtype=np.float32)
        
        for i in range(num_frames):
            start = i * self._hop_size
            end = start + self._window_size
            frame = audio[start:end]
            
            window = signal.windows.hann(self._window_size)
            frame_windowed = frame * window
            
            frame_spec = rfft(frame_windowed, self._fft_size)
            frame_mag = np.abs(frame_spec)
            frame_phase = np.angle(frame_spec)
            
            enhanced_mag = np.sqrt(np.maximum(frame_mag ** 2 - alpha * noise_spec, beta))
            enhanced_spec = enhanced_mag * np.exp(1j * frame_phase)
            
            enhanced_frame = irfft(enhanced_spec)
            enhanced[start:end] += enhanced_frame[:self._window_size] * window
        
        max_val = np.max(np.abs(enhanced))
        if max_val > 0:
            enhanced = enhanced / max_val
        
        return enhanced.astype(np.float32)
    
    def _estimate_noise(self, audio: np.ndarray) -> np.ndarray:
        num_frames = int((len(audio) - self._window_size) / self._hop_size) + 1
        noise_frames = []
        
        for i in range(min(num_frames, 50)):
            start = i * self._hop_size
            end = start + self._window_size
            frame = audio[start:end]
            energy = np.mean(frame ** 2)
            if energy < np.percentile(audio ** 2, 30):
                noise_frames.append(frame)
        
        if noise_frames:
            return np.mean(noise_frames, axis=0)
        
        return audio[:self._window_size]
    
    def adaptive_noise_suppression(self, audio: np.ndarray, learning_rate: float = 0.01, 
                                   min_suppression: float = 0.1) -> np.ndarray:
        num_frames = int((len(audio) - self._window_size) / self._hop_size) + 1
        enhanced = np.zeros(len(audio), dtype=np.float32)
        
        noise_power = np.ones(self._fft_size // 2 + 1) * 0.01
        window = signal.windows.hann(self._window_size)
        
        for i in range(num_frames):
            start = i * self._hop_size
            end = start + self._window_size
            frame = audio[start:end]
            
            frame_windowed = frame * window
            frame_spec = rfft(frame_windowed, self._fft_size)
            frame_power = np.abs(frame_spec) ** 2
            
            frame_energy = np.mean(frame_power)
            is_noise = frame_energy < np.percentile(audio ** 2, 20)
            
            if is_noise:
                noise_power = noise_power * (1 - learning_rate) + frame_power * learning_rate
            
            suppression = np.minimum(frame_power / (noise_power + 1e-10), 1.0)
            suppression = np.maximum(suppression, min_suppression)
            
            enhanced_spec = frame_spec * np.sqrt(suppression)
            enhanced_frame = irfft(enhanced_spec)
            
            enhanced[start:end] += enhanced_frame[:self._window_size] * window
        
        max_val = np.max(np.abs(enhanced))
        if max_val > 0:
            enhanced = enhanced / max_val
        
        return enhanced.astype(np.float32)
    
    def preemphasis(self, audio: np.ndarray, alpha: float = 0.97) -> np.ndarray:
        return np.append(audio[0], audio[1:] - alpha * audio[:-1]).astype(np.float32)
    
    def deemphasis(self, audio: np.ndarray, alpha: float = 0.97) -> np.ndarray:
        result = np.zeros_like(audio)
        result[0] = audio[0]
        for i in range(1, len(audio)):
            result[i] = audio[i] + alpha * result[i-1]
        return result.astype(np.float32)
    
    def dynamic_range_compression(self, audio: np.ndarray, threshold: float = 0.5, 
                                  ratio: float = 2.0, knee: float = 0.1) -> np.ndarray:
        compressed = np.copy(audio)
        
        over_threshold = np.abs(audio) > threshold
        knee_range = np.logical_and(np.abs(audio) > threshold - knee, 
                                   np.abs(audio) < threshold + knee)
        
        compressed[knee_range] = self._apply_knee_compression(
            audio[knee_range], threshold, ratio, knee
        )
        
        compressed[over_threshold] = threshold + (np.abs(audio[over_threshold]) - threshold) / ratio
        compressed[over_threshold] *= np.sign(audio[over_threshold])
        
        max_val = np.max(np.abs(compressed))
        if max_val > 0:
            compressed = compressed / max_val
        
        return compressed.astype(np.float32)
    
    def _apply_knee_compression(self, values: np.ndarray, threshold: float, 
                               ratio: float, knee: float) -> np.ndarray:
        abs_values = np.abs(values)
        normalized = (abs_values - threshold + knee) / (2 * knee)
        
        compressed = threshold + (abs_values - threshold) * (
            (1 - 1/ratio) * normalized ** 2 + 1/ratio
        )
        
        return compressed * np.sign(values)
    
    def voice_activity_detection(self, audio: np.ndarray, aggressiveness: int = 2) -> tuple:
        try:
            import webrtcvad
            if self._webrtc_vad is None:
                self._webrtc_vad = webrtcvad.Vad(aggressiveness)
            
            frame_duration = 30
            frame_size = int(self._sample_rate * frame_duration / 1000)
            
            frames = []
            for i in range(0, len(audio), frame_size):
                frame = audio[i:i+frame_size]
                if len(frame) < frame_size:
                    frame = np.pad(frame, (0, frame_size - len(frame)))
                frame_int16 = (frame * 32767).astype(np.int16)
                frames.append(self._webrtc_vad.is_speech(frame_int16.tobytes(), self._sample_rate))
            
            voice_segments = []
            in_voice = False
            start_idx = 0
            
            for i, is_voice in enumerate(frames):
                if is_voice and not in_voice:
                    in_voice = True
                    start_idx = i * frame_size
                elif not is_voice and in_voice:
                    in_voice = False
                    end_idx = (i + 1) * frame_size
                    voice_segments.append((start_idx, end_idx))
            
            if in_voice:
                voice_segments.append((start_idx, len(audio)))
            
            return voice_segments, frames
        
        except ImportError:
            logger.debug("webrtcvad不可用，使用简单能量检测")
            return self._simple_vad(audio)
    
    def _simple_vad(self, audio: np.ndarray) -> tuple:
        frame_size = int(self._sample_rate * 0.03)
        hop_size = int(self._sample_rate * 0.015)
        
        frames = []
        voice_segments = []
        in_voice = False
        start_idx = 0
        
        for i in range(0, len(audio), hop_size):
            frame = audio[i:i+frame_size]
            energy = np.mean(frame ** 2) if len(frame) > 0 else 0
            is_voice = energy > self._frame_energy_threshold
            frames.append(is_voice)
            
            if is_voice and not in_voice:
                in_voice = True
                start_idx = max(0, i - frame_size)
            elif not is_voice and in_voice:
                in_voice = False
                end_idx = min(len(audio), i + frame_size)
                if end_idx - start_idx > self._sample_rate * 0.1:
                    voice_segments.append((start_idx, end_idx))
        
        if in_voice:
            voice_segments.append((start_idx, len(audio)))
        
        return voice_segments, frames
    
    def apply_vad(self, audio: np.ndarray, aggressiveness: int = 2) -> np.ndarray:
        voice_segments, _ = self.voice_activity_detection(audio, aggressiveness)
        
        if not voice_segments:
            return audio
        
        result = np.array([], dtype=np.float32)
        for start, end in voice_segments:
            result = np.concatenate([result, audio[start:end]])
        
        return result
    
    def remove_silence(self, audio: np.ndarray, threshold: float = 0.003, 
                       min_silence_len: float = 0.3) -> np.ndarray:
        frame_size = int(self._sample_rate * 0.03)
        hop_size = int(self._sample_rate * 0.015)
        
        silence_start = None
        result = np.array([], dtype=np.float32)
        min_silence_samples = int(min_silence_len * self._sample_rate)
        
        for i in range(0, len(audio), hop_size):
            frame = audio[i:i+frame_size]
            energy = np.mean(frame ** 2) if len(frame) > 0 else 0
            
            if energy < threshold:
                if silence_start is None:
                    silence_start = i
            else:
                if silence_start is not None:
                    silence_end = i
                    if silence_end - silence_start > min_silence_samples:
                        result = np.concatenate([result, audio[:silence_start]])
                        audio = audio[silence_end:]
                        i = 0
                    silence_start = None
        
        result = np.concatenate([result, audio])
        
        return result.astype(np.float32)
    
    def normalize_audio(self, audio: np.ndarray, target_rms: float = 0.1) -> np.ndarray:
        rms = np.sqrt(np.mean(audio ** 2))
        if rms > 0:
            audio = audio * (target_rms / rms)
        
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        
        return audio.astype(np.float32)
    
    def apply_gain(self, audio: np.ndarray, db_gain: float) -> np.ndarray:
        gain = 10 ** (db_gain / 20)
        audio = audio * gain
        
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        
        return audio.astype(np.float32)
    
    def high_pass_filter(self, audio: np.ndarray, cutoff: float = 80) -> np.ndarray:
        nyquist = self._sample_rate / 2
        b, a = signal.butter(2, cutoff / nyquist, 'high')
        return signal.filtfilt(b, a, audio).astype(np.float32)
    
    def low_pass_filter(self, audio: np.ndarray, cutoff: float = 4000) -> np.ndarray:
        nyquist = self._sample_rate / 2
        b, a = signal.butter(2, cutoff / nyquist, 'low')
        return signal.filtfilt(b, a, audio).astype(np.float32)
    
    def band_pass_filter(self, audio: np.ndarray, low_cut: float = 80, high_cut: float = 4000) -> np.ndarray:
        nyquist = self._sample_rate / 2
        b, a = signal.butter(2, [low_cut / nyquist, high_cut / nyquist], 'band')
        return signal.filtfilt(b, a, audio).astype(np.float32)
    
    def init_rnnoise(self):
        try:
            import rnnoise
            self._rnnoise_model = rnnoise.RNNoise()
            logger.info("RNNoise降噪模型初始化成功")
            return True
        except ImportError:
            logger.info("rnnoise库不可用，将使用noisereduce作为替代")
        except Exception as e:
            logger.warning(f"RNNoise初始化失败: {e}")
        return False
    
    def apply_noisereduce(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        try:
            import noisereduce as nr
            noise_clip = audio[:int(sample_rate * 0.5)] if len(audio) > sample_rate * 0.5 else audio
            
            try:
                enhanced = nr.reduce_noise(
                    y=audio,
                    sr=sample_rate,
                    y_noise=noise_clip,
                    n_fft=512,
                    hop_length=128,
                    nonstationary=True
                )
            except TypeError:
                enhanced = nr.reduce_noise(
                    y=audio,
                    sr=sample_rate,
                    y_noise=noise_clip,
                    n_fft=512,
                    hop_length=128
                )
            
            max_val = np.max(np.abs(enhanced))
            if max_val > 0:
                enhanced = enhanced / max_val
            
            logger.debug("已应用noisereduce降噪")
            return enhanced.astype(np.float32)
        except ImportError:
            logger.debug("noisereduce库不可用，跳过降噪")
            return audio
        except Exception as e:
            logger.warning(f"noisereduce降噪失败: {e}")
            return audio
    
    def apply_rnnoise(self, audio: np.ndarray) -> np.ndarray:
        if self._rnnoise_model is None:
            if not self.init_rnnoise():
                return self.apply_noisereduce(audio, self._sample_rate)
        
        try:
            audio_int16 = (audio * 32767).astype(np.int16)
            enhanced_int16 = self._rnnoise_model.process(audio_int16)
            enhanced = enhanced_int16.astype(np.float32) / 32767
            
            max_val = np.max(np.abs(enhanced))
            if max_val > 0:
                enhanced = enhanced / max_val
            
            logger.debug("已应用RNNoise降噪")
            return enhanced.astype(np.float32)
        except Exception as e:
            logger.warning(f"RNNoise降噪失败，回退到noisereduce: {e}")
            return self.apply_noisereduce(audio, self._sample_rate)
    
    def noise_gate(self, audio: np.ndarray, threshold: float = None, 
                   attack: float = None, release: float = None, hold: float = None) -> np.ndarray:
        threshold = threshold if threshold is not None else self._noise_gate_threshold
        attack = attack if attack is not None else self._noise_gate_attack
        release = release if release is not None else self._noise_gate_release
        hold = hold if hold is not None else self._noise_gate_hold
        
        frame_size = int(self._sample_rate * 0.01)
        hop_size = frame_size
        
        attack_samples = int(self._sample_rate * attack)
        release_samples = int(self._sample_rate * release)
        hold_samples = int(self._sample_rate * hold)
        
        result = np.copy(audio).astype(np.float32)
        
        gate_open = False
        hold_counter = 0
        
        for i in range(0, len(audio), hop_size):
            frame = audio[i:i+frame_size]
            frame_energy = np.mean(frame ** 2)
            
            if frame_energy > threshold:
                if not gate_open:
                    fade_samples = min(attack_samples, i)
                    start = max(0, i - fade_samples)
                    ramp = np.linspace(0, 1, fade_samples + 1)
                    result[start:i] *= ramp[:-1]
                gate_open = True
                hold_counter = hold_samples
            else:
                if gate_open:
                    if hold_counter > 0:
                        hold_counter -= len(frame)
                    else:
                        fade_samples = min(release_samples, len(audio) - i)
                        ramp = np.linspace(1, 0, fade_samples + 1)
                        result[i:i+fade_samples] *= ramp[:-1]
                        gate_open = False
        
        if not gate_open:
            result[np.abs(audio) < threshold * 0.5] = 0
        
        logger.debug("已应用噪声门限")
        return result
    
    def spectral_gating(self, audio: np.ndarray, threshold: float = 3.0, 
                       smoothing_factor: float = 0.1) -> np.ndarray:
        num_frames = int((len(audio) - self._window_size) / self._hop_size) + 1
        enhanced = np.zeros(len(audio), dtype=np.float32)
        
        noise_estimate = self._estimate_noise(audio)
        noise_spec = np.abs(rfft(noise_estimate, self._fft_size))
        
        window = signal.windows.hann(self._window_size)
        current_gate = np.ones(self._fft_size // 2 + 1)
        
        for i in range(num_frames):
            start = i * self._hop_size
            end = start + self._window_size
            frame = audio[start:end]
            
            frame_windowed = frame * window
            frame_spec = rfft(frame_windowed, self._fft_size)
            frame_mag = np.abs(frame_spec)
            
            noise_threshold = noise_spec * threshold
            
            gate = np.where(frame_mag > noise_threshold, 1.0, smoothing_factor)
            current_gate = current_gate * (1 - 0.1) + gate * 0.1
            
            enhanced_spec = frame_spec * current_gate
            enhanced_frame = irfft(enhanced_spec)
            
            enhanced[start:end] += enhanced_frame[:self._window_size] * window
        
        max_val = np.max(np.abs(enhanced))
        if max_val > 0:
            enhanced = enhanced / max_val
        
        logger.debug("已应用谱域门限")
        return enhanced.astype(np.float32)
    
    def _apply_equalizer(self, audio: np.ndarray) -> np.ndarray:
        nyquist = self._sample_rate / 2
        
        b1, a1 = signal.butter(1, 200 / nyquist, 'high')
        audio = signal.filtfilt(b1, a1, audio)
        
        b2, a2 = signal.butter(1, [800, 3000], btype='band', fs=self._sample_rate)
        audio = signal.filtfilt(b2, a2, audio)
        
        return audio.astype(np.float32)
    
    def _dual_band_agc(self, audio: np.ndarray, low_target: float = 0.6, high_target: float = 0.4, max_gain: float = 10.0) -> np.ndarray:
        nyquist = self._sample_rate / 2
        b_low, a_low = signal.butter(2, 1000 / nyquist, 'low')
        b_high, a_high = signal.butter(2, 1000 / nyquist, 'high')
        
        low_band = signal.filtfilt(b_low, a_low, audio)
        high_band = signal.filtfilt(b_high, a_high, audio)
        
        low_rms = np.sqrt(np.mean(low_band ** 2))
        high_rms = np.sqrt(np.mean(high_band ** 2))
        
        if low_rms > 0:
            low_gain = min(max_gain, low_target / low_rms)
            low_band = low_band * low_gain
        
        if high_rms > 0:
            high_gain = min(max_gain * 1.5, high_target / high_rms)
            high_band = high_band * high_gain
        
        result = low_band + high_band
        
        max_val = np.max(np.abs(result))
        if max_val > 1.0:
            result = result / max_val
        
        return result.astype(np.float32)
    
    def enhance(self, audio: np.ndarray, sample_rate: int = 16000, 
                enable_vad: bool = True, enable_noise_suppression: bool = True,
                enable_compression: bool = True, enable_normalization: bool = True,
                enable_rnnoise: bool = True, enable_noise_gate: bool = True,
                fast_mode: bool = False) -> np.ndarray:
        if sample_rate != self._sample_rate:
            self.set_sample_rate(sample_rate)
        
        audio = audio.astype(np.float32)
        
        if fast_mode:
            logger.debug("使用快速模式：跳过耗时处理步骤")
            
            if enable_noise_gate:
                audio = self.noise_gate(audio, threshold=0.001)
            
            audio = self.preemphasis(audio, alpha=0.97)
            
            if enable_rnnoise and self._rnnoise_model is not None:
                audio = self.apply_rnnoise(audio)
            
            audio = self._apply_equalizer(audio)
            
            if enable_normalization:
                audio = self.normalize_audio(audio, target_rms=0.15)
            
            audio = self.high_pass_filter(audio, cutoff=60)
            
            return audio
        
        if enable_noise_gate:
            audio = self.noise_gate(audio, threshold=0.001)
            logger.debug("已应用噪声门限")
        
        audio = self.preemphasis(audio, alpha=0.97)
        logger.debug("已应用预加重")
        
        if enable_rnnoise:
            audio = self.apply_rnnoise(audio)
            logger.debug("已应用RNNoise降噪")
        
        if enable_noise_suppression:
            audio = self.adaptive_noise_suppression(audio, learning_rate=0.02)
            logger.debug("已应用自适应降噪")
        
        if enable_vad:
            audio = self.apply_vad(audio, aggressiveness=1)
            logger.debug("已应用语音活动检测")
        
        audio = self._dual_band_agc(audio)
        logger.debug("已应用双频段AGC")
        
        if enable_compression:
            audio = self.dynamic_range_compression(audio, threshold=0.4, ratio=2.5)
            logger.debug("已应用动态范围压缩")
        
        if enable_normalization:
            audio = self.normalize_audio(audio, target_rms=0.15)
            logger.debug("已应用音频归一化")
        
        audio = self._apply_equalizer(audio)
        logger.debug("已应用均衡器")
        
        audio = self.high_pass_filter(audio, cutoff=60)
        logger.debug("已应用高通滤波")
        
        return audio


audio_enhancer = AudioEnhancer()