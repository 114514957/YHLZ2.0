"""
YHLZ 2.0 Edge-TTS 引擎实现
使用Edge-TTS（微软免费在线TTS）
优化：极低延迟流式合成、智能分块策略、预热机制、线程池
"""

import logging
import io
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator, Optional, Tuple

import numpy as np

from backend.tts.base import BaseTTSEngine

logger = logging.getLogger(__name__)


class EdgeTTSEngine(BaseTTSEngine):
    """Edge-TTS 引擎 (在线, 免费, 无需GPU)"""

    name = "edge-tts"

    def __init__(self):
        super().__init__()
        self._edge_tts = None
        self._executor: Optional[ThreadPoolExecutor] = None

        # 低延迟配置
        self._stream_buffer_size = 2048
        self._min_chunk_chars = 3
        self._max_chunk_chars = 15

        # 预热状态
        self._warmup_done = False

        self.load()

    def load(self) -> bool:
        """初始化TTS引擎"""
        if self.is_loaded:
            return True
        try:
            logger.info("正在初始化Edge-TTS引擎")
            import edge_tts
            self._edge_tts = edge_tts
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TTS")
            self.is_loaded = True
            logger.info("TTS引擎初始化成功")
            self._warmup()
            return True
        except ImportError:
            logger.error("未安装edge-tts库，TTS功能将不可用")
            self.is_loaded = False
            return False
        except Exception as e:
            logger.error(f"TTS引擎初始化失败: {e}")
            self.is_loaded = False
            return False

    def unload(self) -> None:
        """卸载模型"""
        self.is_loaded = False
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        logger.info("TTS引擎已卸载")

    def release_gpu(self) -> None:
        """Edge-TTS在线引擎无需GPU, 空实现"""
        pass

    def _warmup(self):
        """预热TTS引擎（快速预热）"""
        if not self.is_loaded or self._warmup_done:
            return

        try:
            logger.info("正在预热TTS引擎...")

            async def quick_warmup():
                communicate = self._edge_tts.Communicate("元", "zh-CN-XiaoxiaoNeural")
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        break
                # 确保 communicate 内部 session 被关闭
                if hasattr(communicate, '_session') and communicate._session:
                    await communicate._session.close()

            loop = asyncio.new_event_loop()
            try:
                # M0.3: 预热加超时, 避免网络不可达时阻塞引擎加载/回退链
                loop.run_until_complete(
                    asyncio.wait_for(quick_warmup(), timeout=10.0)
                )
            finally:
                # 清理残留任务
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

            self._warmup_done = True
            logger.info("[OK] TTS引擎预热完成")

        except Exception as e:
            logger.warning(f"TTS预热失败: {e}")

    async def _synthesize_internal(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%") -> bytes:
        """内部合成方法"""
        if not self._edge_tts:
            return b""

        try:
            communicate = self._edge_tts.Communicate(
                text,
                voice,
                rate=rate,
                volume="+0%"
            )

            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]

            return audio_data
        except Exception as e:
            logger.error(f"内部合成失败: {e}")
            return b""

    async def _synthesize_chunk_stream(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural"):
        """
        极低延迟流式合成生成器

        直接yield原始音频块，不等待完整缓冲
        """
        if not self._edge_tts:
            return

        try:
            communicate = self._edge_tts.Communicate(
                text,
                voice,
                rate="+0%",
                volume="+0%"
            )

            buffer = b""
            chunk_count = 0

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer += chunk["data"]

                    # 极低延迟：每2048字节就输出（约0.08秒音频）
                    if len(buffer) >= self._stream_buffer_size:
                        chunk_count += 1
                        logger.debug(f"流式合成块 {chunk_count}: {len(buffer)}字节")
                        yield buffer
                        buffer = b""

            if buffer and len(buffer) >= 500:
                chunk_count += 1
                logger.debug(f"流式合成最后块 {chunk_count}: {len(buffer)}字节")
                yield buffer
            elif buffer:
                logger.debug(f"跳过过小的音频块: {len(buffer)}字节")

            logger.debug(f"流式合成完成，共 {chunk_count} 块")

        except Exception as e:
            logger.error(f"流式合成失败: {e}")

    def _smart_chunk_text(self, text: str) -> list:
        """
        智能文本分块策略

        基于标点符号和语义边界进行分块，确保语音合成的自然性
        """
        if len(text) <= self._max_chunk_chars:
            return [text]

        chunks = []
        current_chunk = ""

        punctuation = "，。！？、；：、\n"

        for char in text:
            current_chunk += char

            if len(current_chunk) >= self._max_chunk_chars or char in punctuation:
                if len(current_chunk) >= self._min_chunk_chars:
                    chunks.append(current_chunk)
                    current_chunk = ""

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        **kwargs
    ) -> Tuple[np.ndarray, int]:
        """
        文本转语音（优化版）
        """
        if not self.is_loaded:
            logger.warning("TTS引擎未初始化，返回模拟音频")
            return self._get_mock_audio(text)

        try:
            voice = self._normalize_voice(voice)

            logger.info(f"开始语音合成: {text[:30]}... | 声音: {voice} | 语速: {rate}")

            future = self._executor.submit(
                self._synthesize_sync_wrapper, text, voice, rate
            )

            audio_bytes = future.result(timeout=60)

            if not audio_bytes or len(audio_bytes) == 0:
                logger.warning("TTS返回空音频，使用备用方案")
                return self._generate_fallback_audio(text)

            audio, sample_rate = self._convert_audio_to_numpy(audio_bytes)
            logger.info(f"语音合成完成，音频长度: {len(audio)}")
            return audio, sample_rate

        except Exception as e:
            logger.error(f"语音合成失败: {e}")
            return self._generate_fallback_audio(text)

    def _normalize_voice(self, voice: str) -> str:
        """中文音色名映射为Edge-TTS ID"""
        voice_map = {
            "晓晓": "zh-CN-XiaoxiaoNeural",
            "云希": "zh-CN-YunxiNeural",
            "云夏": "zh-CN-YunxiaNeural",
            "云阳": "zh-CN-YunyangNeural",
            "晓辰": "zh-CN-XiaochenNeural",
            "晓东": "zh-CN-XiaodongNeural",
            "小艺": "zh-CN-XiaoyiNeural",
            "小甜": "zh-CN-XiaotianNeural",
            "晓曼": "zh-HK-HiuMaanNeural",
            "晓晨": "zh-TW-HsiaoChenNeural",
        }
        if voice in voice_map:
            return voice_map[voice]
        return voice

    def _synthesize_sync_wrapper(self, text: str, voice: str, rate: str = "+0%") -> bytes:
        """同步包装器"""
        try:
            return asyncio.run(self._synthesize_internal(text, voice, rate))
        except Exception as e:
            logger.error(f"同步包装器失败: {e}")
            return b""

    def _convert_audio_to_numpy(self, audio_data: bytes) -> Tuple[np.ndarray, int]:
        """将音频字节数据转换为numpy数组（支持MP3格式）"""
        if not audio_data or len(audio_data) == 0:
            logger.warning("输入音频数据为空")
            return np.zeros(1000, dtype=np.float32), 24000

        try:
            import miniaudio

            result = miniaudio.decode(audio_data)
            audio_np = np.array(result.samples, dtype=np.float32)

            if result.sample_width == 2:
                audio_np = audio_np / 32768.0
            elif result.sample_width == 4:
                audio_np = audio_np / 2147483648.0
            elif result.sample_width == 1:
                audio_np = audio_np / 128.0

            if result.nchannels == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1)

            logger.debug(f"miniaudio转换成功: {len(audio_np)} samples, {result.sample_rate} Hz")
            return audio_np, result.sample_rate

        except ImportError:
            logger.warning("miniaudio不可用，尝试pydub")
            try:
                from pydub import AudioSegment

                audio = AudioSegment.from_file(io.BytesIO(audio_data), format="mp3")
                sample_rate = audio.frame_rate
                channels = audio.channels
                sample_width = audio.sample_width

                samples = audio.get_array_of_samples()
                audio_np = np.array(samples, dtype=np.float32)

                if sample_width == 2:
                    audio_np = audio_np / 32768.0
                elif sample_width == 4:
                    audio_np = audio_np / 2147483648.0
                elif sample_width == 1:
                    audio_np = audio_np / 128.0

                if channels == 2:
                    audio_np = audio_np.reshape(-1, 2).mean(axis=1)

                logger.debug(f"pydub转换成功: {len(audio_np)} samples, {sample_rate} Hz")
                return audio_np, sample_rate

            except Exception as e:
                logger.error(f"pydub解码失败: {e}")
                return self._generate_fallback_audio("")
        except Exception as e:
            logger.error(f"音频转换失败: {e}")
            return self._generate_fallback_audio("")

    def _generate_fallback_audio(self, text: str) -> Tuple[np.ndarray, int]:
        """生成备用音频（当在线TTS失败时使用）"""
        logger.info("使用备用音频生成方案")
        duration = max(1.0, len(text) * 0.1)
        sample_rate = 24000
        t = np.linspace(0, duration, int(duration * sample_rate))

        audio = 0.05 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 2)

        return audio.astype(np.float32), sample_rate

    def _get_mock_audio(self, text: str) -> Tuple[np.ndarray, int]:
        """生成模拟音频"""
        duration = max(0.5, len(text) * 0.05)
        sample_rate = 24000
        t = np.linspace(0, duration, int(duration * sample_rate))
        audio = 0.01 * np.random.randn(len(t)).astype(np.float32)

        return audio, sample_rate

    def stream_synthesize(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural"
    ):
        """
        流式文本转语音生成器 - 同步版本（优化版）
        """
        if not self.is_loaded:
            logger.warning("TTS引擎未初始化，返回模拟音频")
            yield from self._stream_mock_audio(text)
            return

        try:
            logger.info(f"开始流式语音合成: {text[:30]}... | 声音: {voice}")

            voice = self._normalize_voice(voice)
            chunks = asyncio.run(self._stream_synthesize_internal(text, voice))

            for chunk in chunks:
                if chunk:
                    audio, sample_rate = self._convert_audio_to_numpy(chunk)
                    yield audio, sample_rate

            logger.info("流式语音合成完成")

        except Exception as e:
            logger.error(f"流式语音合成失败: {e}")
            yield from self._stream_mock_audio(text)

    async def _stream_synthesize_internal(self, text: str, voice: str):
        """内部流式合成方法（智能分块）"""
        if not self._edge_tts:
            return []

        try:
            # 智能分块文本
            text_chunks = self._smart_chunk_text(text)
            logger.debug(f"智能分块: {len(text_chunks)} 块")

            all_chunks = []

            for i, chunk_text in enumerate(text_chunks):
                communicate = self._edge_tts.Communicate(
                    chunk_text,
                    voice,
                    rate="+0%",
                    volume="+0%"
                )

                buffer = b""

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buffer += chunk["data"]

                        if len(buffer) >= self._stream_buffer_size:
                            all_chunks.append(buffer)
                            buffer = b""

                if buffer:
                    all_chunks.append(buffer)

            return all_chunks

        except Exception as e:
            logger.error(f"内部流式合成失败: {e}")
            return []

    def _stream_mock_audio(self, text: str):
        """生成模拟流式音频"""
        duration = max(0.5, len(text) * 0.05)
        sample_rate = 24000
        total_samples = int(duration * sample_rate)

        chunk_size = int(sample_rate * 0.05)
        num_chunks = total_samples // chunk_size

        for i in range(num_chunks):
            t = np.linspace(i * 0.05, (i + 1) * 0.05, chunk_size)
            audio = 0.01 * np.random.randn(chunk_size).astype(np.float32)
            yield audio, sample_rate

    async def stream_synthesize_text(
        self,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        **kwargs
    ) -> AsyncGenerator[Tuple[np.ndarray, int], None]:
        """
        直接异步流式合成文本 - 极低延迟版本

        使用智能分块策略，每块独立合成，实现最低延迟
        """
        if not self.is_loaded:
            logger.warning("TTS引擎未初始化")
            return

        try:
            logger.info(f"开始直接流式语音合成: {text[:30]}... | 声音: {voice}")

            voice = self._normalize_voice(voice)
            text_chunks = self._smart_chunk_text(text)
            logger.info(f"智能分块: {len(text_chunks)} 块")

            total_audio_length = 0
            for chunk_text in text_chunks:
                logger.info(f"合成块: '{chunk_text}'")
                async for audio_bytes in self._synthesize_chunk_stream(chunk_text, voice):
                    if audio_bytes:
                        logger.debug(f"原始音频字节: {len(audio_bytes)} bytes")
                        audio, sample_rate = self._convert_audio_to_numpy(audio_bytes)
                        logger.debug(f"转换后音频: {len(audio)} samples, {sample_rate} Hz")
                        total_audio_length += len(audio)
                        if len(audio) > 0:
                            yield audio, sample_rate
                        else:
                            logger.info("音频数据为空，跳过")

            logger.info(f"直接流式语音合成完成，总音频长度: {total_audio_length} samples")

        except Exception as e:
            logger.error(f"直接流式合成失败: {e}")

    def get_available_voices(self) -> list:
        """获取可用的语音列表"""
        voices = [
            {"name": "zh-CN-XiaoxiaoNeural", "description": "晓晓（温暖女声）"},
            {"name": "zh-CN-YunxiNeural", "description": "云希（稳重男声）"},
            {"name": "zh-CN-YunxiaNeural", "description": "云夏（活力女声）"},
            {"name": "zh-CN-YunyangNeural", "description": "云阳（成熟男声）"},
            {"name": "zh-CN-XiaoyiNeural", "description": "小艺（年轻女声）"},
            {"name": "zh-CN-XiaotianNeural", "description": "小甜（甜美女声）"},
            {"name": "zh-CN-XiaozhiNeural", "description": "小智（阳光男声）"},
            {"name": "zh-CN-XiaomoNeural", "description": "晓墨（低沉女声）"},
            {"name": "zh-CN-YunjianNeural", "description": "云健（稳重男声）"},
            {"name": "zh-HK-HiuMaanNeural", "description": "晓曼（粤语女声）"},
            {"name": "zh-TW-HsiaoChenNeural", "description": "晓晨（台语女声）"},
        ]
        return voices
