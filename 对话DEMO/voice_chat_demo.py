"""
YHLZ 2.0 语音对话 Demo (独立可跑通)
================================
参考: 下载物象/学习笔记_NachoBot研究报告.md
      下载物象/学习笔记_AIRI研究报告.md

完整闭环: 麦克风 → VAD → ASR → LLM流式 → 句级切分 → 流式TTS → 队列播放 → 回声过滤 → 连续对话

借鉴 NachoBot 的 4 个关键纪律:
  1. 句级切分 + 首段即触发 + 队列播放 (低延迟流式)
  2. 回声过滤 (播放期间禁止识别, 防自嗨)
  3. 任务隔离 (录音/识别/播放分线程, 用队列解耦)
  4. LLM 只在关键节点介入 (ASR/LLM/TTS 各司其职)

运行:
    python 对话DEMO/voice_chat_demo.py                    # 默认 Edge-TTS (轻量快速)
    python 对话DEMO/voice_chat_demo.py --engine qwen3-tts-customvoice  # 用 Qwen3 本地 TTS
    python 对话DEMO/voice_chat_demo.py --text "你好"      # 跳过 ASR, 直接文本输入测试
    python 对话DEMO/voice_chat_demo.py --once             # 单轮对话后退出 (不做连续)

依赖: backend/ 下的 asr_engine / tts_engine / llm_engine / vad_engine
"""

import argparse
import asyncio
import collections
import logging
import re
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# ── 统一 UTF-8 编码 (避免 Windows 下中文/emoji 乱码) ──
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── 项目根目录加入 sys.path (允许 demo/ 独立运行) ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("voice_chat_demo")

# ── 音频参数 ──
SAMPLE_RATE = 16000          # ASR/VAD 要求 16kHz
FRAME_SIZE = 1600            # 100ms/帧 (VAD 帧)
CHANNELS = 1
SILENCE_TIMEOUT = 8.0        # 单次录音最长 8 秒
MIN_SPEECH_DURATION = 0.3    # 最短语音段 0.3 秒 (太短丢弃)
MIN_PENDING_SPEECH_DURATION = 0.2  # 播放期间插话最短 0.2 秒 (插话通常更短)
ECHO_GAIN_RATIO = 1.6        # 音量遮蔽: 插话 RMS 需 > AI 播放音量 × 1.6 才算语音
ECHO_OVERLAP_RATIO = 0.6     # 防循环: 插话与刚播文本字符重叠 > 60% 判回声

# ── TTS 引擎选择 ──
DEFAULT_TTS_ENGINE = "qwen3-tts-customvoice"  # Demo 仅使用 Qwen3-TTS 本地引擎


# ============================================================
# 延迟追踪器
# ============================================================
class LatencyTracker:
    """记录各环节时间戳, 每轮对话结束输出延迟报告"""

    def __init__(self):
        self.marks: dict = {}

    def reset(self):
        self.marks = {}

    def mark(self, event: str):
        self.marks[event] = time.time()

    def _delta_ms(self, a: str, b: str) -> str:
        if a in self.marks and b in self.marks:
            return f"{(self.marks[b] - self.marks[a]) * 1000:.0f}ms"
        return "N/A"

    def report(self) -> str:
        m = self.marks
        lines = [
            "",
            "=" * 52,
            "  延迟追踪报告",
            "=" * 52,
            f"  语音段时长:       {self._delta_ms('vad_start', 'vad_end')}",
            f"  ASR 识别耗时:     {self._delta_ms('asr_start', 'asr_done')}",
            f"  LLM 首字延迟:     {self._delta_ms('llm_start', 'llm_first')}",
            f"  LLM 总生成耗时:   {self._delta_ms('llm_start', 'llm_done')}",
            f"  TTS 首句合成:     {self._delta_ms('tts_start', 'tts_done')}",
            f"  首句入队→播放:    {self._delta_ms('tts_done', 'play_start')}",
            "-" * 52,
            f"  ★ 端到端(说完→听到): {self._delta_ms('vad_end', 'play_start')}",
            f"  ★ 总响应(开口→听到): {self._delta_ms('vad_start', 'play_start')}",
            "=" * 52,
            "",
        ]
        return "\n".join(lines)


