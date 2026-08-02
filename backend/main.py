"""
YHLZ 2.0 后端主入口
云端大脑(DeepSeek) + 本地TTS(Qwen3-TTS 0.6B) + 本地ASR(SenseVoiceSmall)
"""

import logging
import sys
from pathlib import Path

# 添加项目路径
root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(root_path / "backend.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, Optional, AsyncGenerator, Dict, Any
import numpy as np
import asyncio
import json
from contextlib import asynccontextmanager

# 导入配置
from backend.config import config

# 导入ASR引擎（SenseVoiceSmall，GPU加速）
from backend.asr_engine import asr_engine
logger.info(f"使用 {config.asr_model} 引擎 (GPU: {config.asr_device})")

# 导入TTS引擎
from backend.tts_engine import tts_engine
logger.info(f"使用 {config.tts_engine} 引擎")

# 导入情绪分类器（蓝图1.4: 情绪→音色映射）
from backend.emotion_classifier import classify_emotion, resolve_voice_for_emotion, get_emotion_voice

# 导入其他模块
from backend.llm_engine import llm_engine
from backend.vad_engine import vad_engine
from backend.audio_buffer import audio_buffer
from backend.context_manager import context_manager
from backend.conversation_manager import conversation_manager
from backend.sync_manager import sync_manager
import time

# 导入音频输出模块
try:
    import sounddevice as sd
    logger.info("sounddevice音频输出模块已加载")
except ImportError:
    logger.warning("未安装sounddevice，音频输出功能不可用")
    sd = None

# 音频播放线程相关
_audio_player_thread = None
_audio_player_running = False

def _start_audio_player():
    """启动音频播放线程"""
    global _audio_player_thread, _audio_player_running
    if _audio_player_running:
        return
    _audio_player_running = True
    import threading
    _audio_player_thread = threading.Thread(target=_audio_player_loop, daemon=True)
    _audio_player_thread.start()
    logger.info("音频播放线程已启动")

def _stop_audio_player():
    """停止音频播放线程"""
    global _audio_player_running
    _audio_player_running = False
    logger.info("音频播放线程已停止")

def _audio_player_loop():
    """音频播放循环（集成口型同步）
    蓝图1.2: 首段0.5s就绪即开口, 累计满2秒再合并后续
    蓝图1.3: 消费 done 哨兵后才复位口型; 被打断的流不产生 done
    """
    global _audio_player_running
    import time
    import numpy as np
    
    if sd is None:
        logger.error("sounddevice未加载，音频播放线程退出")
        return
    
    logger.info("音频播放线程开始运行（集成口型同步）")
    
    target_chunk_size = audio_buffer.sample_rate * 2  # 2秒保底缓冲（仅fallback模式）
    min_play_size = max(int(audio_buffer.sample_rate * config.tts_first_chunk_min_ms / 1000.0), audio_buffer.sample_rate // 4)
    first_segment = True
    use_fallback = config.tts_fallback_buffer_enabled  # 蓝图D4: Demo阶段默认关闭
    
    mouth_sync_chunk_size = audio_buffer.sample_rate // 10
    
    while _audio_player_running:
        try:
            accumulated_audio = []
            accumulated_length = 0
            
            while accumulated_length < target_chunk_size:
                audio_data = audio_buffer.get_next_audio()
                if audio_data is not None and len(audio_data) > 0:
                    accumulated_audio.append(audio_data)
                    accumulated_length += len(audio_data)
                    logger.debug(f"累积音频块: {len(audio_data)} samples, 总长度: {accumulated_length}")
                else:
                    # 蓝图D4: 渐进播放 — 首段达到min_play_size即开口
                    if accumulated_length >= min_play_size:
                        break
                    # 正常流结束: 消费 done 哨兵后收尾
                    if audio_buffer.is_stream_done:
                        break
                    time.sleep(0.005)
            
            if accumulated_audio:
                combined_audio = np.concatenate(accumulated_audio)
                logger.info(f"播放合并音频块: {len(combined_audio)} samples, {audio_buffer.sample_rate} Hz")
                
                # 记录自播窗口 (蓝图1.5 回声过滤)
                audio_buffer.record_play_window(len(combined_audio) / audio_buffer.sample_rate)
                
                try:
                    sd.play(combined_audio, audio_buffer.sample_rate)
                    
                    num_chunks = len(combined_audio) // mouth_sync_chunk_size
                    for i in range(num_chunks):
                        start = i * mouth_sync_chunk_size
                        end = start + mouth_sync_chunk_size
                        chunk = combined_audio[start:end]
                        mouth_open = audio_buffer.calculate_mouth_open(chunk)
                        
                        sync_manager.record_event('mouth_sync', {
                            'value': mouth_open,
                            'timestamp': time.time()
                        })
                        
                        time.sleep(mouth_sync_chunk_size / audio_buffer.sample_rate)
                    
                    remaining = len(combined_audio) % mouth_sync_chunk_size
                    if remaining > 0:
                        chunk = combined_audio[-remaining:]
                        mouth_open = audio_buffer.calculate_mouth_open(chunk)
                        sync_manager.record_event('mouth_sync', {
                            'value': mouth_open,
                            'timestamp': time.time()
                        })
                        
                    sd.wait()
                    
                except Exception as play_e:
                    logger.error(f"sounddevice播放错误: {play_e}")
                    time.sleep(0.05)
                
                # 蓝图1.3: 只有正常结束(done哨兵)才复位口型; 流未结束保持张合
                if audio_buffer.is_stream_done:
                    audio_buffer.reset_mouth_open()
                    sync_manager.record_event('mouth_sync', {
                        'value': 0.0,
                        'timestamp': time.time()
                    })
                    audio_buffer.reset_stream_done()
                    first_segment = True
                else:
                    first_segment = False
                
                accumulated_audio = []
                accumulated_length = 0
                logger.info(f"音频播放完成")
            else:
                # 无音频: 仅在流结束时复位口型
                if audio_buffer.is_stream_done:
                    audio_buffer.reset_mouth_open()
                    sync_manager.record_event('mouth_sync', {
                        'value': 0.0,
                        'timestamp': time.time()
                    })
                    audio_buffer.reset_stream_done()
                    first_segment = True
                time.sleep(0.005)
            
        except Exception as e:
            logger.error(f"音频播放线程错误: {e}")
            audio_buffer.reset_mouth_open()
            accumulated_audio = []
            accumulated_length = 0
            time.sleep(0.1)
    
    logger.info("音频播放线程已退出")

# Lifespan事件处理器（必须在app创建之前定义）
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan事件处理器（替代旧的@app.on_event）"""
    # 启动事件
    logger.info("=" * 60)
    logger.info("YHLZ 2.0 后端启动中...")
    logger.info("DeepSeek LLM + Qwen3-TTS 0.6B + SenseVoiceSmall ASR")
    logger.info("=" * 60)

    # 打印配置信息
    logger.info(f"配置信息:")
    
    # LLM信息
    if config.api_provider == "dashscope":
        logger.info(f"  LLM: {config.dashscope_model} (阿里云通义千问 API)")
    else:
        logger.info(f"  LLM: {config.deepseek_model} (DeepSeek API)")
    
    # ASR信息
    logger.info(f"  ASR: {config.asr_model} (GPU: {config.asr_device}, FP16: {config.use_fp16})")
    
    # TTS信息
    logger.info(f"  TTS: Qwen3-TTS 0.6B CustomVoice (本地)")
    
    # 上下文限制
    logger.info(f"  上下文限制: {config.max_context_tokens} tokens")
    
    logger.info("=" * 60)

    # ASR模型按需加载（模块管理模式）
    logger.info("ASR模型将按需加载（模块管理模式）")
    logger.info("模块管理模式已启用，可通过 /modules/status, /modules/start, /modules/stop 管理模块")

    # 播放欢迎语音（延迟到后台执行，避免阻塞启动）
    welcome_text = "llm初始化成功,tts初始化成功,这里是元亨,信息于你无限,科技开拓未来"
    logger.info(f"欢迎语音准备就绪: {welcome_text}")

    # 初始化连续对话管理器
    conversation_manager.set_engines(
        asr_engine=asr_engine,
        llm_engine=llm_engine,
        tts_engine=tts_engine,
        vad_engine=vad_engine,
        audio_buffer=audio_buffer
    )
    await conversation_manager.start_conversation()
    logger.info("连续对话管理器初始化完成")

    # 启动音频播放线程
    if sd:
        _start_audio_player()
        logger.info("音频播放线程已启动")
    else:
        logger.warning("音频输出不可用，跳过音频播放线程")
    
    # 启动多模态同步管理器
    sync_manager.start()
    logger.info("多模态同步管理器已启动")

    # 蓝图D5: 应急重置热键 (Ctrl+Shift+R → 清空对话历史)
    _hotkey_thread = None
    try:
        import threading as _th
        def _hotkey_listener():
            try:
                from pynput import keyboard
                def _on_hotkey():
                    context_manager.clear_history()
                    audio_buffer.clear_buffer()
                    logger.info("<<< 应急重置: 对话历史已清空 (Ctrl+Shift+R) >>>")
                _current_keys = set()
                def _on_press(key):
                    try:
                        if hasattr(key, 'char'):
                            _current_keys.add(key.char.lower() if key.char else str(key))
                    except:
                        _current_keys.add(str(key))
                    if keyboard.Key.ctrl in _current_keys or keyboard.Key.ctrl_l in _current_keys or keyboard.Key.ctrl_r in _current_keys:
                        if keyboard.Key.shift in _current_keys or keyboard.Key.shift_l in _current_keys or keyboard.Key.shift_r in _current_keys:
                            if 'r' in _current_keys:
                                _on_hotkey()
                def _on_release(key):
                    try:
                        _current_keys.discard(key.char.lower() if key.char else str(key))
                    except:
                        _current_keys.discard(str(key))
                with keyboard.Listener(on_press=_on_press, on_release=_on_release) as listener:
                    listener.join()
            except ImportError:
                logger.info("pynput 未安装，跳过全局热键注册（可通过 /clear-history API 手动重置）")
            except Exception as e:
                logger.warning(f"热键监听启动失败: {e}")
        _hotkey_thread = _th.Thread(target=_hotkey_listener, daemon=True)
        _hotkey_thread.start()
        logger.info("应急重置热键已注册: Ctrl+Shift+R → 清空对话历史")
    except Exception as e:
        logger.warning(f"热键注册失败: {e}")

    yield  # 应用运行中

    # 关闭事件
    logger.info("YHLZ 2.0 后端关闭中...")
    
    # 停止音频播放线程
    _stop_audio_player()
    
    # 停止多模态同步管理器
    sync_manager.stop()
    logger.info("多模态同步管理器已停止")

    # 卸载模型
    asr_engine.unload()
    tts_engine.unload()
    vad_engine.unload()

    logger.info("YHLZ 2.0 后端已关闭")


app = FastAPI(
    title="YHLZ 2.0 智能语音助手",
    version="2.0",
    description="云端大脑 + 本地轻量感官 - 完整语音对话系统",
    swagger_ui_parameters={"defaultModelsExpandDepth": -1, "syntaxHighlight.theme": "monokai", "tryItOutEnabled": True},
    redoc_url="/redoc",
    docs_url="/docs",
    lifespan=lifespan  # 使用lifespan替代on_event
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompressedWebSocket:
    """压缩WebSocket - 支持permessage-deflate压缩"""
    
    def __init__(self, websocket: WebSocket, compress_threshold: int = 512):
        """
        初始化压缩WebSocket
        
        Args:
            websocket: 原始WebSocket
            compress_threshold: 压缩阈值（小于此大小的数据不压缩）
        """
        self.ws = websocket
        self.compress_threshold = compress_threshold
        self._compression_enabled = True
        
        # 压缩统计
        self.bytes_sent = 0
        self.bytes_compressed = 0
        self.messages_sent = 0
    
    async def send_text(self, data: str):
        """发送文本（自动压缩）"""
        try:
            # JSON编码
            encoded = data.encode('utf-8')
            self.bytes_sent += len(encoded)
            
            # 大数据自动压缩
            if self._compression_enabled and len(encoded) > self.compress_threshold:
                try:
                    import zlib
                    compressed = zlib.compress(encoded, level=6)
                    # 添加压缩标记
                    await self.ws.send_bytes(b'\x00' + compressed)
                    self.bytes_compressed += len(compressed)
                except Exception:
                    # 压缩失败，发送原始数据
                    await self.ws.send_text(data)
            else:
                await self.ws.send_text(data)
            
            self.messages_sent += 1
            
        except Exception as e:
            logger.error(f"WebSocket发送失败: {e}")
            raise
    
    async def send_bytes(self, data: bytes):
        """发送字节数据"""
        try:
            await self.ws.send_bytes(data)
            self.bytes_sent += len(data)
            self.messages_sent += 1
        except Exception as e:
            logger.error(f"WebSocket发送失败: {e}")
            raise
    
    async def receive_text(self) -> str:
        """接收文本"""
        try:
            message = await self.ws.receive()
            
            if message.type == WebSocket.TextMessage:
                return message.text
            elif message.type == WebSocket.BinaryMessage:
                # 检查是否压缩数据
                if message.bytes and len(message.bytes) > 0 and message.bytes[0] == 0x00:
                    # 解压缩
                    import zlib
                    compressed = message.bytes[1:]
                    return zlib.decompress(compressed).decode('utf-8')
                else:
                    return message.bytes.decode('utf-8')
            else:
                return ""
                
        except Exception as e:
            logger.error(f"WebSocket接收失败: {e}")
            return ""
    
    async def accept(self, subprotocol: str = None):
        """接受连接"""
        await self.ws.accept(subprotocol=subprotocol)
    
    async def close(self, code: int = 1000, reason: str = ""):
        """关闭连接"""
        await self.ws.close(code=code, reason=reason)
    
    def enable_compression(self):
        """启用压缩"""
        self._compression_enabled = True
    
    def disable_compression(self):
        """禁用压缩"""
        self._compression_enabled = False
    
    def get_stats(self) -> dict:
        """获取压缩统计"""
        if self.bytes_sent > 0:
            ratio = (1 - self.bytes_compressed / self.bytes_sent) * 100
            return {
                "messages_sent": self.messages_sent,
                "bytes_sent": self.bytes_sent,
                "bytes_compressed": self.bytes_compressed,
                "compression_ratio": f"{ratio:.1f}%"
            }
        else:
            return {
                "messages_sent": 0,
                "bytes_sent": 0,
                "bytes_compressed": 0,
                "compression_ratio": "0%"
            }


# WebSocket连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[CompressedWebSocket] = []
        self._compression_enabled = True
        self._compress_threshold = 512
    
    async def connect(self, websocket: WebSocket):
        """连接WebSocket"""
        compressed_ws = CompressedWebSocket(websocket, self._compress_threshold)
        if self._compression_enabled:
            compressed_ws.enable_compression()
        else:
            compressed_ws.disable_compression()
        
        await compressed_ws.accept()
        self.active_connections.append(compressed_ws)
        logger.info("WebSocket连接已建立（压缩已启用）")
    
    def disconnect(self, websocket: CompressedWebSocket):
        """断开连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            stats = websocket.get_stats()
            logger.info(f"WebSocket连接已断开 | 统计: {stats}")
    
    def get_stats(self) -> dict:
        """获取所有连接统计"""
        total_sent = 0
        total_compressed = 0
        total_messages = 0
        
        for ws in self.active_connections:
            stats = ws.get_stats()
            total_sent += stats["bytes_sent"]
            total_compressed += stats["bytes_compressed"]
            total_messages += stats["messages_sent"]
        
        return {
            "active_connections": len(self.active_connections),
            "total_messages": total_messages,
            "total_bytes_sent": total_sent,
            "total_bytes_compressed": total_compressed,
            "compression_ratio": f"{(1 - total_compressed / max(total_sent, 1)) * 100:.1f}%"
        }


manager = ConnectionManager()

# Pydantic模型
class ChatRequest(BaseModel):
    text: str
    temperature: float = 0.7
    max_tokens: int = 2048
    tts_enabled: bool = False
    voice: str = "Vivian"  # 默认使用 Vivian（明亮的年轻女声）
    rate: str = "0%"

class AudioRequest(BaseModel):
    audio_data: List[float]
    sample_rate: int = 16000

class SynthesisRequest(BaseModel):
    text: str
    voice: str = "Vivian"  # 默认使用 Vivian（明亮的年轻女声）
    emotion: Optional[str] = None  # 蓝图1.4: 显式情绪(happy/calm/sad/angry/neutral) → 映射音色

class ConfigUpdate(BaseModel):
    llm_model: Optional[str] = None
    api_key: Optional[str] = None

# VAD配置更新模型
class VADConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interrupt_enabled: Optional[bool] = None
    energy_threshold: Optional[float] = None
    silero_threshold: Optional[float] = None
    frame_size: Optional[int] = None
    min_speech_frames: Optional[int] = None

# VAD检测请求
class VADDetectionRequest(BaseModel):
    audio_data: List[float]
    sample_rate: int = 16000

# 健康检查
@app.get("/health", summary="健康检查", description="检查所有服务模块是否正常运行")
async def health_check():
    # 获取当前使用的模型名称
    if config.api_provider == "dashscope":
        model_name = config.dashscope_model
        provider_name = "阿里云通义千问"
    else:
        model_name = config.deepseek_model
        provider_name = "DeepSeek"
    
    # 获取ASR模型信息
    asr_model_info = config.asr_model
    
    # 获取TTS模型信息
    tts_model_info = "Qwen3-TTS-0.6B-CustomVoice"
    
    # ASR状态
    asr_status = asr_engine.is_loaded
    
    return {
        "status": "healthy",
        "llm": llm_engine.is_connected,
        "asr": asr_status,
        "tts": tts_engine.is_loaded,
        "vad": vad_engine.is_loaded,
        "provider": provider_name,
        "model": model_name,
        "asr_model": asr_model_info,
        "tts_model": tts_model_info,
        "fp16_enabled": config.use_fp16,
        "kv_cache_enabled": config.use_kv_cache,
        "websocket_stats": manager.get_stats()
    }

# WebSocket统计
@app.get("/websocket-stats", summary="WebSocket统计", description="查看WebSocket连接和压缩统计")
async def get_websocket_stats():
    return manager.get_stats()

# 缓存统计
@app.get("/cache-stats", summary="缓存统计", description="查看当前系统的缓存和状态信息")
async def get_cache_stats():
    return {
        "llm": {
            "connected": llm_engine.is_connected,
            "model": config.deepseek_model
        },
        "context": {
            "token_count": context_manager.get_token_count(),
            "near_limit": context_manager.is_near_limit(),
            "history_count": len(context_manager.history)
        },
        "audio_buffer": {
            "has_pending": audio_buffer.has_pending_audio(),
            "is_interrupted": audio_buffer.is_interrupted
        }
    }

# 文本聊天
@app.post("/chat", summary="文本对话", description="使用 SSE 协议进行流式文本对话")
async def chat(request: ChatRequest):
    try:
        logger.info(f"收到聊天请求: {request.text[:50]}...")
        
        # 添加用户消息到上下文
        context_manager.add_message("user", request.text)
        
        # 获取上下文
        messages = context_manager.get_context()
        
        # 打印发送给LLM的消息，用于调试
        logger.info(f"发送给LLM的消息数: {len(messages)}")
        for i, msg in enumerate(messages):
            logger.info(f"  [{i}] {msg['role']}: {msg['content'][:80]}...")
        
        # 流式生成响应
        full_response = ""
        
        async def generate():
            nonlocal full_response
            
            import asyncio
            text_queue = asyncio.Queue()
            tts_task = None
            
            async def tts_producer():
                tts_accumulated_text = ""
                while True:
                    try:
                        chunk = await asyncio.wait_for(text_queue.get(), timeout=5.0)
                        if chunk is None:
                            break
                        tts_accumulated_text += chunk
                        # 流式断句：标点优先（句号/问号/感叹号/分号断句，逗号也断），50字安全上限
                        should_cut = (
                            tts_accumulated_text[-1] in "。！？；!?;…"
                            or (tts_accumulated_text[-1] in "，、," and len(tts_accumulated_text) >= 8)
                            or len(tts_accumulated_text) >= 50
                        )
                        if should_cut:
                            logger.info(f"TTS合成文本: '{tts_accumulated_text}'")
                            # 蓝图1.4: 情绪→音色映射
                            tts_voice = resolve_voice_for_emotion(
                                tts_accumulated_text,
                                base_voice=request.voice,
                                enabled=config.emotion_enabled,
                                confidence_threshold=config.emotion_confidence_threshold
                            )
                            async for audio_chunk, sr in tts_engine.stream_synthesize_text(tts_accumulated_text, voice=tts_voice):
                                if audio_chunk is not None and len(audio_chunk) > 0:
                                    logger.info(f"添加音频到缓冲: {len(audio_chunk)} samples, {sr} Hz")
                                    audio_buffer.add_audio(audio_chunk, sr)
                            tts_accumulated_text = ""
                        text_queue.task_done()
                    except asyncio.TimeoutError:
                        break
                    except Exception as e:
                        logger.error(f"TTS生产者任务错误: {e}")
                        break
                
                if tts_accumulated_text:
                    tts_voice = resolve_voice_for_emotion(
                        tts_accumulated_text,
                        base_voice=request.voice,
                        enabled=config.emotion_enabled,
                        confidence_threshold=config.emotion_confidence_threshold
                    )
                    async for audio_chunk, sr in tts_engine.stream_synthesize_text(tts_accumulated_text, voice=tts_voice):
                        audio_buffer.add_audio(audio_chunk, sr)
                
                # 蓝图1.3: 正常结束标记 done 哨兵 (被打断的流由interrupt清掉)
                audio_buffer.mark_stream_done()
            
            if request.tts_enabled:
                tts_task = asyncio.create_task(tts_producer())
            
            async for chunk in llm_engine.generate_stream(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                
                if request.tts_enabled:
                    await text_queue.put(chunk)
            
            if request.tts_enabled and tts_task:
                await text_queue.put(None)
                await tts_task
            
            context_manager.add_message("assistant", full_response)
            
            yield f"data: {json.dumps({'is_done': True, 'full_content': full_response}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"聊天请求失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 语音识别
@app.post("/transcribe", summary="语音识别", description="将音频数据转换为文本")
async def transcribe(request: AudioRequest):
    try:
        audio_np = np.array(request.audio_data, dtype=np.float32)
        text = asr_engine.transcribe(audio_np, request.sample_rate)
        return {"text": text, "success": True}
    except Exception as e:
        logger.error(f"语音识别失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 语音合成
@app.post("/synthesize", summary="语音合成", description="将文本转换为语音音频")
async def synthesize(request: SynthesisRequest):
    try:
        # 蓝图1.4: 情绪→音色映射 (显式emotion优先, 否则自动分类)
        voice = request.voice
        if config.emotion_enabled:
            if request.emotion:
                voice = get_emotion_voice(request.emotion, voice)
            else:
                voice = resolve_voice_for_emotion(
                    request.text,
                    base_voice=voice,
                    enabled=True,
                    confidence_threshold=config.emotion_confidence_threshold
                )
        
        # 使用指定的声音进行合成
        audio, sample_rate = tts_engine.synthesize(request.text, voice=voice)
        
        # 添加到音频缓冲
        audio_buffer.add_audio(audio, sample_rate)
        audio_buffer.mark_stream_done()
        
        # 返回音频数据
        return {
            "audio": audio.tolist(),
            "sample_rate": sample_rate,
            "success": True,
            "voice": voice
        }
    except Exception as e:
        logger.error(f"语音合成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 流式语音合成
@app.post("/synthesize/stream", summary="流式语音合成", description="流式将文本转换为语音音频")
async def synthesize_stream(request: SynthesisRequest):
    try:
        logger.info(f"开始流式语音合成: {request.text[:30]}... | 声音: {request.voice}")
        
        # 蓝图1.4: 情绪→音色映射
        stream_voice = request.voice
        if config.emotion_enabled:
            if request.emotion:
                stream_voice = get_emotion_voice(request.emotion, stream_voice)
            else:
                stream_voice = resolve_voice_for_emotion(
                    request.text,
                    base_voice=stream_voice,
                    enabled=True,
                    confidence_threshold=config.emotion_confidence_threshold
                )
        
        async def audio_stream():
            async for audio_chunk, sample_rate in tts_engine.stream_synthesize_text(request.text, stream_voice):
                if audio_chunk is not None:
                    yield json.dumps({
                        "audio": audio_chunk.tolist(),
                        "sample_rate": sample_rate,
                        "is_done": False
                    }) + "\n"
            
            yield json.dumps({
                "is_done": True,
                "sample_rate": 24000
            }) + "\n"
        
        return StreamingResponse(audio_stream(), media_type="application/json")
    
    except Exception as e:
        logger.error(f"流式语音合成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 打断音频播放
@app.post("/interrupt", summary="打断播放", description="立即停止当前的音频播放")
async def interrupt():
    audio_buffer.interrupt()
    return {"success": True, "message": "Audio interrupted"}

# 清空历史
@app.post("/clear-history", summary="清空历史", description="清空对话历史和音频缓存")
async def clear_history():
    context_manager.clear_history()
    audio_buffer.clear_buffer()
    return {"success": True}

# ==================== 性格设定API ====================

class PersonalityUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    occupation: Optional[str] = None
    description: Optional[str] = None
    personality_traits: Optional[List[str]] = None
    speaking_style: Optional[str] = None
    tone: Optional[str] = None
    catchphrases: Optional[List[str]] = None

@app.get("/personality", summary="获取性格配置", description="获取当前AI的性格设定")
async def get_personality():
    config = context_manager.get_personality_config()
    return config.dict()

@app.post("/personality", summary="更新性格配置", description="更新AI的性格设定")
async def update_personality(update: PersonalityUpdate):
    update_dict = update.dict(exclude_none=True)
    if update_dict:
        context_manager.update_personality(**update_dict)
        return {"success": True, "message": "性格配置已更新"}
    return {"success": False, "message": "没有提供任何更新"}

@app.post("/personality/reset", summary="重置性格配置", description="将性格配置重置为默认值")
async def reset_personality():
    context_manager.reset_personality()
    return {"success": True, "message": "性格配置已重置"}

# ==================== VAD相关API ====================

@app.get("/vad/config", summary="获取VAD配置", description="获取当前VAD（语音活动检测）的配置")
async def get_vad_config():
    return {"success": True, "config": vad_engine.get_config()}

@app.post("/vad/config", summary="更新VAD配置", description="更新VAD配置参数")
async def update_vad_config(update: VADConfigUpdate):
    config_dict = update.dict(exclude_none=True)
    if config_dict:
        vad_engine.set_config(config_dict)
        return {"success": True, "message": "VAD配置已更新"}
    return {"success": False, "message": "没有提供任何更新"}

@app.post("/vad/detect", summary="检测语音活动", description="检测音频中是否有语音活动")
async def detect_speech(request: VADDetectionRequest):
    try:
        audio_np = np.array(request.audio_data, dtype=np.float32)
        has_speech = vad_engine.detect_speech(audio_np, request.sample_rate)
        return {
            "success": True,
            "has_speech": has_speech,
            "vad_enabled": vad_engine.enabled,
            "interrupt_enabled": vad_engine.interrupt_enabled
        }
    except Exception as e:
        logger.error(f"VAD检测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/vad/interrupt", summary="触发VAD中断", description="通过VAD检测触发TTS播放中断")
async def trigger_interrupt(request: VADDetectionRequest):
    try:
        if not vad_engine.enabled or not vad_engine.interrupt_enabled:
            return {"success": False, "message": "VAD中断功能未启用"}
        
        audio_np = np.array(request.audio_data, dtype=np.float32)
        has_speech = vad_engine.detect_speech(audio_np, request.sample_rate)
        
        if has_speech:
            # 触发中断
            audio_buffer.set_interrupted(True)
            logger.info("VAD检测到语音，已触发TTS中断")
            return {
                "success": True,
                "has_speech": True,
                "interrupted": True,
                "message": "检测到语音，已触发中断"
            }
        else:
            return {
                "success": True,
                "has_speech": False,
                "interrupted": False,
                "message": "未检测到语音"
            }
    except Exception as e:
        logger.error(f"VAD中断检测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 流式对话API ====================

# ==================== 蓝图D6: 桌宠同步 WebSocket ====================

@app.websocket("/ws/avatar", name="桌宠同步")
async def websocket_avatar_endpoint(websocket: WebSocket):
    """桌宠→backend 最小 WS 契约: 口型/表情/心跳/重连"""
    await websocket.accept()
    sync_manager.register_ws_client(websocket)
    logger.info("桌宠已连接 /ws/avatar")
    
    # 发送连接确认
    await websocket.send_text(json.dumps({
        "type": "connected",
        "data": {"version": "1.0", "backend": "YHLZ2.0"},
        "ts": time.time()
    }))
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=12.0)
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "ts": time.time()
                    }))
                elif msg_type == "status":
                    # 桌宠上报状态
                    logger.debug(f"桌宠状态: {msg.get('data', {})}")
            except asyncio.TimeoutError:
                # 心跳超时检查
                try:
                    await websocket.send_text(json.dumps({
                        "type": "ping",
                        "ts": time.time()
                    }))
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("桌宠已断开 /ws/avatar")
    except Exception as e:
        logger.warning(f"桌宠 WS 异常: {e}")
    finally:
        sync_manager.unregister_ws_client(websocket)

# 流式对话端点 - 支持ASR同步识别 + LLM流式输出 + TTS同步合成（低延迟优化）
@app.websocket("/ws/stream", name="流式语音对话")
async def websocket_stream_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    # 流式ASR相关 - 更低延迟
    asr_buffer = np.array([], dtype=np.float32)
    asr_chunk_size = 3200  # 约0.2秒（更低延迟）
    asr_accumulated_text = ""
    asr_streaming = False
    
    # TTS播放状态
    is_playing = False
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "audio_chunk":
                asr_streaming = True
                audio_chunk = np.array(message.get("audio", []), dtype=np.float32)
                sample_rate = message.get("sample_rate", 16000)
                
                asr_buffer = np.concatenate([asr_buffer, audio_chunk])
                
                # 更低延迟：每积累约0.2秒进行一次识别
                if len(asr_buffer) >= asr_chunk_size:
                    audio_to_process = asr_buffer[:asr_chunk_size].copy()
                    asr_buffer = asr_buffer[int(asr_chunk_size * 2/3):]
                    
                    loop = asyncio.get_event_loop()
                    text = await loop.run_in_executor(
                        None,
                        asr_engine.transcribe,
                        audio_to_process,
                        sample_rate
                    )
                    
                    if text and text.strip():
                        if text.strip().startswith(asr_accumulated_text):
                            new_text = text.strip()[len(asr_accumulated_text):]
                            if new_text:
                                asr_accumulated_text = text.strip()
                                await websocket.send_text(json.dumps({
                                    "type": "asr_result",
                                    "text": new_text,
                                    "full_text": asr_accumulated_text
                                }))
                        else:
                            asr_accumulated_text = text.strip()
                            await websocket.send_text(json.dumps({
                                "type": "asr_result",
                                "text": asr_accumulated_text,
                                "full_text": asr_accumulated_text
                            }))
                
            elif message.get("type") == "audio_end":
                asr_streaming = False
                asr_accumulated_text = ""
                await websocket.send_text(json.dumps({
                    "type": "asr_done"
                }))
                
            elif message.get("type") == "chat_stream":
                text = message.get("text", "")
                
                if not text.strip():
                    continue
                
                # 蓝图D5: ASR自然词应急重置 ("清空/重置/重新开始" → 清空对话历史)
                reset_keywords = ["清空", "重置", "重新开始", "清除对话", "清除历史"]
                if any(kw in text for kw in reset_keywords):
                    context_manager.clear_history()
                    audio_buffer.clear_buffer()
                    await websocket.send_text(json.dumps({
                        "type": "system",
                        "text": "对话历史已清空，可以重新开始对话。"
                    }))
                    logger.info("<<< ASR自然词应急重置: 对话历史已清空 >>>")
                    continue
                
                context_manager.add_message("user", text)
                messages = context_manager.get_context()
                
                full_response = ""
                tts_queue = asyncio.Queue()
                tts_done = asyncio.Event()
                
                async def tts_worker():
                    accumulated_text = ""
                    while True:
                        try:
                            chunk = await asyncio.wait_for(tts_queue.get(), timeout=0.5)
                            if chunk is None:
                                break
                            accumulated_text += chunk
                            # 蓝图D2: 统一切句规则 — 标点优先 / 12字触发 / 30字上限
                            should_cut = (
                                accumulated_text[-1] in "。！？；"
                                or len(accumulated_text) >= 12
                                or len(accumulated_text) >= 30
                            )
                            if should_cut:
                                async for audio_chunk, sr in tts_engine.stream_synthesize_text(accumulated_text):
                                    await websocket.send_text(json.dumps({
                                        "type": "audio_chunk",
                                        "audio": audio_chunk.tolist(),
                                        "sample_rate": sr
                                    }))
                                accumulated_text = ""
                        except asyncio.TimeoutError:
                            if accumulated_text:
                                async for audio_chunk, sr in tts_engine.stream_synthesize_text(accumulated_text):
                                    await websocket.send_text(json.dumps({
                                        "type": "audio_chunk",
                                        "audio": audio_chunk.tolist(),
                                        "sample_rate": sr
                                    }))
                                accumulated_text = ""
                
                tts_task = asyncio.create_task(tts_worker())
                
                async for chunk in llm_engine.generate_stream(messages, flush_threshold=1):
                    full_response += chunk
                    
                    await websocket.send_text(json.dumps({
                        "type": "text_chunk",
                        "content": chunk
                    }))
                    
                    await tts_queue.put(chunk)
                
                await tts_queue.put(None)
                await tts_task
                
                context_manager.add_message("assistant", full_response)
                
                await websocket.send_text(json.dumps({
                    "type": "done",
                    "content": full_response
                }))
            
            elif message.get("type") == "interrupt":
                audio_buffer.interrupt()
                await websocket.send_text(json.dumps({
                    "type": "interrupted"
                }))
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"流式WebSocket错误: {e}")
        manager.disconnect(websocket)

# ==================== TTS引擎切换API ====================

class TTSEngineRequest(BaseModel):
    """TTS引擎切换请求模型"""
    engine: str
    voice: Optional[str] = None

@app.post("/tts/engine", summary="切换TTS引擎", description="切换使用的TTS引擎")
async def switch_tts_engine(request: TTSEngineRequest):
    """切换TTS引擎 (蓝图1.1: 通过TTSManager统一切换+回退)"""
    global tts_engine
    
    try:
        logger.info(f"切换TTS引擎: {request.engine}")
        
        from backend.tts_engine import tts_manager
        
        if tts_manager.activate(request.engine):
            tts_engine = tts_manager
            logger.info(f"已切换到TTS引擎: {request.engine}")
            return {"success": True, "message": f"已切换到TTS引擎: {request.engine}"}
        else:
            return {"success": False, "message": f"引擎切换失败或不可用: {request.engine}"}
            
    except Exception as e:
        logger.error(f"切换TTS引擎失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tts/engines", summary="获取可用TTS引擎", description="获取可用的TTS引擎列表")
async def get_available_tts_engines():
    """获取可用的TTS引擎列表 (蓝图1.1: 引擎注册表)"""
    from backend.tts_engine import tts_manager
    return {
        "success": True,
        "engines": tts_manager.get_available_engines(),
        "current_engine": tts_manager._active_name
    }


# ==================== Live2D API ====================

live2d_state = {
    "current_model": None,
    "current_emotion": "idle",
    "glow_color": "#4169E1",
    "mouth_open": 0.0,
    "available_models": [
        {
            "name": "Hiyori (本地)",
            "url": "http://localhost:18765/hiyori_vts/hiyori.model3.json"
        },
        {
            "name": "Hijiki",
            "url": "https://cdn.jsdelivr.net/npm/live2d-widget-model-hijiki@1.0.5/assets/hijiki.model3.json"
        },
        {
            "name": "Shizuku",
            "url": "https://cdn.jsdelivr.net/npm/live2d-widget-model-shizuku@1.0.5/assets/shizuku.model3.json"
        },
        {
            "name": "Miku",
            "url": "https://cdn.jsdelivr.net/npm/live2d-widget-model-miku@1.0.5/assets/miku.model3.json"
        }
    ]
}

class LoadModelRequest(BaseModel):
    model_url: str

class ActionRequest(BaseModel):
    action: str

class EmotionRequest(BaseModel):
    emotion: str

@app.get("/live2d", summary="Live2D页面", description="返回Live2D渲染页面")
async def get_live2d_page():
    import os
    html_path = os.path.join(os.path.dirname(__file__), "../assets/live2d/live2d_viewer.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, media_type="text/html")
    else:
        return {"error": "Live2D页面未找到"}

@app.post("/live2d/load", summary="加载模型", description="加载指定的Live2D模型")
async def load_live2d_model(request: LoadModelRequest):
    live2d_state["current_model"] = request.model_url
    return {
        "success": True,
        "message": f"模型已加载: {request.model_url}",
        "current_model": request.model_url
    }

@app.post("/live2d/action", summary="触发动作", description="触发Live2D模型动作")
async def trigger_live2d_action(request: ActionRequest):
    live2d_state["current_emotion"] = request.action
    return {
        "success": True,
        "message": f"动作已触发: {request.action}",
        "current_action": request.action
    }

@app.post("/live2d/emotion", summary="设置情绪", description="设置Live2D模型情绪")
async def set_live2d_emotion(request: EmotionRequest):
    emotion_map = {
        "开心": "happy",
        "悲伤": "sad",
        "愤怒": "angry",
        "平静": "neutral",
        "惊讶": "surprised",
        "害羞": "happy",
        "默认": "neutral",
        "焦虑": "anxious",
        "疲惫": "tired",
        "兴奋": "excited"
    }
    emotion = emotion_map.get(request.emotion, "neutral")
    live2d_state["current_emotion"] = emotion
    
    return {
        "success": True,
        "message": f"情绪已设置: {request.emotion}",
        "current_emotion": live2d_state["current_emotion"]
    }

@app.post("/live2d/emotion-intensity", summary="设置情绪强度", description="设置Live2D模型情绪并指定强度")
async def set_live2d_emotion_intensity(request: dict):
    emotion = request.get("emotion", "neutral")
    intensity = request.get("intensity", 1.0)
    
    emotion_map = {
        "开心": "happy",
        "悲伤": "sad",
        "愤怒": "angry",
        "平静": "neutral",
        "惊讶": "surprised",
        "害羞": "happy",
        "默认": "neutral",
        "焦虑": "anxious",
        "疲惫": "tired",
        "兴奋": "excited",
        "happy": "happy",
        "sad": "sad",
        "angry": "angry",
        "neutral": "neutral",
        "surprised": "surprised",
        "anxious": "anxious",
        "tired": "tired",
        "excited": "excited"
    }
    
    normalized_emotion = emotion_map.get(emotion, "neutral")
    live2d_state["current_emotion"] = normalized_emotion
    
    return {
        "success": True,
        "message": f"情绪已设置: {normalized_emotion} (强度: {intensity})",
        "current_emotion": normalized_emotion,
        "intensity": intensity
    }

@app.post("/live2d/mouth-open", summary="设置口型开合度", description="设置Live2D模型口型开合度(0-1)")
async def set_live2d_mouth_open(request: dict):
    value = request.get("value", 0.0)
    value = max(0.0, min(1.0, value))
    
    live2d_state["mouth_open"] = value
    
    audio_buffer.set_audio_energy_callback(lambda v: None)
    
    sync_manager.record_event('mouth_sync', {
        'value': value,
        'timestamp': time.time()
    })
    
    return {
        "success": True,
        "message": f"口型开合度已设置: {value}",
        "mouth_open": value
    }

@app.post("/live2d/glow-color", summary="设置光效颜色", description="设置Live2D模型背景光效颜色")
async def set_live2d_glow_color(request: dict):
    color = request.get("color", "#4169E1")
    
    live2d_state["glow_color"] = color
    
    return {
        "success": True,
        "message": f"光效颜色已设置: {color}",
        "glow_color": color
    }

@app.get("/live2d/models", summary="模型列表", description="获取可用的Live2D模型列表")
async def get_live2d_models():
    return {
        "models": live2d_state["available_models"]
    }

@app.get("/live2d/status", summary="状态查询", description="获取Live2D模型当前状态")
async def get_live2d_status():
    return {
        "success": True,
        "current_model": live2d_state.get("current_model", ""),
        "current_emotion": live2d_state.get("current_emotion", "neutral"),
        "glow_color": live2d_state.get("glow_color", "#4169E1"),
        "mouth_open": live2d_state.get("mouth_open", 0.0),
        "available_models": live2d_state.get("available_models", [])
    }

@app.get("/sync/status", summary="同步管理器状态", description="获取多模态同步管理器状态")
async def get_sync_status():
    return {
        "success": True,
        "status": sync_manager.get_status()
    }

@app.get("/sync/events", summary="同步事件列表", description="获取最近的同步事件")
async def get_sync_events(event_type: str = None, limit: int = 10):
    events = sync_manager.get_recent_events(event_type, limit)
    return {
        "success": True,
        "events": events,
        "count": len(events)
    }


class ModuleControlRequest(BaseModel):
    module_name: str


@app.get("/modules/status", summary="模块状态", description="获取所有服务模块的当前状态")
async def get_modules_status():
    modules = {
        "asr": {
            "name": "语音识别",
            "status": "running" if asr_engine.is_loaded else "stopped",
            "description": "离线语音转文字"
        },
        "tts": {
            "name": "语音合成",
            "status": "running" if tts_engine.is_loaded else "stopped",
            "description": "文字转语音"
        },
        "vad": {
            "name": "语音活动检测",
            "status": "running" if vad_engine.is_loaded else "stopped",
            "description": "实时语音打断检测"
        },
        "llm": {
            "name": "大语言模型",
            "status": "running" if llm_engine.is_connected else "stopped",
            "description": "AI对话引擎"
        }
    }
    
    return {"success": True, "modules": modules}


@app.post("/modules/start", summary="启动模块", description="启动指定的服务模块")
async def start_module(request: ModuleControlRequest):
    module_name = request.module_name.lower()
    
    try:
        if module_name == "asr":
            if asr_engine.is_loaded:
                return {"success": False, "message": "ASR引擎已加载"}
            # 在独立线程中加载模型，避免阻塞事件循环
            import concurrent.futures
            loop = asyncio.get_event_loop()
            load_success = await loop.run_in_executor(
                None, lambda: asr_engine.load_model(max_retries=3)
            )
            if load_success:
                return {"success": True, "message": "ASR引擎加载成功"}
            else:
                return {"success": False, "message": "ASR引擎加载失败"}
        
        elif module_name == "tts":
            if tts_engine.is_loaded:
                return {"success": False, "message": "TTS引擎已加载"}
            tts_engine.load()
            return {"success": True, "message": "TTS引擎加载成功"}
        
        elif module_name == "vad":
            if vad_engine.is_loaded:
                return {"success": False, "message": "VAD引擎已加载"}
            vad_engine._init_engine()
            return {"success": True, "message": "VAD引擎加载成功"}
        
        elif module_name == "llm":
            if llm_engine.is_connected:
                return {"success": False, "message": "LLM引擎已连接"}
            await llm_engine.connect()
            return {"success": True, "message": "LLM引擎连接成功"}
        
        else:
            return {"success": False, "message": f"未知模块: {module_name}"}
    
    except Exception as e:
        logger.error(f"启动模块 {module_name} 失败: {e}")
        return {"success": False, "message": f"启动模块失败: {e}"}


@app.post("/modules/stop", summary="停止模块", description="停止指定的服务模块，释放显存")
async def stop_module(request: ModuleControlRequest):
    module_name = request.module_name.lower()
    
    try:
        if module_name == "asr":
            if not asr_engine.is_loaded:
                return {"success": False, "message": "ASR引擎未加载"}
            asr_engine.unload()
            return {"success": True, "message": "ASR引擎已卸载，显存已释放"}
        
        elif module_name == "tts":
            if not tts_engine.is_loaded:
                return {"success": False, "message": "TTS引擎未加载"}
            tts_engine.unload()
            return {"success": True, "message": "TTS引擎已卸载"}
        
        elif module_name == "vad":
            if not vad_engine.is_loaded:
                return {"success": False, "message": "VAD引擎未加载"}
            vad_engine.is_loaded = False
            return {"success": True, "message": "VAD引擎已停止"}
        
        elif module_name == "llm":
            if not llm_engine.is_connected:
                return {"success": False, "message": "LLM引擎未连接"}
            llm_engine.disconnect()
            return {"success": True, "message": "LLM引擎已断开连接"}
        
        else:
            return {"success": False, "message": f"未知模块: {module_name}"}
    
    except Exception as e:
        logger.error(f"停止模块 {module_name} 失败: {e}")
        return {"success": False, "message": f"停止模块失败: {e}"}


# ==================== Memory API ====================

class MemoryAddRequest(BaseModel):
    content: str
    category: str = "general"
    importance: int = 1
    related_topics: List[str] = []
    emotion_tag: Optional[str] = None

@app.post("/memory")
async def add_memory(request: MemoryAddRequest):
    memory_id = context_manager.add_long_term_memory(
        content=request.content,
        category=request.category,
        importance=request.importance,
        related_topics=request.related_topics,
        emotion_tag=request.emotion_tag
    )
    return {"success": True, "memory_id": memory_id}

@app.get("/memory/search")
async def search_memory(query: str, limit: int = 5):
    memories = context_manager.get_relevant_memories(query, limit)
    return {"memories": [m.dict() if hasattr(m, 'dict') else m for m in memories]}

@app.get("/memory/list")
async def list_memories(limit: int = 100):
    memories = context_manager.get_long_term_memories(limit)
    return {"memories": [m.dict() if hasattr(m, 'dict') else m for m in memories]}

@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    return {"success": True, "deleted": memory_id}

@app.put("/memory/{memory_id}")
async def update_memory(memory_id: str, request: MemoryAddRequest):
    return {"success": True, "memory_id": memory_id}

# ==================== WebSocket 实时对话 ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """实时语音对话 WebSocket"""
    await websocket.accept()
    logger.info("WebSocket 实时语音对话连接已建立")
    try:
        # 使用 conversation_manager 处理实时对话
        await conversation_manager.handle_ws(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket 实时语音对话连接已断开")
    except Exception as e:
        logger.error(f"WebSocket 实时语音对话错误: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )