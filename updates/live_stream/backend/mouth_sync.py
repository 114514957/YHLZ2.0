import numpy as np
from scipy import signal
import logging
import time

logger = logging.getLogger(__name__)


class MouthSyncEngine:
    def __init__(self, sample_rate=16000, sync_mode='db'):
        self.sample_rate = sample_rate
        self.sync_mode = sync_mode
        self.history = []
        self.max_history_length = 10
        self._mouth_value = 0.0
        
        self.b, self.a = signal.butter(4, 300, fs=sample_rate, btype='low')
        
        self._vowel_analyser = None
        self._vowel_params = {
            'a': 0.0,
            'e': 0.0,
            'i': 0.0,
            'o': 0.0,
            'u': 0.0
        }
        
        if sync_mode == 'vowel' or sync_mode == 'auto':
            self._init_vowel_analyser()

    def _init_vowel_analyser(self):
        try:
            from pymouth import VowelAnalyser
            self._vowel_analyser = VowelAnalyser()
            logger.info("pymouth元音分析器初始化成功")
        except ImportError:
            logger.warning("pymouth未安装，将使用分贝模式")
            self.sync_mode = 'db'

    def calculate_mouth_open(self, audio_chunk):
        if len(audio_chunk) == 0:
            self._mouth_value = 0.0
            return 0.0
        
        try:
            audio_np = np.array(audio_chunk, dtype=np.float32)
            
            volume = np.abs(audio_np).mean()
            
            if volume < 0.001:
                self._mouth_value = max(0.0, self._mouth_value - 0.1)
                self._reset_vowel_params()
                return self._mouth_value
            
            if self.sync_mode == 'vowel' and self._vowel_analyser:
                return self._calculate_vowel_sync(audio_np)
            
            filtered = signal.filtfilt(self.b, self.a, audio_np)
            
            energy = np.sum(filtered ** 2) / len(filtered)
            
            mouth_value = min(1.0, max(0.0, energy * 10000))
            
            self.history.append(mouth_value)
            if len(self.history) > self.max_history_length:
                self.history.pop(0)
            
            smoothed_value = sum(self.history) / len(self.history)
            
            self._mouth_value = smoothed_value
            return self._mouth_value
            
        except Exception as e:
            logger.error(f"口型同步计算失败: {e}")
            return 0.0

    def _calculate_vowel_sync(self, audio_np):
        try:
            vowels = self._vowel_analyser.analyse(audio_np, sample_rate=self.sample_rate)
            
            self._vowel_params = {
                'a': vowels.get('a', 0.0),
                'e': vowels.get('e', 0.0),
                'i': vowels.get('i', 0.0),
                'o': vowels.get('o', 0.0),
                'u': vowels.get('u', 0.0)
            }
            
            mouth_open = max(
                self._vowel_params['a'],
                self._vowel_params['e'],
                self._vowel_params['i'],
                self._vowel_params['o'],
                self._vowel_params['u']
            )
            
            self.history.append(mouth_open)
            if len(self.history) > self.max_history_length:
                self.history.pop(0)
            
            self._mouth_value = sum(self.history) / len(self.history)
            return self._mouth_value
            
        except Exception as e:
            logger.error(f"元音分析失败: {e}")
            self.sync_mode = 'db'
            return self.calculate_mouth_open(audio_np)

    def _reset_vowel_params(self):
        self._vowel_params = {
            'a': 0.0,
            'e': 0.0,
            'i': 0.0,
            'o': 0.0,
            'u': 0.0
        }

    def get_mouth_value(self):
        return self._mouth_value

    def get_vowel_params(self):
        return self._vowel_params

    def reset(self):
        self.history = []
        self._mouth_value = 0.0
        self._reset_vowel_params()

    def set_sync_mode(self, mode):
        self.sync_mode = mode
        if mode == 'vowel' and self._vowel_analyser is None:
            self._init_vowel_analyser()


class AudioAnalyzer:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.mouth_sync = MouthSyncEngine(sample_rate)
        
    def analyze_audio(self, audio_data):
        mouth_value = self.mouth_sync.calculate_mouth_open(audio_data)
        vowel_params = self.mouth_sync.get_vowel_params()
        
        return {
            'mouth_open': mouth_value,
            'volume': np.abs(np.array(audio_data)).mean() if audio_data else 0.0,
            'vowel_params': vowel_params
        }


mouth_sync_engine = MouthSyncEngine()
audio_analyzer = AudioAnalyzer()