# ============================================================
# 句级切分 (参考 NachoBot text_splitter: cut5 标点优先 + 短句合并)
# ============================================================
def split_text_for_streaming(text: str, min_segment_length: int = 8,
                             max_length: int = 50) -> List[str]:
    """语义级碎片合并 + markdown 残留剥离

    保留原调用约束:
      - 返回的每段保留句末标点 (调用点判断 sentences[0][-1:] in 标点)
      - 标点(。！？；!?;…)直断, 逗号累积 >=min_segment_length 才断
      - 超过 max_length 安全上限强制断
    叠加优化:
      - 口语前缀 (好的/嗯/然后/那你...) 粘连到下一段, 减少孤立碎片
      - 段内剥离 markdown 残留 ( ** ` 等)
    """
    text = re.sub(r'[*_~`]', '', text)
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)
    text = re.sub(r'#+\s*', '', text)
    text = text.strip()
    if not text:
        return []

    raw_parts = re.split(r'([。！？；!?…]+)', text)
    clauses = []
    for i in range(0, len(raw_parts) - 1, 2):
        content = raw_parts[i]
        punct = raw_parts[i + 1]
        if content.strip():
            clauses.append((content.strip(), punct))

    remainder = raw_parts[-1].strip() if raw_parts else ''
    if remainder:
        clauses.append((remainder, ''))

    segments: List[str] = []
    for content, punct in clauses:
        if not content:
            continue
        if punct in ('。', '！', '？', '…'):
            segments.append(content + punct)
        elif len(content) >= max_length:
            segments.append(content + punct)
        else:
            sub_parts = re.split(r'([，,：:、])', content)
            buf = ''
            for j in range(0, len(sub_parts) - 1, 2):
                seg = sub_parts[j]
                sep = sub_parts[j + 1]
                buf += seg + sep
                if len(buf) >= min_segment_length:
                    segments.append(buf.strip())
                    buf = ''
            buf += sub_parts[-1] if sub_parts else ''
            buf = buf.strip()
            if buf:
                segments.append(buf + punct if punct else buf)

    oral_prefixes = (
        '好的', '嗯', '啊', '哦', '噢', '行', '对', '是的',
        '那个', '然后', '那你', '这个', '就是', '不过',
        '嗯嗯', '好好', '行行', '可以', '没问题', '好吧',
    )
    merged: List[str] = []
    skip_next = False
    for i in range(len(segments)):
        if skip_next:
            skip_next = False
            continue
        seg = segments[i]
        stripped = seg.strip()
        is_prefix = (
            len(stripped) <= 6
            and stripped.rstrip('，,、 ') in oral_prefixes
            and not any(stripped.endswith(p) for p in '。！？；!?…')
        )
        if is_prefix and i + 1 < len(segments):
            merged.append(stripped + segments[i + 1])
            skip_next = True
        elif merged and len(stripped) < min_segment_length and not any(stripped.endswith(p) for p in '。！？；!?…'):
            merged[-1] = merged[-1] + stripped
        else:
            merged.append(seg)

    return [s for s in merged if s.strip()]


# ============================================================
# 录音器: sounddevice 流式录音 + VAD 状态机
# ============================================================
class Recorder:
    """流式录音 + VAD 检测, 输出完整语音段
    支持 barge-in 打断: AI 播放期间检测用户说话 → 中断播放
    """

    def __init__(self, vad_engine, tracker: Optional[LatencyTracker] = None,
                 player: Optional["Player"] = None):
        self.vad = vad_engine
        self.tracker = tracker
        self.player = player  # barge-in: 引用 Player 用于打断
        self._stream = None
        self._lock = threading.Lock()
        self._is_recording = False
        self._paused = False  # 回声过滤: 播放期间暂停正常识别
        self._frames: List[np.ndarray] = []
        self._speech_started = False
        self._start_time = 0.0
        self._on_speech_end: Optional[callable] = None
        # barge-in: 播放期间持续检测语音, 连续 N 帧才确认打断 (防误触)
        self._barge_in_count = 0
        self._barge_in_threshold = 3  # 连续 3 帧语音 (~192ms) 才确认打断
        self._barge_in_triggered = False
        # 预滚动环形缓冲: 保留 1 秒音频, 防 ASR 丢开头字
        self._preroll = collections.deque(maxlen=int(SAMPLE_RATE / FRAME_SIZE))
        # 播放期间插话排队 (方案A: 不打断, 播完再处理)
        self._pending_segments = collections.deque(maxlen=8)
        self._queue_lock = threading.Lock()
        # 音量遮蔽: AI 播放音量基准 (一阶低通平滑, 防静音帧骤降)
        self._ai_play_volume = 0.0
        self._smooth_rms = 0.0

    def set_paused(self, paused: bool):
        """回声过滤: 播放期间暂停正常识别, 但仍检测插话 (方案A: 不打断)"""
        with self._lock:
            self._paused = paused
            self._barge_in_count = 0
            self._barge_in_triggered = False
            if paused:
                # 播放开始: 清空正在采集的帧 (播放前的残留不应计入插话)
                self._frames.clear()
                self._speech_started = False
                self.vad.reset()
            # 恢复时不清 _speech_started, 播放结束后的正常识别照常
            self._ai_play_volume = 0.0

    def start(self, on_speech_end):
        self._on_speech_end = on_speech_end
        import sounddevice as sd
        self._is_recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=FRAME_SIZE,
            callback=self._callback,
        )
        self._stream.start()
        logger.info("麦克风录音已启动 (VAD 能量检测)")

    def stop(self):
        self._is_recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("麦克风录音已停止")

    def _callback(self, indata, frames, time_info, status):
        if not self._is_recording:
            return

        frame = indata[:, 0].copy()

        # VAD 检测 (无论是否暂停都做)
        is_speech = self.vad.detect_speech(frame, SAMPLE_RATE)

        with self._lock:
            if self._paused:
                # 播放期间: 方案A 不打断, 只采集插话 (音量遮蔽滤回声)
                frame_rms = float(np.sqrt(np.mean(frame ** 2)))
                # 遮蔽: 用户声音需明显大于 AI 播放音量 (防止把 AI 回声当插话)
                speech_now = is_speech and (frame_rms > self._ai_play_volume * ECHO_GAIN_RATIO)

                if not self._speech_started and speech_now:
                    self._speech_started = True
                    self._start_time = time.time()
                    # 预滚动: 含播放前残留 1s (可能混有回声, 靠遮蔽+防循环兜底)
                    self._frames = list(self._preroll)
                    self._preroll.clear()
                    logger.info("🗒️  播放期间检测到插话开始 (音量遮蔽通过)")
                if self._speech_started:
                    # 只 append 语音帧 (静音帧不累计, 保证 duration 是真实插话长度)
                    if speech_now:
                        self._frames.append(frame)
                    # VAD 判定说完 → 排队 (不触发任何打断)
                    if not self.vad.is_speaking():
                        self._flush_pending_speech()
                        self._speech_started = False

                # 预滚动缓冲: 播放期间也保留音频
                self._preroll.append(frame)
                return

            # 正常模式: 非播放期间
            self._preroll.append(frame)

            if is_speech and not self._speech_started:
                self._speech_started = True
                self._start_time = time.time()
                # 预滚动: 把 ring buffer 里的音频也包含进去 (防丢开头字)
                self._frames = list(self._preroll)
                self._preroll.clear()
                if self.tracker:
                    self.tracker.reset()
                    self.tracker.mark("vad_start")
                logger.info("🎙️  检测到语音开始 (含预滚动缓冲)")
            if self._speech_started:
                self._frames.append(frame)
                # 超时保护
                if time.time() - self._start_time > SILENCE_TIMEOUT:
                    self._flush_speech()

    def _flush_pending_speech(self):
        """播放期间插话: VAD 判定说完 → 入队 (不打断, 播完再处理)"""
        frames = self._frames
        self._frames = []
        if not frames:
            return
        audio = np.concatenate(frames)
        duration = len(audio) / SAMPLE_RATE
        if duration < MIN_PENDING_SPEECH_DURATION:
            logger.debug(f"插话过短 ({duration:.2f}s), 丢弃")
            return
        with self._queue_lock:
            self._pending_segments.append((audio, time.time(), duration))
        logger.info(f"🗒️  播放期间插话已排队: {duration:.2f}s, {len(audio)} samples")

    def has_pending(self) -> bool:
        with self._queue_lock:
            return len(self._pending_segments) > 0

    def push_pending(self, audio: np.ndarray, duration: float):
        """锁超时兜底: 非播放期被吞的语音段也统一入队, 保证不静默丢弃"""
        with self._queue_lock:
            self._pending_segments.append((audio, time.time(), duration))

    def pop_pending(self):
        with self._queue_lock:
            return self._pending_segments.popleft() if self._pending_segments else None

    def set_ai_play_volume(self, rms: float):
        """Player 播放时回调: 记录 AI 播放音量作为回声基准 (低通平滑)"""
        self._smooth_rms = self._smooth_rms * 0.8 + rms * 0.2
        self._ai_play_volume = self._smooth_rms

    def _flush_speech(self):
        """VAD 状态机进入 silence 时调用 (外部触发或超时)"""
        if not self._speech_started:
            return
        self._speech_started = False
        if self.tracker:
            self.tracker.mark("vad_end")
        frames = self._frames
        self._frames = []
        if not frames:
            return

        audio = np.concatenate(frames)
        duration = len(audio) / SAMPLE_RATE
        if duration < MIN_SPEECH_DURATION:
            logger.debug(f"语音段过短 ({duration:.2f}s), 丢弃")
            return

        logger.info(f"✅ 语音段采集完成: {duration:.2f}s, {len(audio)} samples")
        if self._on_speech_end:
            # 在独立线程回调, 避免阻塞录音回调
            threading.Thread(
                target=self._on_speech_end, args=(audio,), daemon=True
            ).start()

    def check_silence_timeout(self):
        """主循环调用: 检测 VAD 状态机是否回到 silence (一句话说完)"""
        with self._lock:
            if self._speech_started and not self.vad.is_speaking():
                self._flush_speech()


# ============================================================
# 播放器: 队列顺序播放 (回声过滤联动)
# ============================================================
class Player:
    """音频队列播放, 播放期间通知 Recorder 暂停识别"""

    def __init__(self, recorder: Optional["Recorder"] = None,
                 tracker: Optional[LatencyTracker] = None):
        self.recorder = recorder  # 可选, 文本模式无 Recorder
        self.tracker = tracker
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._interrupt = threading.Event()
        self._first_play_marked = False
        # 连续播放缓冲 (OutputStream + callback, 无间隙无截断)
        self._audio_buf = np.array([], dtype=np.float32)
        self._buf_lock = threading.Lock()
        self._stream = None
        self._stream_sr = 24000
        self._buf_empty_count = 0
        # barge-in 打断: is_playing 标记 AI 是否在播放
        self.is_playing = False
        self._on_interrupt: Optional[callable] = None
        # 插话方案A: 播放完成回调 (处理排队插话)
        self.on_play_done: Optional[callable] = None

    def start(self):
        self._running = True
        self._interrupt.clear()
        self._first_play_marked = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("音频播放线程已启动")

    def stop(self):
        self._running = False
        self._interrupt.set()
        self._queue.put(None)  # 哨兵唤醒
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        # 关闭 OutputStream
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def enqueue(self, audio: np.ndarray, sample_rate: int):
        self._queue.put((audio, sample_rate))

    def interrupt(self):
        """用户打断: 清空队列和缓冲, 停止当前播放, 通知上层中断 LLM/TTS 任务"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._interrupt.set()
        with self._buf_lock:
            self._audio_buf = np.array([], dtype=np.float32)
        # barge-in 回调: 让 VoiceChatDemo 中断 LLM 流式 + TTS worker, 防止句子串台
        if self._on_interrupt:
            try:
                self._on_interrupt()
            except Exception as e:
                logger.error(f"_on_interrupt 回调失败: {e}")

    def _loop(self):
        import sounddevice as sd

        def _audio_callback(outdata, frames, time_info, status):
            """OutputStream callback: 从缓冲区连续读取, 无间隙无截断"""
            with self._buf_lock:
                buf = self._audio_buf
                if len(buf) >= frames:
                    outdata[:, 0] = buf[:frames]
                    self._audio_buf = buf[frames:]
                    self._buf_empty_count = 0
                elif len(buf) > 0:
                    # 缓冲区不足, 播完剩余 + 补静音
                    n = len(buf)
                    outdata[:n, 0] = buf
                    outdata[n:, 0] = 0
                    self._audio_buf = np.array([], dtype=np.float32)
                    self._buf_empty_count = 0
                else:
                    # 缓冲区空, 输出静音 (保持流不中断)
                    outdata[:, 0] = 0
                    self._buf_empty_count += 1

            # 上报 AI 播放音量 (音量遮蔽的回声基准), 静音帧用 0 压低平滑值
            if self.recorder:
                self.recorder.set_ai_play_volume(
                    float(np.sqrt(np.mean(outdata[:, 0] ** 2)))
                )

        while self._running:
            item = self._queue.get()
            try:
                if item is None:
                    break
                audio, sr = item
                if audio is None or len(audio) == 0:
                    continue

                # 播放开始 → 暂停录音 (回声过滤)
                if self.recorder:
                    self.recorder.set_paused(True)
                self._interrupt.clear()
                self.is_playing = True  # barge-in: 标记 AI 正在播放

                if self.tracker and not self._first_play_marked:
                    self.tracker.mark("play_start")
                    self._first_play_marked = True

                logger.info(f"🔊 入队音频: {len(audio)} samples, {sr} Hz")

                # 无缝拼接: 直接追加到连续播放缓冲区 (不另加 padding)
                with self._buf_lock:
                    self._audio_buf = np.concatenate(
                        [self._audio_buf, audio.astype(np.float32)]
                    ) if len(self._audio_buf) > 0 else audio.astype(np.float32)

                # 启动 OutputStream (如果未运行或采样率变化)
                need_new_stream = (
                    self._stream is None
                    or not self._stream.active
                    or self._stream_sr != sr
                )
                if need_new_stream:
                    if self._stream is not None:
                        try:
                            self._stream.stop()
                            self._stream.close()
                        except Exception:
                            pass
                    self._stream_sr = sr
                    self._stream = sd.OutputStream(
                        samplerate=sr,
                        channels=1,
                        dtype='float32',
                        callback=_audio_callback,
                        blocksize=2048,
                    )
                    self._stream.start()

                # 段播放循环: 持续取队列中积压块拼入缓冲, 直到队列空且缓冲播完
                while self._running and not self._interrupt.is_set():
                    # 非阻塞取走队列中所有积压块, 立即拼入 (块间无静音)
                    while True:
                        try:
                            nxt = self._queue.get_nowait()
                        except queue.Empty:
                            break
                        if nxt is None:
                            self._running = False
                            break
                        n_audio, n_sr = nxt
                        if n_audio is None or len(n_audio) == 0:
                            self._queue.task_done()
                            continue
                        logger.info(f"🔊 入队音频: {len(n_audio)} samples, {n_sr} Hz")
                        if n_sr != sr and self._stream is not None:
                            # 采样率变化, 重启流 (极少发生)
                            try:
                                self._stream.stop()
                                self._stream.close()
                            except Exception:
                                pass
                            self._stream_sr = n_sr
                            self._stream = sd.OutputStream(
                                samplerate=n_sr, channels=1, dtype='float32',
                                callback=_audio_callback, blocksize=2048,
                            )
                            self._stream.start()
                        with self._buf_lock:
                            self._audio_buf = np.concatenate(
                                [self._audio_buf, n_audio.astype(np.float32)]
                            ) if len(self._audio_buf) > 0 else n_audio.astype(np.float32)
                        self._queue.task_done()

                    with self._buf_lock:
                        buf_len = len(self._audio_buf)
                    if buf_len == 0 and self._queue.empty() and self._buf_empty_count >= 3:
                        break
                    time.sleep(0.02)

                if self._interrupt.is_set() or not self._running:
                    # 打断/停止: 停流 + 清缓冲 + 清队列
                    if self._stream:
                        try:
                            self._stream.stop()
                        except Exception:
                            pass
                    with self._buf_lock:
                        self._audio_buf = np.array([], dtype=np.float32)
                    while not self._queue.empty():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    self._buf_empty_count = 0
                    self.is_playing = False  # barge-in: 标记播放结束
                    logger.info("⏹️  播放被打断")
                else:
                    self.is_playing = False  # barge-in: 标记播放结束
                    logger.info("✅ 播放完成")
                    # 插话方案A: 播完后通知上层处理排队插话
                    if self.on_play_done:
                        try:
                            self.on_play_done()
                        except Exception as e:
                            logger.error(f"on_play_done 回调失败: {e}")
            except Exception as e:
                logger.error(f"播放失败: {e}")
            finally:
                if self.recorder:
                    self.recorder.set_paused(False)
                    time.sleep(0.15)
                self._queue.task_done()


# ============================================================
# 语音对话主控
# ============================================================
class VoiceChatDemo:
    def __init__(self, args):
        self.args = args
        self.tts_engine_name = args.engine or DEFAULT_TTS_ENGINE

        # 引擎 (延迟导入, 让环境变量先生效)
        os.environ.setdefault("TTS_ENGINE", self.tts_engine_name)
        from backend.config import config
        from backend.asr_engine import asr_engine
        from backend.tts_engine import tts_engine, tts_manager
        from backend.llm_engine import llm_engine
        from backend.vad_engine import vad_engine

        self.config = config
        self.asr = asr_engine
        self.tts = tts_engine
        self.tts_manager = tts_manager
        self.llm = llm_engine
        self.vad = vad_engine

        # 对话历史
        self.history: List[dict] = []
        self.system_prompt = (
            "你是元亨, 是用户的铁哥们, 说话随意亲切像兄弟一样。"
            "用口语化、自然的中文回复, 每次回复控制在 2-3 句话以内。"
            "不要使用 markdown 格式或列表。"
        )

        # 组件
        self.recorder: Optional[Recorder] = None
        self.player: Optional[Player] = None
        self.voice = "Vivian"  # 默认音色, load_engines() 内会按引擎覆盖
        self.tracker = LatencyTracker()

        # 状态
        self._processing = threading.Lock()  # 同一时刻只处理一句话
        self._pending_lock = threading.Lock()  # 排队队列消费者互斥: 同一时刻只一个线程在消化队列
        self._should_stop = False
        # barge-in 任务令牌: 每次 +1 让旧的 LLM/TTS 任务及时退出, 防止句子串台
        self._gen_token = 0
        # 插话方案A: 正在处理排队插话的标志 (保证插话紧跟对应 assistant 回复)
        self._is_processing_pending = False

    # ── 引擎加载 ──
    def load_engines(self):
        logger.info("=" * 60)
        logger.info("YHLZ 2.0 语音对话 Demo")
        logger.info("=" * 60)

        # 强制激活指定的 TTS 引擎 (activate 内部会自动 load)
        if not self.tts_manager.activate(self.tts_engine_name):
            raise RuntimeError(f"TTS 引擎 {self.tts_engine_name} 激活失败")
        active = self.tts_manager.active_engine
        active_name = self.tts_manager._active_name or "unknown"
        logger.info(f"TTS 引擎: {active_name} (loaded={bool(active and active.is_loaded)})")

        # Qwen3-CustomVoice 固定使用 Vivian 音色
        self.voice = "Vivian"
        logger.info(f"默认音色: {self.voice}")

        # ASR (SenseVoiceSmall, 首次会下载/加载模型, 耗时较长)
        if self.args.text:
            logger.info("文本输入模式, 跳过 ASR 加载")
        else:
            logger.info("正在加载 ASR 引擎 (SenseVoiceSmall) ...")
            ok = self.asr.load_model(direct_gpu=True)
            if not ok:
                raise RuntimeError("ASR 引擎加载失败, 无法继续")
            logger.info("ASR 引擎加载完成")

        # LLM 连接检查
        if not self.llm.is_connected:
            logger.warning("LLM 引擎未连接 (检查 .env 中的 DASHSCOPE_API_KEY)")
        else:
            logger.info(f"LLM 引擎已连接: {self.config.api_provider} / {self.config.dashscope_model}")

        # 注: TTS warmup 由 faster-qwen3-tts 引擎 load() 内置完成 (CUDA graph 预热)

        logger.info("=" * 60)

    # ── barge-in 回调: 由 Player.interrupt() 触发 ──
    def _on_player_interrupt(self):
        """barge-in 触发: 令牌 +1 让旧的 LLM 流式 + TTS worker 退出, 防止句子串台"""
        self._gen_token += 1
        logger.info(f"🛑 barge-in 中断当前生成任务 (新 token={self._gen_token})")

    # ── 插话方案A: 播放完成回调 → 处理排队插话 ──
    def _on_play_done(self):
        if not self.recorder.has_pending():
            return
        threading.Thread(target=self._process_pending_segments, daemon=True).start()

    def _process_pending_segments(self):
        """处理排队语音段 (播放期插话 + 锁超时补话): 相邻短段合并 → ASR → 防回声 → 回复

        保证任何语音段都不被静默丢弃; 锁占用时等待重试而非丢弃。
        """
        if not self._pending_lock.acquire(blocking=False):
            return  # 已有消费者在消化队列
        self._is_processing_pending = True
        try:
            # 队列按 ts 时间戳顺序消化; 相邻 (<1.5s) 且合并后 <50 字的段合并成一句
            merged_text = ""
            merged_ts = None
            prev_ts = None

            def _flush(flush_text: str, ts: float):
                nonlocal merged_text, merged_ts
                text = flush_text.strip()
                if not text:
                    return
                if self._is_echo(text):
                    logger.info(f"⛔ 插话识别 '{text[:20]}' 疑似回声, 丢弃")
                    return
                logger.info(f"🗣️  插话(排队段): {text}")
                # 等待主处理锁; 拿不到就重试, 绝不丢弃
                while not self._processing.acquire(timeout=5.0):
                    logger.warning("[QUEUE] 等待主处理锁中... (排队段不丢弃)")
                try:
                    # _generate_and_speak 内部已 append user 消息, 这里不再重复
                    asyncio.run(self._generate_and_speak(text))
                except Exception as e:
                    logger.error(f"处理排队插话失败: {e}", exc_info=True)
                finally:
                    self._processing.release()

            while True:
                item = self.recorder.pop_pending()
                if item is None:
                    break
                audio, ts, dur = item
                text = self.asr.transcribe(audio, sample_rate=SAMPLE_RATE) or ""
                text = text.strip()
                if not text:
                    prev_ts = ts
                    continue
                # 相邻短段合并 (碎片如 "对" "然后" "那个" 合并为一句)
                if (
                    prev_ts is not None
                    and ts - prev_ts < 1.5
                    and len(merged_text) + len(text) <= 50
                ):
                    merged_text += text
                    merged_ts = ts
                    logger.info(f"[QUEUE] 合并相邻短段 → '{merged_text}'")
                else:
                    if merged_text:
                        _flush(merged_text, merged_ts or ts)
                    merged_text = text
                    merged_ts = ts
                prev_ts = ts

            if merged_text:
                _flush(merged_text, merged_ts or 0.0)
        finally:
            self._is_processing_pending = False
            self._pending_lock.release()

    def _is_echo(self, text: str) -> bool:
        """防循环: 插话与刚播的 assistant 文本字符重叠超过阈值判回声"""
        last_assistant = next((m["content"] for m in reversed(self.history)
                               if m["role"] == "assistant"), "")
        if not last_assistant:
            return False
        chars = set(text)
        overlap = len(chars & set(last_assistant))
        ratio = overlap / max(len(chars), 1)
        return ratio > ECHO_OVERLAP_RATIO

    # ── ASR 回调: 拿到语音段后识别 → LLM → TTS → 播放 ──
    def _on_speech_end(self, audio: np.ndarray):
        # barge-in 后上一轮 _generate_and_speak 可能还在退出途中, 这里给 2s 等待窗口
        # 避免新一轮语音段被丢弃 (用户已经开口说话, 必须被处理)
        # 历史顺序: 若正在处理排队插话, 等它先落地 (保证插话紧跟 assistant 回复)
        for _ in range(20):
            if not self._is_processing_pending:
                break
            time.sleep(0.05)
        if not self._processing.acquire(timeout=2.0):
            # 超时不丢弃: 语音段转排队队列, 由 _process_pending_segments 消化
            duration = len(audio) / SAMPLE_RATE
            self.recorder.push_pending(audio, duration)
            logger.warning(f"[QUEUE] 锁占用超时, 语音段({duration:.2f}s)转入排队, 不丢弃")
            # 若当前没有消费者在消化队列, 启动一个
            if not self._is_processing_pending:
                threading.Thread(target=self._process_pending_segments, daemon=True).start()
            return
        try:
            self._handle_turn(audio)
        except Exception as e:
            logger.error(f"处理本轮对话失败: {e}", exc_info=True)
        finally:
            self._processing.release()

    def _handle_turn(self, audio: np.ndarray):
        # 每轮对话开始, 重置追踪器 (vad_start/vad_end 已由 Recorder 记录)
        # 1. ASR 识别
        self.tracker.mark("asr_start")
        logger.info("📝 正在识别...")
        text = self.asr.transcribe(audio, sample_rate=SAMPLE_RATE)
        self.tracker.mark("asr_done")
        text = (text or "").strip()
        if not text:
            logger.info("识别结果为空, 跳过")
            return
        logger.info(f"👤 你: {text}")

        # 2. LLM 流式生成 + 句级切分 + 流式 TTS
        asyncio.run(self._generate_and_speak(text))

    async def _generate_and_speak(self, user_text: str):
        """分段流式: LLM 流式生成 → 句级切分 → 并行预合成 → 顺序入队播放

        核心优化 (解决句子之间卡顿):
        - 每段句子独立 asyncio task 合成, LLM 出句即可立即创建合成任务
        - _play_dispatcher 按 seq 顺序把音频 chunk 入 player 队列, 保证播放顺序
        - 这样 TTS 合成请求尽早"排队", 不用等上一段合成完才开始下一段

        barge-in 支持: 全程用 my_token 监测 _gen_token, 被中断时立即停止。
        """
        my_token = self._gen_token
        def interrupted() -> bool:
            return self._gen_token != my_token

        self.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self.system_prompt}] + self.history[-8:]

        self.tracker.mark("llm_start")
        logger.info("🤖 正在生成回复 (并行预合成模式)...")
        full_reply = ""
        sentence_buf = ""
        first_token_marked = False
        first_tts_marked = False

        # 并行合成: 每段独立 task, 通过 play_queue 把音频 chunk 按 seq 发给 dispatcher
        # item 格式: (seq, audio, sr, is_end)
        #   - audio != None: 流式 chunk (is_end=False)
        #   - audio == None, is_end=True: 该段合成结束
        play_queue: asyncio.Queue = asyncio.Queue()
        synth_tasks: List[asyncio.Task] = []
        seq_counter = 0

        async def _synth_one(seq: int, sentence: str, is_first_sentence: bool):
            """合成一段, 流式 chunk 直接送入 play_queue (dispatcher 保证顺序)"""
            nonlocal first_tts_marked
            try:
                first_chunk_marked = False
                accum_buf = []
                accum_len = 0
                accum_sr = None
                # 首片阈值降到 0.17s (4000 samples @24kHz), 让首片更早入队
                min_flush_samples = 4000

                async for audio_chunk, sr in self.tts.stream_synthesize_text(
                    sentence, voice=self.voice
                ):
                    if interrupted():
                        logger.info(f"🛑 TTS[{seq}] 流式合成被中断, 停止")
                        break
                    if audio_chunk is None or len(audio_chunk) == 0:
                        continue
                    accum_sr = sr
                    accum_buf.append(audio_chunk)
                    accum_len += len(audio_chunk)

                    # 首片立即送 dispatcher (低延迟), 后续累积到 0.17s 再 flush
                    if not first_chunk_marked:
                        merged = np.concatenate(accum_buf)
                        await play_queue.put((seq, merged, sr, False))
                        if not first_tts_marked:
                            self.tracker.mark("tts_done")
                            first_tts_marked = True
                        first_chunk_marked = True
                        accum_buf = []
                        accum_len = 0
                    elif accum_len >= min_flush_samples:
                        merged = np.concatenate(accum_buf)
                        await play_queue.put((seq, merged, sr, False))
                        accum_buf = []
                        accum_len = 0

                # flush 句子剩余 (中断时不 flush)
                if accum_buf and not interrupted():
                    merged = np.concatenate(accum_buf)
                    await play_queue.put((seq, merged, accum_sr or self.tts._sample_rate, False))
                    if is_first_sentence and not first_chunk_marked:
                        if not first_tts_marked:
                            self.tracker.mark("tts_done")
                            first_tts_marked = True
                        first_chunk_marked = True

                # 流式未产出 chunk 时回退到整段合成
                if not first_chunk_marked and not interrupted():
                    audio, sr = await asyncio.to_thread(
                        self.tts.synthesize, sentence, voice=self.voice
                    )
                    if audio is not None and len(audio) > 0:
                        await play_queue.put((seq, audio, sr, False))
                        if is_first_sentence and not first_tts_marked:
                            self.tracker.mark("tts_done")
                            first_tts_marked = True
            except Exception as e:
                logger.error(f"TTS[{seq}] 合成失败 ('{sentence}'): {e}")
            finally:
                # 段结束标记 (无论成功失败都要发, 否则 dispatcher 卡住)
                await play_queue.put((seq, None, None, True))

        async def _play_dispatcher():
            """按 seq 顺序从 play_queue 取音频, 入 player 队列保证播放顺序

            收到 None 哨兵后, 把 pending 中剩余的按顺序全部输出再退出。
            """
            next_seq = 0
            # pending[seq] = {"chunks": [(audio, sr), ...], "finished": bool}
            pending: dict = {}

            while True:
                item = await play_queue.get()
                if item is None:  # 全局结束哨兵
                    break
                seq, audio, sr, is_end = item

                if seq not in pending:
                    pending[seq] = {"chunks": [], "finished": False}

                if audio is not None:
                    pending[seq]["chunks"].append((audio, sr))

                if is_end:
                    pending[seq]["finished"] = True

                # 推进: 把已结束的段按顺序输出
                while next_seq in pending and pending[next_seq]["finished"]:
                    chunks = pending[next_seq]["chunks"]
                    for a, s in chunks:
                        self.player.enqueue(a, s)
                    pending.pop(next_seq)
                    next_seq += 1

                # 当前段未结束但已有 chunk, 且 next_seq 指向它 → 流式输出已到 chunk
                if next_seq in pending and not pending[next_seq]["finished"]:
                    chunks = pending[next_seq]["chunks"]
                    if chunks:
                        for a, s in chunks:
                            self.player.enqueue(a, s)
                        pending[next_seq]["chunks"] = []

            # 收尾: 输出剩余 (中断场景)
            while next_seq in pending:
                chunks = pending[next_seq]["chunks"]
                for a, s in chunks:
                    self.player.enqueue(a, s)
                pending.pop(next_seq)
                next_seq += 1

        # dispatcher 先启动, 后面通过 None 哨兵通知结束
        dispatcher_task = asyncio.create_task(_play_dispatcher())

        # LLM 流式生成 + 句级切分 → 启动并行合成 task
        try:
            async for chunk in self.llm.generate_stream(
                messages, temperature=0.7, max_tokens=512
            ):
                if interrupted():
                    logger.info("🛑 LLM 流式生成被中断, 停止接收")
                    break
                if not first_token_marked:
                    self.tracker.mark("llm_first")
                    first_token_marked = True
                full_reply += chunk
                sentence_buf += chunk
                print(chunk, end="", flush=True)

                # 句级切分 (更激进: min_segment_length=4, 让句子更短更早入队)
                sentences = split_text_for_streaming(sentence_buf, min_segment_length=4)
                if len(sentences) > 1:
                    ready = sentences[0]
                    sentence_buf = "".join(sentences[1:])
                    is_first = not first_tts_marked
                    if is_first:
                        self.tracker.mark("tts_start")
                    t = asyncio.create_task(_synth_one(seq_counter, ready, is_first))
                    synth_tasks.append(t)
                    seq_counter += 1
                elif len(sentences) == 1 and sentences[0][-1:] in "。！？；!?;…":
                    ready = sentences[0]
                    sentence_buf = ""
                    is_first = not first_tts_marked
                    if is_first:
                        self.tracker.mark("tts_start")
                    t = asyncio.create_task(_synth_one(seq_counter, ready, is_first))
                    synth_tasks.append(t)
                    seq_counter += 1
        except Exception as e:
            logger.error(f"LLM 流式生成异常: {e}")

        print()
        self.tracker.mark("llm_done")

        # 处理剩余文本 (中断时不再入队)
        if sentence_buf.strip() and not interrupted():
            is_first = not first_tts_marked
            if is_first:
                self.tracker.mark("tts_start")
            t = asyncio.create_task(_synth_one(seq_counter, sentence_buf.strip(), is_first))
            synth_tasks.append(t)
            seq_counter += 1

        # 等待所有合成 task 完成 (最多 5s, 中断时 1s)
        if synth_tasks:
            wait_timeout = 1.0 if interrupted() else 5.0
            try:
                await asyncio.wait_for(
                    asyncio.gather(*synth_tasks, return_exceptions=True),
                    timeout=wait_timeout
                )
            except asyncio.TimeoutError:
                if not interrupted():
                    logger.warning(f"合成 task 未在 {wait_timeout}s 内完成, 强制取消")
                for t in synth_tasks:
                    if not t.done():
                        t.cancel()

        # 通知 dispatcher 结束
        await play_queue.put(None)
        try:
            await asyncio.wait_for(dispatcher_task, timeout=2.0)
        except asyncio.TimeoutError:
            dispatcher_task.cancel()

        # 被中断时不记录助手回复, 让新一轮重新生成
        if interrupted():
            logger.info("🛑 本轮生成被 barge-in 中断, 不记录到历史")
            if self.history and self.history[-1].get("role") == "user":
                self.history.pop()
            return

        # 记录助手回复
        self.history.append({"role": "assistant", "content": full_reply})
        logger.info(f"💬 元亨: {full_reply}")

        # 等待 play_start (最多 3 秒, 仅用于延迟统计; 不阻塞太久, 尽快释放 _processing 锁)
        for _ in range(60):
            if "play_start" in self.tracker.marks:
                break
            await asyncio.sleep(0.05)

        logger.info(self.tracker.report())

    # ── 文本模式 (跳过 ASR) ──
    def run_text_mode(self, text: str):
        logger.info(f"文本输入模式: {text}")
        self.tracker.reset()
        # 文本模式: 发送时刻即"开口"也即"说完", 用同一时间点占位
        self.tracker.mark("vad_start")
        self.tracker.mark("vad_end")
        self.tracker.mark("asr_start")
        self.tracker.mark("asr_done")
        self.player = Player(recorder=None, tracker=self.tracker)
        self.player.start()
        try:
            asyncio.run(self._generate_and_speak(text))
            # 等待播放队列消费完
            self.player._queue.join()
        finally:
            self.player.stop()

    # ── 语音连续对话模式 ──
    def run_voice_mode(self):
        self.recorder = Recorder(self.vad, tracker=self.tracker, player=None)
        self.player = Player(self.recorder, tracker=self.tracker)
        # 插话方案A: 播放完成回调 → 处理排队插话
        self.player.on_play_done = self._on_play_done
        # 双向绑定: Recorder 引用 Player (音量上报用)
        self.recorder.player = self.player
        self.player.start()
        self.recorder.start(on_speech_end=self._on_speech_end)

        print("\n" + "=" * 60)
        print("  语音对话已启动, 请说话 (连续对话模式)")
        print("  按 Ctrl+C 退出")
        print("=" * 60 + "\n")

        try:
            while not self._should_stop:
                # 主循环: 检测 VAD 静音超时 (一句话说完)
                if self.recorder:
                    self.recorder.check_silence_timeout()
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("\n收到退出信号...")
        finally:
            self._should_stop = True
            if self.recorder:
                self.recorder.stop()
            if self.player:
                self.player.stop()
            # 卸载引擎
            try:
                self.asr.unload()
                self.tts.unload()
                self.vad.unload()
            except Exception:
                pass
            print("已退出, 再见!")


# ============================================================
# 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="YHLZ 2.0 语音对话 Demo (独立可跑通)"
    )
    parser.add_argument(
        "--engine",
        choices=["qwen3-tts-customvoice", "qwen3-tts"],
        default=None,
        help=f"TTS 引擎 (默认 {DEFAULT_TTS_ENGINE})",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="文本输入模式: 跳过 ASR, 直接用此文本对话 (用于快速验证 LLM+TTS)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="单轮对话后退出 (仅 --text 模式生效)",
    )
    args = parser.parse_args()

    demo = VoiceChatDemo(args)
    demo.load_engines()

    if args.text:
        demo.run_text_mode(args.text)
    else:
        demo.run_voice_mode()


if __name__ == "__main__":
    main()
