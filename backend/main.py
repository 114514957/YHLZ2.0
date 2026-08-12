"""
YHLZ 2.0 后端主入口
云端大脑(DeepSeek) + 本地TTS(Qwen3-TTS 0.6B) + 本地ASR(SenseVoiceSmall)
"""

import logging
import os
import sys
from pathlib import Path

# 统一 UTF-8 编码 (避免 Windows 下中文/emoji 乱码)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目路径
root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(root_path / "backend.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Request
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

# V10.1.7: 对话回合控制器 (Conversation Turn Controller, 懒加载)
_turn_controller = None

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
    welcome_text = "llm初始化成功,tts初始化成功,这里是元亨,信息于你无限,元亨重塑未来"
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

    # Vision Perception V1.0 - 注册感知工具 + 懒加载 Service
    try:
        from backend.vision.perception.tools import register_vision_tools
        n = register_vision_tools(override=True)
        logger.info(f"Vision Perception 工具已注册: {n} 个 (read_screen_text / detect_objects)")
    except Exception as e:
        logger.warning(f"Vision Perception 工具注册失败: {e}")

    # Vision Understanding V1.0 - 注册理解工具 + 懒加载 Service
    try:
        from backend.vision.understanding.tools import register_understanding_tools
        n = register_understanding_tools(override=True)
        logger.info(f"Vision Understanding 工具已注册: {n} 个 (describe_scene / answer_visual)")
    except Exception as e:
        logger.warning(f"Vision Understanding 工具注册失败: {e}")

    # Vision Memory V1.0 - 注册视觉记忆工具 + 懒加载 Service
    try:
        from backend.vision.memory.tools import register_vision_memory_tools
        n = register_vision_memory_tools(override=True)
        logger.info(f"Vision Memory 工具已注册: {n} 个 (search_visual_memory)")
    except Exception as e:
        logger.warning(f"Vision Memory 工具注册失败: {e}")

    # Personality Engine V3.4 - 注册人格工具 + 懒加载 Service
    try:
        from backend.personality.tools import register_personality_tools
        n = register_personality_tools(override=True)
        logger.info(f"Personality Engine 工具已注册: {n} 个 (get_personality_style)")
    except Exception as e:
        logger.warning(f"Personality Engine 工具注册失败: {e}")

    # Vision Action V1.0 - 注册行动工具 + 懒加载 Service
    try:
        from backend.action.tools import register_action_tools
        n = register_action_tools(override=True)
        logger.info(f"Vision Action 工具已注册: {n} 个 (request_action)")
    except Exception as e:
        logger.warning(f"Vision Action 工具注册失败: {e}")

    # Embodied AI V4.1 - 注册具身工具 + 懒加载 Service
    try:
        from backend.embodied.tools import register_embodied_tools
        n = register_embodied_tools(override=True)
        logger.info(f"Embodied AI 工具已注册: {n} 个 (query_environment_state)")
    except Exception as e:
        logger.warning(f"Embodied AI 工具注册失败: {e}")

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
    # V10.1.7: Conversation Turn Controller 集成 (事件协议输出)
    from backend.conversation_controller import (
        ConversationTurnController,
    )
    global _turn_controller
    if _turn_controller is None:
        _turn_controller = ConversationTurnController()
    ctc = _turn_controller
    try:
        logger.info(f"收到聊天请求: {request.text[:50]}...")

        # Turn 生命周期: 接收 → READY (或 QUEUED)
        turn = ctc.begin_turn(request.text, source="user")
        turn_id = turn.turn_id

        # 添加用户消息到上下文
        context_manager.add_message("user", request.text)

        # 获取上下文
        messages = context_manager.get_context(recent_messages=8)

        # 打印发送给LLM的消息，用于调试
        logger.info(f"发送给LLM的消息数: {len(messages)}")
        for i, msg in enumerate(messages):
            logger.info(f"  [{i}] {msg['role']}: {msg['content'][:80]}...")

        # 流式生成响应
        full_response = ""

        async def generate():
            nonlocal full_response
            turn_ = ctc.claim_ready_turn()

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

            # V10.1.7 事件协议: START
            start_evt = ctc.stream_event(turn_id, "START", {
                "input": request.text[:200],
            })
            yield f"data: {json.dumps(start_evt, ensure_ascii=False)}\n\n"

            # 流式 LLM 生成
            ctc.mark_streaming(turn_id)
            async for chunk in llm_engine.generate_stream(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            ):
                full_response += chunk
                # V10.1.7 事件协议: TOKEN (sequence 单调递增)
                tok_evt = ctc.stream_event(turn_id, "TOKEN", {
                    "content": chunk,
                })
                yield f"data: {json.dumps(tok_evt, ensure_ascii=False)}\n\n"

                if request.tts_enabled:
                    await text_queue.put(chunk)

            if request.tts_enabled and tts_task:
                await text_queue.put(None)
                await tts_task

            context_manager.add_message("assistant", full_response)

            # V10.1.7 事件协议: COMPLETE
            comp_evt = ctc.stream_event(turn_id, "COMPLETE", {
                "full_content": full_response,
            })
            yield f"data: {json.dumps(comp_evt, ensure_ascii=False)}\n\n"

            ctc.complete_turn(turn_id)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"聊天请求失败: {e}")
        try:
            ctc.error_turn(turn_id, str(e))
        except Exception:
            pass
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
    voice_identity: Optional[Dict[str, Any]] = None  # M0.4: 顶层 voice_identity 字段（替代 character.yaml）

class VoiceIdentityUpdate(BaseModel):
    """M0.4: voice_identity 专用更新模型（字段级 merge，None=不修改）"""
    voice_id: Optional[str] = None
    engine: Optional[str] = None

@app.get("/personality", summary="获取性格配置", description="获取当前AI的性格设定（含 voice_identity）")
async def get_personality():
    cfg = context_manager.get_personality_config()
    return cfg  # M0.4: 修复原 config.dict() bug（dict 无 .dict() 方法），直接返回 dict

@app.post("/personality", summary="更新性格配置", description="更新AI的性格设定（voice_identity 走字段级 merge）")
async def update_personality(update: PersonalityUpdate):
    update_dict = update.dict(exclude_none=True)
    if update_dict:
        context_manager.update_personality(**update_dict)
        return {"success": True, "message": "性格配置已更新"}
    return {"success": False, "message": "没有提供任何更新"}

@app.post("/personality/reset", summary="重置性格配置", description="将性格配置重置为默认值（含 voice_identity 重置）")
async def reset_personality():
    context_manager.reset_personality()
    return {"success": True, "message": "性格配置已重置"}

# ==================== Voice Identity API (M0.4) ====================
# 替代 character.yaml：personality.json 单源扩展，voice_identity 字段独立端点

@app.get("/personality/voice-identity", summary="获取声音身份", description="获取当前角色绑定的 voice_identity (voice_id + engine)")
async def get_voice_identity():
    vi = context_manager.get_voice_identity()
    return {"success": True, "voice_identity": vi}

@app.post("/personality/voice-identity", summary="更新声音身份", description="字段级更新 voice_identity（None=不修改），持久化到 personality.json")
async def update_voice_identity(update: VoiceIdentityUpdate):
    update_dict = update.dict(exclude_none=True)
    if not update_dict:
        return {"success": False, "message": "没有提供任何更新字段"}
    new_vi = context_manager.update_voice_identity(**update_dict)
    return {"success": True, "message": "voice_identity 已更新", "voice_identity": new_vi}

# ==================== V2.2 声音克隆 API ====================
# 懒加载 voice_identity service 单例 (避免启动时强制初始化)
_voice_identity_service = None

def _get_voice_identity_service():
    """懒加载 VoiceIdentityService (V2.2 + V2.3-Phase6 TEST_MODE)"""
    global _voice_identity_service
    if _voice_identity_service is None:
        try:
            from backend.voice_identity import VoiceIdentityService
            _voice_identity_service = VoiceIdentityService.create_default()
            # V2.3-Phase6: TEST_MODE 下强制 mock adapter, 不加载真实模型
            from backend.voice_identity.mock_loader import is_test_mode, get_mock_loader
            if is_test_mode():
                loader = get_mock_loader()
                adapter_result = loader.load("qwen3")
                if adapter_result.is_ok:
                    _voice_identity_service.set_adapter(adapter_result.unwrap())
                    logger.info("VoiceIdentityService 已初始化 (TEST_MODE, mock adapter)")
                else:
                    logger.warning(f"TEST_MODE mock adapter 加载失败: {adapter_result.error}, 回退到配置加载")
                    _voice_identity_service.load_adapter_from_config()
            else:
                # 生产路径: 从 voice_clone_config.json 加载默认 adapter
                _voice_identity_service.load_adapter_from_config()
                logger.info("VoiceIdentityService 已初始化 (V2.2)")
        except Exception as e:
            logger.error(f"VoiceIdentityService 初始化失败: {e}")
            raise
    return _voice_identity_service

@app.post("/voice/clone", summary="声音克隆", description="上传参考音频克隆声音 (V2.2)")
async def voice_clone(
    request: Request,
    audio: UploadFile = File(..., description="参考音频 wav/mp3/flac/ogg/m4a"),
    name: str = Form(..., description="声音展示名"),
    engine: str = Form("qwen3", description="引擎 qwen3/gpt_sovits"),
    voice_id: Optional[str] = Form(None, description="显式 voice_id (可选)"),
    language: str = Form("zh", description="主语言"),
    metadata: Optional[str] = Form(None, description="JSON 字符串元数据 (gpt_sovits 需含 sovits_model/gpt_model)"),
):
    """声音克隆端点 (V2.2)

    流程: 上传音频 → 校验 → 分析 → 创建 Profile → Adapter.prepare_voice → 返回

    返回:
        成功: {"voice_id", "status", "warnings", "adapter", "quality_score"}
        失败: {"error", "stage"}
    """
    # V2.3-Phase3 权限校验: 创建类操作 (先于 service init, 避免 403 时加载模型)
    try:
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        actor_id = get_actor_id(request)
        get_permission_checker().check_create(actor_id)
    except HTTPException:
        raise  # 403 直接抛出
    except Exception as e:
        logger.warning(f"权限校验异常 (不阻塞): {e}")

    try:
        svc = _get_voice_identity_service()
    except Exception as e:
        return {"success": False, "error": str(e), "stage": "service_init"}

    # V2.3-Phase8: 记录克隆开始时间 (用于延迟指标)
    _clone_start_time = time.time()

    # 1. 校验引擎
    if engine not in ("qwen3", "gpt_sovits"):
        return {"success": False, "error": f"不支持的 engine: {engine}", "stage": "validate"}

    # 2. 保存上传音频到临时文件
    import os, tempfile, json as _json
    try:
        from backend.voice_identity.adapter.config import load_config
        cfg = load_config()
        upload_dir = cfg.upload.temp_dir
        os.makedirs(upload_dir, exist_ok=True)
        max_size = cfg.upload.max_size_mb * 1024 * 1024
    except Exception:
        upload_dir = os.path.join("cache", "voice_clone", "_uploads")
        os.makedirs(upload_dir, exist_ok=True)
        max_size = 50 * 1024 * 1024

    # 读全部内容并校验大小
    content = await audio.read()
    if len(content) == 0:
        return {"success": False, "error": "音频文件为空", "stage": "validate"}
    if len(content) > max_size:
        return {"success": False, "error": f"音频文件过大 (> {max_size//1024//1024}MB)", "stage": "validate"}

    # 扩展名
    ext = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
    tmp_path = os.path.join(upload_dir, f"upload_{int(time.time()*1000)}{ext}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "error": f"保存上传文件失败: {e}", "stage": "validate"}

    # 3. 解析 metadata
    meta_dict = None
    if metadata:
        try:
            meta_dict = _json.loads(metadata)
        except _json.JSONDecodeError as e:
            return {"success": False, "error": f"metadata JSON 解析失败: {e}", "stage": "validate"}

    # 4. 按引擎构造请求级 Adapter (并发安全: 不修改全局 _adapter)
    #    V2.3-Phase6: TEST_MODE 下使用 mock adapter, 不加载真实模型
    request_adapter = None
    try:
        from backend.voice_identity.mock_loader import build_adapter_from_config_test_aware
        adapter_r = build_adapter_from_config_test_aware(engine)
        if adapter_r.is_err():
            return {"success": False, "error": f"Adapter 构造失败: {adapter_r.error}", "stage": "cache"}
        request_adapter = adapter_r.unwrap()
    except Exception as e:
        return {"success": False, "error": f"Adapter 构造失败: {e}", "stage": "cache"}

    # 5. 调用 Service.clone_voice_with_adapter (请求级上下文绑定, 不污染全局)
    result = svc.clone_voice_with_adapter(
        audio_path=tmp_path, name=name, engine=engine,
        voice_id=voice_id, metadata=meta_dict, language=language,
        auto_prepare=True, adapter=request_adapter,
    )

    if result.is_err():
        # 解析 stage: error 以 [validate]/[analyze]/[create_voice]/[register] 开头
        err = str(result.error)
        stage = "unknown"
        for s in ("validate", "analyze", "create_voice", "register", "cache"):
            if f"[{s}]" in err:
                stage = s
                break
        # V2.3-Phase8: 记录失败指标
        try:
            from backend.voice_identity.metrics import record_clone
            record_clone(
                success=False, latency=time.time() - _clone_start_time,
                voice_id=voice_id or "",
            )
        except Exception:
            pass
        return {"success": False, "error": err, "stage": stage}

    clone_result = result.unwrap()
    profile = clone_result.profile
    logger.info(f"声音克隆成功: voice_id={profile.voice_id} adapter={clone_result.adapter}")

    # V2.3-Phase8: 记录成功指标
    try:
        from backend.voice_identity.metrics import record_clone
        record_clone(
            success=True,
            latency=time.time() - _clone_start_time,
            voice_id=profile.voice_id,
            quality_score=clone_result.quality_score,
        )
    except Exception:
        pass

    # Phase 3.3 审计: 记录创建事件 (失败不阻塞)
    try:
        from backend.voice_identity.audit import get_audit_logger
        get_audit_logger().log(
            event_type="voice_created",
            voice_id=profile.voice_id,
            actor_id="system",
            owner_id=profile.owner_id,
            detail={"engine": profile.engine, "name": profile.name, "adapter": clone_result.adapter},
        )
    except Exception:
        pass

    # 克隆成功后可选立即删除上传音频 (由配置 cleanup_on_success 控制)
    try:
        from backend.voice_identity.adapter.config import load_config as _lc
        _cleanup_on_success = _lc().upload.cleanup_on_success
    except Exception:
        _cleanup_on_success = False
    if _cleanup_on_success:
        try:
            from backend.voice_identity.adapter.upload_cleaner import cleanup_file
            cleanup_file(tmp_path)
        except Exception:
            pass

    return {
        "success": True,
        "voice_id": profile.voice_id,
        "name": profile.name,
        "status": profile.status,
        "engine": profile.engine,
        "warnings": clone_result.warnings,
        "adapter": clone_result.adapter,
        "cache_path": clone_result.cache_path,
        "embedding_hash": clone_result.embedding_hash,
        "quality_score": clone_result.quality_score,
    }

@app.post("/voice/synthesize", summary="声音合成测试", description="用已克隆声音合成语音 (V2.2)")
async def voice_synthesize_test(
    voice_id: str = Form(..., description="已克隆的 voice_id"),
    text: str = Form(..., description="待合成文本"),
    language: str = Form("zh", description="语言"),
):
    """声音合成测试端点 (V2.2)

    返回:
        成功: {"audio_path", "text"}
        失败: {"error"}
    """
    try:
        svc = _get_voice_identity_service()
    except Exception as e:
        return {"success": False, "error": str(e)}

    result = svc.synthesize(voice_id=voice_id, text=text, language=language)
    if result.is_err():
        return {"success": False, "error": result.error}
    # Phase 3.3 审计: 记录合成事件 (失败不阻塞)
    try:
        from backend.voice_identity.audit import get_audit_logger
        get_audit_logger().log(
            event_type="voice_synthesized",
            voice_id=voice_id,
            actor_id="system",
            detail={"text": text[:200], "language": language, "audio_path": result.unwrap()},
        )
    except Exception:
        pass
    return {"success": True, "audio_path": result.unwrap(), "text": text}

# ==================== Phase 2.1 声音资产管理 ====================

@app.get("/voice/list", summary="声音列表", description="获取所有已克隆声音 (Phase 2.1)")
async def voice_list():
    """返回所有 voice profile (按 created_time 倒序)"""
    try:
        svc = _get_voice_identity_service()
    except Exception as e:
        return {"success": False, "error": str(e)}
    try:
        profiles = svc.list_voice()
        items = []
        for p in profiles:
            items.append({
                "voice_id": p.voice_id,
                "name": p.name,
                "engine": p.engine,
                "type": p.type,
                "status": p.status,
                "created_time": p.created_at,
                "language": p.language,
                "metadata": p.metadata,
            })
        return {"success": True, "total": len(items), "items": items}
    except Exception as e:
        logger.error(f"声音列表查询失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/{voice_id}", summary="声音详情", description="查询单个声音 profile (Phase 2.1)")
async def voice_detail(voice_id: str):
    """返回指定 voice_id 的 profile + model 信息"""
    try:
        svc = _get_voice_identity_service()
    except Exception as e:
        return {"success": False, "error": str(e)}
    try:
        db = svc.db
        profile = db.get_profile_by_id(voice_id)
        if profile is None:
            return {"success": False, "error": f"voice_id 不存在: {voice_id}"}
        return {
            "success": True,
            "voice_id": profile.voice_id,
            "name": profile.name,
            "engine": profile.engine,
            "type": profile.type,
            "status": profile.status,
            "created_time": profile.created_at,
            "language": profile.language,
            "metadata": profile.metadata,
        }
    except Exception as e:
        logger.error(f"声音详情查询失败: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/voice/{voice_id}", summary="删除声音", description="删除指定声音 (Phase 2.1)")
async def voice_delete(voice_id: str, request: Request, soft: bool = False):
    """删除 voice profile + 关联缓存

    参数:
        soft: True=软删(保留数据), False=硬删(级联清理, 默认)
    """
    try:
        svc = _get_voice_identity_service()
    except Exception as e:
        return {"success": False, "error": str(e)}
    # V2.3-Phase3 权限校验: delete 须 owner/system
    try:
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        actor_id = get_actor_id(request)
        get_permission_checker().check_delete(svc, voice_id, actor_id)
    except HTTPException:
        raise  # 403/404 直接抛出
    except Exception as e:
        logger.warning(f"权限校验异常 (不阻塞): {e}")
    try:
        # 先查存在性
        db = svc.db
        profile = db.get_profile_by_id(voice_id)
        if profile is None:
            return {"success": False, "error": f"voice_id 不存在: {voice_id}"}
        # 经 Service 删除 (会清理缓存), 返回 bool
        ok = svc.delete_voice(voice_id, soft=soft)
        if not ok:
            return {"success": False, "error": f"删除失败: {voice_id}"}
        logger.info(f"声音已删除: {voice_id} soft={soft}")
        # Phase 3.3 审计: 记录删除事件 (失败不阻塞)
        try:
            from backend.voice_identity.audit import get_audit_logger
            get_audit_logger().log(
                event_type="voice_deleted",
                voice_id=voice_id,
                actor_id=actor_id,
                owner_id=profile.owner_id,
                detail={"soft": soft, "name": profile.name},
            )
        except Exception:
            pass
        return {"success": True, "voice_id": voice_id, "soft": soft}
    except Exception as e:
        logger.error(f"声音删除失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== 上传音频清理 ====================

@app.post("/voice/uploads/cleanup", summary="清理超时上传音频", description="按 TTL 清理 _uploads 目录 (工程化项)")
async def voice_uploads_cleanup_ttl():
    """按 TTL 清理超时的上传音频文件"""
    try:
        from backend.voice_identity.adapter.upload_cleaner import cleanup_expired
        stats = cleanup_expired()
        return {"success": True, "stats": stats.to_dict()}
    except Exception as e:
        logger.error(f"TTL 清理失败: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/voice/uploads/cleanup-all", summary="清理全部上传音频", description="删除 _uploads 目录下所有音频 (无视 TTL)")
async def voice_uploads_cleanup_all():
    """手动清理: 删除所有上传音频"""
    try:
        from backend.voice_identity.adapter.upload_cleaner import cleanup_all
        stats = cleanup_all()
        return {"success": True, "stats": stats.to_dict()}
    except Exception as e:
        logger.error(f"全量清理失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== Phase 1.3 质量评估 ====================

@app.post("/voice/quality/evaluate", summary="音频质量评估", description="评估合成音频质量 (Phase 1.3)")
async def voice_quality_evaluate(
    request: Request,
    reference_audio: UploadFile = File(..., description="原始参考音频 wav"),
    synthesized_audio: UploadFile = File(..., description="合成音频 wav"),
    reference_text: Optional[str] = Form(None, description="原始文本 (可选, 用于 WER)"),
    use_asr: bool = Form(False, description="是否启用 ASR 转写计算 WER (需 ASR 引擎就绪)"),
):
    """质量评估端点 (Phase 1.3)

    返回 QualityReport: similarity_score / wer / snr / duration_score / status
    """
    # V2.3-Phase3 权限校验: synthesize (评估合成质量)
    try:
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        actor_id = get_actor_id(request)
        get_permission_checker().check_create(actor_id)  # 复用: 拒绝 anonymous/guest
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"权限校验异常 (不阻塞): {e}")
    import os, tempfile
    from backend.voice_identity.adapter.voice_quality_evaluator import evaluate_quality

    tmp_dir = tempfile.mkdtemp(prefix="yhlz_quality_")
    try:
        ref_path = os.path.join(tmp_dir, "ref.wav")
        syn_path = os.path.join(tmp_dir, "syn.wav")
        with open(ref_path, "wb") as f:
            f.write(await reference_audio.read())
        with open(syn_path, "wb") as f:
            f.write(await synthesized_audio.read())

        asr_fn = None
        if use_asr:
            try:
                from backend.asr_engine import asr_engine
                def asr_fn(p):
                    return asr_engine.transcribe_file(p)
            except Exception as e:
                logger.warning(f"ASR 引擎不可用, 跳过 WER: {e}")

        report = evaluate_quality(ref_path, syn_path, reference_text, asr_fn)
        return {"success": True, "report": report.to_dict()}
    except Exception as e:
        logger.error(f"质量评估失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

# ==================== Phase 2.3 Adapter Dashboard ====================

@app.get("/voice/adapters/dashboard", summary="Adapter 状态面板", description="获取所有 Adapter 健康状态 (Phase 2.3)")
async def voice_adapters_dashboard():
    """返回各 adapter 的 mode/can_serve/health_check"""
    try:
        from backend.voice_identity.adapter import list_adapters, build_adapter
        from backend.voice_identity.adapter.config import load_config
        cfg = load_config()
        items = []
        for name in list_adapters():
            entry = {"name": name}
            try:
                if name == "qwen3":
                    mode = cfg.qwen3.mode
                elif name == "gpt_sovits":
                    mode = cfg.gpt_sovits.mode
                else:
                    mode = "unknown"
                entry["mode"] = mode
                # 构造 adapter 实例 (mock 模式不依赖外部服务)
                r = build_adapter(name, {
                    "mode": mode,
                    "cache_dir": getattr(cfg, name, cfg.qwen3).cache_dir if hasattr(getattr(cfg, name, None), "cache_dir") else "cache/voice_clone",
                })
                if r.is_ok:
                    ad = r.unwrap()
                    entry["can_serve"] = ad.can_serve()
                    entry["health"] = ad.health_check()
                else:
                    entry["can_serve"] = False
                    entry["health"] = {"ok": False, "error": r.error}
            except Exception as e:
                entry["can_serve"] = False
                entry["health"] = {"ok": False, "error": str(e)}
            items.append(entry)
        return {"success": True, "adapters": items}
    except Exception as e:
        logger.error(f"Adapter Dashboard 查询失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== Phase 2.2 音频试听 ====================

@app.get("/voice/audio/{voice_id}", summary="音频试听", description="获取合成音频文件 (Phase 2.2)")
async def voice_audio_play(voice_id: str):
    """返回指定 voice_id 的合成音频文件 (供 <audio> 试听)

    优先返回该 voice 的最近合成结果; 若无则 404。
    """
    import os
    from fastapi.responses import FileResponse
    try:
        # 在 cache/voice_clone 下查找该 voice_id 的音频文件
        cache_root = os.path.join("cache", "voice_clone")
        # 1. 查找 _uploads 下的合成结果 (mock synthesize 写入)
        synth_dir = os.path.join(cache_root, "_synth")
        if os.path.isdir(synth_dir):
            candidates = [f for f in os.listdir(synth_dir) if f.startswith(voice_id) and f.endswith(".wav")]
            if candidates:
                candidates.sort(key=lambda f: os.path.getmtime(os.path.join(synth_dir, f)), reverse=True)
                return FileResponse(os.path.join(synth_dir, candidates[0]), media_type="audio/wav")
        # 2. 查找 voice_cache 永久缓存
        vc_dir = os.path.join("backend", "data", "voice_cache", voice_id)
        if os.path.isdir(vc_dir):
            wavs = [f for f in os.listdir(vc_dir) if f.endswith(".wav")]
            if wavs:
                return FileResponse(os.path.join(vc_dir, wavs[0]), media_type="audio/wav")
        return {"success": False, "error": f"无音频文件: {voice_id}"}
    except Exception as e:
        logger.error(f"音频试听失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== Phase 3.1 批量克隆任务 ====================

@app.post("/voice/clone/batch", summary="批量声音克隆", description="提交批量克隆任务 (Phase 3.1)")
async def voice_clone_batch(
    request: Request,
    items_json: str = Form(..., description='任务项 JSON 数组, 每项含 audio_path/name/engine/language/metadata'),
    owner: str = Form("system", description="任务发起者"),
):
    """批量克隆端点 (Phase 3.1)

    参数:
        items_json: JSON 数组字符串, 每项 {audio_path, name, engine?, language?, metadata?}
        owner: 任务发起者

    返回:
        {"success": true, "task": {task_id, status, total, ...}}
    """
    # V2.3-Phase3 权限校验: 创建类操作 (先于 service init)
    try:
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        actor_id = get_actor_id(request)
        get_permission_checker().check_create(actor_id)
        # actor 覆盖 owner (除非 owner 显式指定非默认值)
        if owner == "system":
            owner = actor_id
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"权限校验异常 (不阻塞): {e}")
    import json as _json
    try:
        from backend.voice_identity.batch import get_task_queue, BatchTaskError
        items = _json.loads(items_json)
        if not isinstance(items, list):
            return {"success": False, "error": "items_json 必须是 JSON 数组"}
        queue = get_task_queue()
        task = queue.submit(items, owner=owner)
        return {"success": True, "task": task.to_dict()}
    except BatchTaskError as e:
        return {"success": False, "error": str(e)}
    except _json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON 解析失败: {e}"}
    except Exception as e:
        logger.error(f"批量克隆提交失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/clone/batch/{task_id}", summary="批量任务状态", description="查询批量克隆任务状态 (Phase 3.1)")
async def voice_clone_batch_status(task_id: str):
    """查询批量任务详情"""
    try:
        from backend.voice_identity.batch import get_task_queue
        task = get_task_queue().get_task(task_id)
        if task is None:
            return {"success": False, "error": f"任务不存在: {task_id}"}
        return {"success": True, "task": task.to_dict()}
    except Exception as e:
        logger.error(f"批量任务查询失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/clone/batch", summary="批量任务列表", description="列出最近批量克隆任务 (Phase 3.1)")
async def voice_clone_batch_list(limit: int = 50):
    """列出最近批量任务 (摘要)"""
    try:
        from backend.voice_identity.batch import get_task_queue
        summaries = get_task_queue().list_tasks(limit=limit)
        return {"success": True, "total": len(summaries), "items": [s.to_dict() for s in summaries]}
    except Exception as e:
        logger.error(f"批量任务列表失败: {e}")
        return {"success": False, "error": str(e)}

@app.post("/voice/clone/batch/{task_id}/cancel", summary="取消批量任务", description="取消未完成的批量任务项 (Phase 3.1)")
async def voice_clone_batch_cancel(task_id: str):
    """取消批量任务 (仅标记, 不中断已运行项)"""
    try:
        from backend.voice_identity.batch import get_task_queue
        ok = get_task_queue().cancel(task_id)
        if not ok:
            return {"success": False, "error": f"任务不存在或已完成: {task_id}"}
        return {"success": True, "task_id": task_id}
    except Exception as e:
        logger.error(f"批量任务取消失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== Phase 3.2 声音去重 ====================

@app.post("/voice/duplicate/check", summary="声音去重检测", description="检测音频是否与已有声音重复 (Phase 3.2)")
async def voice_duplicate_check(
    audio: UploadFile = File(..., description="待检测音频 wav/mp3"),
    threshold: float = Form(0.85, description="相似度阈值 (0.0~1.0)"),
    skip_asr: bool = Form(True, description="跳过声学特征分析 (仅哈希匹配)"),
):
    """去重检测端点 (Phase 3.2)

    返回 DuplicateResult: is_duplicate/confidence/matched_voice_id/match_type
    """
    import os, tempfile
    try:
        from backend.voice_identity.dedup import VoiceDeduplicator
        from backend.voice_identity.clone.audio_validator import validate_audio
        from backend.voice_identity.clone.voice_analyzer import analyze_voice

        svc = _get_voice_identity_service()
        dedup = VoiceDeduplicator(svc, threshold=threshold)

        # 保存上传音频
        tmp_dir = tempfile.mkdtemp(prefix="yhlz_dedup_")
        ext = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        tmp_path = os.path.join(tmp_dir, f"check{ext}")
        with open(tmp_path, "wb") as f:
            f.write(await audio.read())

        # 可选: 提取特征 (提高检测精度)
        feature = None
        if not skip_asr:
            v = validate_audio(tmp_path)
            if v.is_ok():
                a = analyze_voice(v.unwrap())
                if a.is_ok():
                    feature = a.unwrap()

        result = dedup.check_duplicate(tmp_path, feature=feature)
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        logger.error(f"去重检测失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

# ==================== Phase 3.3 安全与审计 ====================

@app.get("/voice/audit/log", summary="审计日志查询", description="查询声音操作审计日志 (Phase 3.3)")
async def voice_audit_log(
    voice_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """审计日志查询端点 (Phase 3.3)

    支持按 voice_id/event_type/actor_id/时间范围 筛选
    """
    try:
        from backend.voice_identity.audit import get_audit_logger
        logger_audit = get_audit_logger()
        entries = logger_audit.query(
            voice_id=voice_id, event_type=event_type, actor_id=actor_id,
            start_time=start_time, end_time=end_time,
            limit=limit, offset=offset,
        )
        total = logger_audit.count(voice_id=voice_id, event_type=event_type, actor_id=actor_id)
        return {
            "success": True, "total": total, "limit": limit, "offset": offset,
            "items": [e.to_dict() for e in entries],
        }
    except Exception as e:
        logger.error(f"审计日志查询失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/audit/count", summary="审计日志计数", description="统计审计日志条数 (Phase 3.3)")
async def voice_audit_count(
    voice_id: Optional[str] = None,
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
):
    """审计日志计数端点 (Phase 3.3)"""
    try:
        from backend.voice_identity.audit import get_audit_logger
        count = get_audit_logger().count(
            voice_id=voice_id, event_type=event_type, actor_id=actor_id,
        )
        return {"success": True, "count": count}
    except Exception as e:
        logger.error(f"审计日志计数失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/audit/permission/{voice_id}", summary="权限检查", description="检查操作者对声音的权限 (Phase 3.3)")
async def voice_permission_check(
    voice_id: str,
    actor_id: str = "system",
    action: str = "read",
):
    """权限检查端点 (Phase 3.3)

    action: read/write/delete/synthesize
    """
    try:
        from backend.voice_identity.audit import VoicePermission, PermissionError
        svc = _get_voice_identity_service()
        profile = svc.get_voice(voice_id)
        if profile is None:
            return {"success": False, "error": f"voice_id 不存在: {voice_id}"}
        perm = VoicePermission()
        allowed = perm.can(profile, actor_id, action)
        return {
            "success": True,
            "voice_id": voice_id,
            "actor_id": actor_id,
            "action": action,
            "allowed": allowed,
            "owner_id": profile.owner_id,
        }
    except Exception as e:
        logger.error(f"权限检查失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== V2.3-Phase4 声音生命周期 ====================

@app.post("/voice/{voice_id}/archive", summary="归档声音", description="将声音归档 (V2.3-Phase4)")
async def voice_archive(voice_id: str, request: Request):
    """归档声音 (ready/active/inactive → archived)"""
    try:
        from backend.voice_identity.voice_lifecycle import get_lifecycle
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        svc = _get_voice_identity_service()
        actor_id = get_actor_id(request)
        # 归档须 write 权限 (owner/system)
        try:
            get_permission_checker().check_write(svc, voice_id, actor_id)
        except HTTPException:
            raise
        result = get_lifecycle().archive_voice(voice_id)
        return {"success": result.success, "result": result.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"归档声音失败: {e}")
        return {"success": False, "error": str(e)}

@app.post("/voice/{voice_id}/restore", summary="恢复归档声音", description="恢复归档/停用声音 (V2.3-Phase4)")
async def voice_restore(voice_id: str, request: Request):
    """恢复声音 (archived/inactive → ready)"""
    try:
        from backend.voice_identity.voice_lifecycle import get_lifecycle
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        svc = _get_voice_identity_service()
        actor_id = get_actor_id(request)
        try:
            get_permission_checker().check_write(svc, voice_id, actor_id)
        except HTTPException:
            raise
        result = get_lifecycle().restore_voice(voice_id)
        return {"success": result.success, "result": result.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复声音失败: {e}")
        return {"success": False, "error": str(e)}

@app.post("/voice/lifecycle/cleanup", summary="生命周期清理", description="按使用时长自动降级未使用声音 (V2.3-Phase4)")
async def voice_lifecycle_cleanup(
    request: Request,
    inactive_days: int = Form(90, description="未使用降级 inactive 天数"),
    archive_days: int = Form(180, description="未使用归档天数"),
):
    """批量清理未使用声音 (90d → inactive, 180d → archived)"""
    try:
        from backend.voice_identity.voice_lifecycle import get_lifecycle
        from backend.voice_identity.permission import get_permission_checker, get_actor_id
        # 清理须 system 权限
        actor_id = get_actor_id(request)
        if actor_id != "system":
            raise HTTPException(status_code=403, detail="permission denied: 仅 system 可执行生命周期清理")
        report = get_lifecycle().cleanup_unused_voice(
            inactive_days=inactive_days, archive_days=archive_days,
        )
        return {"success": True, "report": report.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生命周期清理失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/voice/lifecycle/list", summary="生命周期状态列表", description="列出归档/停用声音 (V2.3-Phase4)")
async def voice_lifecycle_list(status: Optional[str] = None):
    """列出归档/停用声音"""
    try:
        from backend.voice_identity.voice_lifecycle import get_lifecycle
        lc = get_lifecycle()
        if status == "archived":
            items = lc.list_archived()
        elif status == "inactive":
            items = lc.list_inactive()
        else:
            items = lc.list_archived() + lc.list_inactive()
        return {
            "success": True,
            "total": len(items),
            "items": [
                {
                    "voice_id": p.voice_id, "name": p.name,
                    "status": p.status, "owner_id": p.owner_id,
                    "created_at": p.created_at,
                } for p in items
            ],
        }
    except Exception as e:
        logger.error(f"生命周期列表查询失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== V2.3-Phase7 WebUI Dashboard 生产化 ====================

@app.get("/voice/dashboard", summary="声音系统仪表盘", description="聚合统计: 声音/任务/质量/Adapter (V2.3-Phase7)")
async def voice_dashboard():
    """Dashboard 聚合统计端点

    返回:
        - voices: 声音数量统计 (total/active/ready/archived)
        - tasks: 任务统计 (total/pending/running/done/failed)
        - quality: 质量统计 (avg_score/distribution)
        - adapters: Adapter 状态 (engine/loaded/health)
        - metrics: 累计监控指标 (clone_total/success/failed/latency)
    """
    try:
        svc = _get_voice_identity_service()
        # 声音统计
        all_profiles = svc.list_voice()
        voice_stats = {
            "total": len(all_profiles),
            "active": sum(1 for p in all_profiles if p.status == "active"),
            "ready": sum(1 for p in all_profiles if p.status == "ready"),
            "archived": sum(1 for p in all_profiles if p.status == "archived"),
            "warning": sum(1 for p in all_profiles if p.status == "warning"),
        }
        # 任务统计
        task_stats = {"total": 0, "pending": 0, "running": 0, "done": 0, "failed": 0}
        try:
            from backend.voice_identity.batch import get_task_queue
            summaries = get_task_queue().list_tasks(limit=1000)
            task_stats["total"] = len(summaries)
            for s in summaries:
                if s.status in task_stats:
                    task_stats[s.status] += 1
        except Exception:
            pass
        # 质量统计
        quality_scores = [
            getattr(p, "quality_score", None) for p in all_profiles
            if getattr(p, "quality_score", None) is not None
        ]
        quality_stats = {
            "count": len(quality_scores),
            "avg_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0,
        }
        # Adapter 状态
        adapters_info = {"test_mode": False, "engines": []}
        try:
            from backend.voice_identity.mock_loader import is_test_mode, get_mock_loader
            adapters_info["test_mode"] = is_test_mode()
            if is_test_mode():
                adapters_info["engines"] = get_mock_loader().health_check().get("loaded_engines", [])
            else:
                # 生产环境: 检查 service 注入的 adapter
                adp = getattr(svc, "_adapter", None)
                if adp is not None:
                    adapters_info["engines"] = [adp.name]
        except Exception:
            pass
        # 监控指标
        metrics_snapshot = {}
        try:
            from backend.voice_identity.metrics import get_metrics
            m = get_metrics().get_snapshot()
            metrics_snapshot = {
                "clone_total": m.clone_total,
                "clone_success": m.clone_success,
                "clone_failed": m.clone_failed,
                "adapter_error_total": m.adapter_error_total,
                "latency_avg": round(m.latency_sum / m.latency_count, 4) if m.latency_count > 0 else 0,
                "last_clone_latency": m.last_clone_latency,
                "last_clone_quality": m.last_clone_quality,
            }
        except Exception:
            pass
        return {
            "success": True,
            "voices": voice_stats,
            "tasks": task_stats,
            "quality": quality_stats,
            "adapters": adapters_info,
            "metrics": metrics_snapshot,
        }
    except Exception as e:
        logger.error(f"Dashboard 查询失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== V2.3-Phase8 监控系统 ====================

@app.get("/metrics", summary="Prometheus 指标", description="Prometheus 文本格式监控指标 (V2.3-Phase8)")
async def metrics_endpoint():
    """Prometheus scrape 端点

    返回 voice_clone_total / voice_clone_success / voice_clone_failed /
    voice_clone_latency_seconds / voice_quality_score / voice_adapter_error_total
    """
    from backend.voice_identity.metrics import render_prometheus
    from fastapi import Response
    text = render_prometheus()
    return Response(content=text, media_type="text/plain; version=0.0.4; charset=utf-8")

@app.get("/voice/metrics", summary="Voice 指标 JSON", description="Voice Identity 指标 JSON 格式 (V2.3-Phase8)")
async def voice_metrics_json():
    """JSON 格式指标 (便于 WebUI 直接消费)"""
    try:
        from backend.voice_identity.metrics import get_metrics
        m = get_metrics().get_snapshot()
        return {
            "success": True,
            "clone_total": m.clone_total,
            "clone_success": m.clone_success,
            "clone_failed": m.clone_failed,
            "adapter_error_total": m.adapter_error_total,
            "latency_sum": round(m.latency_sum, 4),
            "latency_count": m.latency_count,
            "latency_avg": round(m.latency_sum / m.latency_count, 4) if m.latency_count > 0 else 0,
            "quality_sum": round(m.quality_sum, 4),
            "quality_count": m.quality_count,
            "quality_avg": round(m.quality_sum / m.quality_count, 4) if m.quality_count > 0 else 0,
            "adapter_errors": dict(m.adapter_errors),
            "last_clone_voice_id": m.last_clone_voice_id,
            "last_clone_latency": m.last_clone_latency,
            "last_clone_quality": m.last_clone_quality,
        }
    except Exception as e:
        logger.error(f"Voice 指标查询失败: {e}")
        return {"success": False, "error": str(e)}

# ==================== V2.3-Phase9 安全增强 ====================

@app.post("/voice/security/check", summary="音频安全检查", description="检查音频文件安全性 (V2.3-Phase9)")
async def voice_security_check(
    audio: UploadFile = File(..., description="待检查音频"),
):
    """安全检查端点

    检查项: 文件大小 / 格式白名单 / 时长上限 / SHA256 哈希 / 静音 / 削波
    返回 SecurityReport
    """
    import os, tempfile
    try:
        content = await audio.read()
        if not content:
            return {"success": False, "error": "音频文件为空"}
        # 保存到临时文件
        ext = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        tmp_path = os.path.join(tempfile.gettempdir(), f"sec_check_{int(time.time()*1000)}{ext}")
        with open(tmp_path, "wb") as f:
            f.write(content)
        try:
            from backend.voice_identity.voice_security import check_audio_security
            report = check_audio_security(tmp_path)
            return {"success": True, "report": report.to_dict()}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"安全检查失败: {e}")
        return {"success": False, "error": str(e)}

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
                messages = context_manager.get_context(recent_messages=8)
                
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


# ==================== Agent API (V3.0) ====================
# 新增 /agent/* 端点, 不破坏 V2.3 已有接口

class AgentChatRequest(BaseModel):
    query: str
    use_tools: bool = True
    use_memory: Optional[bool] = None
    history: Optional[List[Dict[str, Any]]] = []

@app.post("/agent/chat", summary="Agent 对话 (含工具调用与记忆)")
async def agent_chat(request: AgentChatRequest):
    """V3.0 Agent 主入口: ReAct 循环 + 工具调用 + 记忆"""
    try:
        from backend.agent.service import get_service
        from backend.agent.schemas import Message
        svc = get_service()
        # 转换历史消息
        history = None
        if request.history:
            history = []
            for m in request.history:
                role = m.get("role", "user")
                content = m.get("content", "")
                history.append(Message(role=role, content=content))
        result = await svc.chat(
            query=request.query,
            history=history,
            use_tools=request.use_tools,
            use_memory=request.use_memory,
        )
        return {
            "success": result.success,
            "answer": result.answer,
            "iterations": result.iterations,
            "tool_calls": [tc.to_openai_dict() for tc in result.tool_calls],
            "memory_used": result.memory_used,
            "memory_stored": result.memory_stored,
            "latency_ms": round(result.latency_ms, 2),
            "steps_count": len(result.steps),
            "error": result.error,
        }
    except Exception as e:
        logger.error(f"Agent 对话失败: {e}", exc_info=True)
        return {"success": False, "answer": "", "error": str(e)}


@app.post("/agent/chat/stream", summary="Agent 流式对话 (SSE)")
async def agent_chat_stream(request: AgentChatRequest):
    """V3.0 Agent 流式对话 (不含工具调用)"""
    from backend.agent.service import get_service
    from backend.agent.schemas import Message
    svc = get_service()
    history = None
    if request.history:
        history = [Message(role=m.get("role", "user"), content=m.get("content", "")) for m in request.history]

    async def _gen():
        async for ch in svc.chat_stream(request.query, history=history):
            yield f"data: {ch}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.post("/agent/plan", summary="生成执行计划")
async def agent_plan(request: Request):
    """V3.0 任务规划: 将目标分解为步骤"""
    try:
        body = await request.json()
        goal = body.get("goal", "")
        available_tools = body.get("available_tools")
        if not goal:
            return {"success": False, "error": "goal 为空"}
        from backend.agent.service import get_service
        svc = get_service()
        plan = svc.plan(goal, available_tools)
        return {
            "success": True,
            "plan": {
                "id": plan.id,
                "goal": plan.goal,
                "steps": [
                    {"id": s.id, "description": s.description, "tool": s.tool, "status": s.status}
                    for s in plan.steps
                ],
                "created_at": plan.created_at,
            },
        }
    except Exception as e:
        logger.error(f"Agent 规划失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@app.get("/agent/tools", summary="列出可用工具")
async def agent_list_tools(category: Optional[str] = None):
    """V3.0 列出所有已注册工具"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        return {"success": True, "tools": svc.list_tools(category=category), "count": len(svc.list_tools(category=category))}
    except Exception as e:
        return {"success": False, "error": str(e), "tools": []}


@app.get("/agent/tools/{tool_name}", summary="获取工具详情")
async def agent_get_tool(tool_name: str):
    """V3.0 获取单个工具详情"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        t = svc.get_tool(tool_name)
        if t is None:
            raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")
        return {"success": True, "tool": t}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/agent/status", summary="Agent 系统状态")
async def agent_status():
    """V3.0 Agent 系统状态"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        return {"success": True, **svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/agent/memory", summary="添加记忆")
async def agent_memory_add(request: Request):
    """V3.0 添加记忆条目"""
    try:
        body = await request.json()
        content = body.get("content", "")
        category = body.get("category", "fact")
        source = body.get("source", "user")
        metadata = body.get("metadata")
        if not content:
            return {"success": False, "error": "content 为空"}
        from backend.agent.service import get_service
        svc = get_service()
        mem_id = await svc.memory_add(content, category, source, metadata)
        return {"success": True, "memory_id": mem_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/agent/memory", summary="列出记忆")
async def agent_memory_list(category: Optional[str] = None, limit: int = 100, offset: int = 0):
    """V3.0 列出记忆"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        entries = await svc.memory_list(category, limit, offset)
        return {
            "success": True,
            "memories": [e.to_dict() for e in entries],
            "count": len(entries),
            "total": await svc.memory_count(category),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "memories": []}


@app.get("/agent/memory/search", summary="搜索记忆")
async def agent_memory_search(query: str, limit: int = 5, category: Optional[str] = None):
    """V3.0 搜索记忆 (关键词匹配)"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        entries = await svc.memory_search(query, limit, category)
        return {"success": True, "memories": [e.to_dict() for e in entries], "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e), "memories": []}


@app.get("/agent/memory/short-term", summary="获取短期记忆")
async def agent_memory_short_term(limit: int = 10):
    """V3.0 获取短期记忆 (最近对话)"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        items = svc.memory_short_term(limit=limit)
        return {"success": True, "memories": items, "count": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e), "memories": []}


@app.get("/agent/memory/{memory_id}", summary="获取记忆详情")
async def agent_memory_get(memory_id: str):
    """V3.0 获取单个记忆"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        entry = await svc.memory_get(memory_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
        return {"success": True, "memory": entry.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.put("/agent/memory/{memory_id}", summary="更新记忆")
async def agent_memory_update(memory_id: str, request: Request):
    """V3.0 更新记忆字段"""
    try:
        body = await request.json()
        from backend.agent.service import get_service
        svc = get_service()
        ok = await svc.memory_update(memory_id, **body)
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/agent/memory/{memory_id}", summary="删除记忆")
async def agent_memory_delete(memory_id: str):
    """V3.0 删除记忆"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        ok = await svc.memory_delete(memory_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
        return {"success": True, "deleted": memory_id}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/agent/memory", summary="清空所有记忆")
async def agent_memory_clear():
    """V3.0 清空记忆库"""
    try:
        from backend.agent.service import get_service
        svc = get_service()
        n = await svc.memory_clear()
        return {"success": True, "deleted_count": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== Vision Perception V1.0 ====================

def _get_perception_service():
    """获取 PerceptionService 单例 (按 config 自动加载权限)"""
    from backend.vision.perception.service import get_service
    svc = get_service()
    if not svc._initialized:
        svc.load_config({
            "perception_enabled": config.perception_enabled,
            "ocr_enabled": config.perception_ocr_enabled,
            "detection_enabled": config.perception_detection_enabled,
            "allow_image_save": config.perception_allow_image_save,
            "max_image_size": config.perception_max_image_size,
            "min_confidence": config.perception_min_confidence,
            "save_policy": config.perception_save_policy,
        })
        # 懒加载注入 VisionService (用于截屏后感知)
        try:
            from backend.vision.service import get_service as _get_vision_service
            svc.set_vision_service(_get_vision_service())
        except Exception as e:
            logger.warning(f"VisionService 注入失败: {e}")
    return svc


@app.get("/perception/status", summary="感知系统状态", description="获取 Perception 子系统状态 (V1.0)")
async def perception_status():
    try:
        svc = _get_perception_service()
        return {"success": True, "status": svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/perception/permission", summary="获取感知权限", description="获取当前 Perception 权限配置")
async def perception_get_permission():
    try:
        svc = _get_perception_service()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/permission", summary="更新感知权限", description="字段级更新 Perception 权限 (None=不修改)")
async def perception_update_permission(payload: Dict[str, Any] = None):
    try:
        svc = _get_perception_service()
        if payload is None:
            payload = {}
        # 过滤 None 值 (字段级更新)
        updates = {k: v for k, v in payload.items() if v is not None}
        if updates:
            perm = svc.update_permission(**updates)
            return {"success": True, "permission": perm.to_dict()}
        return {"success": True, "permission": svc.get_permission(), "note": "无更新字段"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/reset-permission", summary="重置感知权限", description="重置为默认 (全部拒绝)")
async def perception_reset_permission():
    try:
        svc = _get_perception_service()
        svc.reset_permission()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/ocr", summary="OCR 文字识别", description="对上传图片执行 OCR 识别 (V1.0)")
async def perception_ocr(
    file: UploadFile = File(...),
    language: str = Form("zh"),
    min_confidence: float = Form(0.0),
):
    """上传图片并执行 OCR 识别

    Args:
        file: 图片文件 (PNG / JPG)
        language: 期望语言 (zh / en / mixed)
        min_confidence: 最小置信度阈值
    """
    try:
        import numpy as np
        import cv2

        # 读取上传图片
        contents = await file.read()
        img_array = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "无法解码图片"}

        svc = _get_perception_service()
        result = svc.recognize_ocr(
            image=image,
            language=language,
            min_confidence=min_confidence,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/detect", summary="目标检测", description="对上传图片执行目标检测 (V1.0)")
async def perception_detect(
    file: UploadFile = File(...),
    min_confidence: float = Form(0.0),
    max_objects: Optional[int] = Form(None),
):
    """上传图片并执行目标检测"""
    try:
        import numpy as np
        import cv2

        contents = await file.read()
        img_array = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "无法解码图片"}

        svc = _get_perception_service()
        result = svc.detect_objects(
            image=image,
            min_confidence=min_confidence,
            max_objects=max_objects,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/combined", summary="联合感知", description="同时执行 OCR + Detection (V1.0)")
async def perception_combined(
    file: UploadFile = File(...),
    language: str = Form("zh"),
    min_confidence: float = Form(0.0),
    max_objects: Optional[int] = Form(None),
):
    """上传图片并执行联合感知 (OCR + Detection)"""
    try:
        import numpy as np
        import cv2

        contents = await file.read()
        img_array = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "无法解码图片"}

        svc = _get_perception_service()
        result = svc.perceive_combined(
            image=image,
            language=language,
            min_confidence=min_confidence,
            max_objects=max_objects,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/screen/ocr", summary="截屏 OCR", description="截取当前屏幕并执行 OCR (需 screen + ocr 权限)")
async def perception_screen_ocr(
    region: Optional[str] = Form(None),         # JSON 字符串: {"x":0,"y":0,"w":100,"h":100}
    language: str = Form("zh"),
):
    """截屏并 OCR"""
    try:
        import json as _json
        svc = _get_perception_service()
        region_dict = _json.loads(region) if region else None
        result = svc.capture_screen_and_perceive(
            mode="ocr",
            region=region_dict,
            language=language,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/perception/screen/detect", summary="截屏检测", description="截取当前屏幕并执行目标检测")
async def perception_screen_detect(
    region: Optional[str] = Form(None),
):
    """截屏并检测"""
    try:
        import json as _json
        svc = _get_perception_service()
        region_dict = _json.loads(region) if region else None
        result = svc.capture_screen_and_perceive(
            mode="detection",
            region=region_dict,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/perception/adapters", summary="Adapter 列表", description="列出所有 OCR / Detection Adapter")
async def perception_list_adapters():
    try:
        svc = _get_perception_service()
        return {
            "success": True,
            "ocr_adapters": svc.list_ocr_adapters(),
            "detection_adapters": svc.list_detection_adapters(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/perception/logs", summary="感知日志查询", description="查询感知处理日志")
async def perception_logs(
    source: Optional[str] = None,
    adapter: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 100,
):
    try:
        svc = _get_perception_service()
        return {
            "success": True,
            "logs": svc.get_logs(source=source, adapter=adapter, event=event, limit=limit),
            "stats": svc.get_log_stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/perception/logs", summary="清空感知日志", description="清空所有感知处理日志")
async def perception_clear_logs():
    try:
        svc = _get_perception_service()
        n = svc.clear_logs()
        return {"success": True, "cleared": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== Vision Understanding V1.0 ====================

def _get_understanding_service():
    """获取 UnderstandingService 单例 (按 config 自动加载权限)"""
    from backend.vision.understanding.service import get_service
    svc = get_service()
    if not svc._initialized:
        svc.load_config({
            "understanding_enabled": config.understanding_enabled,
            "allow_image_save": config.understanding_allow_image_save,
            "max_image_size": config.understanding_max_image_size,
            "save_policy": config.understanding_save_policy,
        })
        # 懒加载注入 VisionService (用于截屏后理解)
        try:
            from backend.vision.service import get_service as _get_vision_service
            svc.set_vision_service(_get_vision_service())
        except Exception as e:
            logger.warning(f"VisionService 注入失败: {e}")
        # 懒加载注入 PerceptionService (用于感知上下文增强)
        try:
            from backend.vision.perception.service import get_service as _get_perception_service
            svc.set_perception_service(_get_perception_service())
        except Exception as e:
            logger.warning(f"PerceptionService 注入失败: {e}")
    return svc


@app.get("/understanding/status", summary="理解系统状态", description="获取 Understanding 子系统状态 (V1.0)")
async def understanding_status():
    try:
        svc = _get_understanding_service()
        return {"success": True, "status": svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/understanding/permission", summary="获取理解权限", description="获取当前 Understanding 权限配置")
async def understanding_get_permission():
    try:
        svc = _get_understanding_service()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/permission", summary="更新理解权限", description="字段级更新 Understanding 权限 (None=不修改)")
async def understanding_update_permission(payload: Dict[str, Any] = None):
    try:
        svc = _get_understanding_service()
        if payload is None:
            payload = {}
        updates = {k: v for k, v in payload.items() if v is not None}
        if updates:
            perm = svc.update_permission(**updates)
            return {"success": True, "permission": perm.to_dict()}
        return {"success": True, "permission": svc.get_permission(), "note": "无更新字段"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/reset-permission", summary="重置理解权限", description="重置为默认 (全部拒绝)")
async def understanding_reset_permission():
    try:
        svc = _get_understanding_service()
        svc.reset_permission()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/describe", summary="场景描述", description="对上传图片执行场景理解与描述 (V1.0)")
async def understanding_describe(
    file: UploadFile = File(...),
    language: str = Form("zh"),
    max_tokens: int = Form(512),
):
    """上传图片并执行场景描述"""
    try:
        import numpy as np
        import cv2

        contents = await file.read()
        img_array = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "无法解码图片"}

        svc = _get_understanding_service()
        result = svc.describe_scene(
            image=image,
            language=language,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/qa", summary="视觉问答", description="对上传图片提问并回答 (V1.0)")
async def understanding_qa(
    file: UploadFile = File(...),
    question: str = Form(...),
    language: str = Form("zh"),
    max_tokens: int = Form(512),
):
    """上传图片并执行视觉问答"""
    try:
        import numpy as np
        import cv2

        contents = await file.read()
        img_array = np.frombuffer(contents, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": "无法解码图片"}

        svc = _get_understanding_service()
        result = svc.answer_visual(
            image=image,
            question=question,
            language=language,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/screen/describe", summary="截屏场景描述", description="截取当前屏幕并描述场景 (需 screen + understanding 权限)")
async def understanding_screen_describe(
    region: Optional[str] = Form(None),         # JSON 字符串: {"x":0,"y":0,"w":100,"h":100}
    language: str = Form("zh"),
):
    """截屏并描述场景"""
    try:
        import json as _json
        svc = _get_understanding_service()
        region_dict = _json.loads(region) if region else None
        result = svc.capture_screen_and_understand(
            mode="describe",
            region=region_dict,
            language=language,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/understanding/screen/qa", summary="截屏视觉问答", description="截取当前屏幕并回答问题 (需 screen + understanding 权限)")
async def understanding_screen_qa(
    question: str = Form(...),
    region: Optional[str] = Form(None),
    language: str = Form("zh"),
):
    """截屏并视觉问答"""
    try:
        import json as _json
        svc = _get_understanding_service()
        region_dict = _json.loads(region) if region else None
        result = svc.capture_screen_and_understand(
            mode="qa",
            region=region_dict,
            language=language,
            question=question,
        )
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/understanding/adapters", summary="VLM Adapter 列表", description="列出所有 VLM Adapter")
async def understanding_list_adapters():
    try:
        svc = _get_understanding_service()
        return {
            "success": True,
            "adapters": svc.list_adapters(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/understanding/logs", summary="理解日志查询", description="查询理解处理日志")
async def understanding_logs(
    source: Optional[str] = None,
    adapter: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 100,
):
    try:
        svc = _get_understanding_service()
        return {
            "success": True,
            "logs": svc.get_logs(source=source, adapter=adapter, event=event, limit=limit),
            "stats": svc.get_log_stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/understanding/logs", summary="清空理解日志", description="清空所有理解处理日志")
async def understanding_clear_logs():
    try:
        svc = _get_understanding_service()
        n = svc.clear_logs()
        return {"success": True, "cleared": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== Vision Memory V1.0 ====================

def _get_vision_memory_service():
    """获取 MemoryService 单例 (按 config 自动加载权限)"""
    from backend.vision.memory.service import get_service
    svc = get_service(db_path=config.vision_memory_db_path)
    if not svc._initialized:
        svc.load_config({
            "vision_memory_enabled": config.vision_memory_enabled,
            "allow_raw_image_save": config.vision_memory_allow_raw_image_save,
            "default_importance": config.vision_memory_default_importance,
            "max_query_limit": config.vision_memory_max_query_limit,
            "db_path": config.vision_memory_db_path,
        })
    return svc


@app.get("/vision-memory/status", summary="视觉记忆状态", description="获取 Vision Memory 子系统状态 (V1.0)")
async def vision_memory_status():
    try:
        svc = _get_vision_memory_service()
        return {"success": True, "status": svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/vision-memory/permission", summary="获取记忆权限", description="获取当前 Vision Memory 权限配置")
async def vision_memory_get_permission():
    try:
        svc = _get_vision_memory_service()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/vision-memory/permission", summary="更新记忆权限", description="字段级更新 Vision Memory 权限 (None=不修改)")
async def vision_memory_update_permission(payload: Dict[str, Any] = None):
    try:
        svc = _get_vision_memory_service()
        if payload is None:
            payload = {}
        updates = {k: v for k, v in payload.items() if v is not None}
        if updates:
            perm = svc.update_permission(**updates)
            return {"success": True, "permission": perm.to_dict()}
        return {"success": True, "permission": svc.get_permission(), "note": "无更新字段"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/vision-memory/reset-permission", summary="重置记忆权限", description="重置为默认 (全部拒绝)")
async def vision_memory_reset_permission():
    try:
        svc = _get_vision_memory_service()
        svc.reset_permission()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/vision-memory/save", summary="保存视觉记忆", description="保存视觉记忆记录 (只记忆结构化结果, 禁止原始图像)")
async def vision_memory_save(payload: Dict[str, Any]):
    try:
        svc = _get_vision_memory_service()
        from backend.vision.memory.schema import VisualMemoryRecord
        if not payload:
            return {"success": False, "error": "缺少请求体"}
        if "understanding_result" in payload:
            from backend.vision.understanding.schema import UnderstandingResult
            result = UnderstandingResult.from_dict(payload["understanding_result"])
            res = svc.save_understanding_result(
                result,
                tags=payload.get("tags"),
                importance=payload.get("importance"),
            )
            return {"success": res.success, **res.to_dict()}
        record = VisualMemoryRecord.from_dict(payload)
        res = svc.save(record)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/vision-memory/query", summary="检索视觉记忆", description="按条件检索视觉记忆 (时间/场景/标签/关键词/重要程度)")
async def vision_memory_query(payload: Dict[str, Any] = None):
    try:
        svc = _get_vision_memory_service()
        from backend.vision.memory.schema import MemoryQuery
        payload = payload or {}
        if isinstance(payload.get("time_from"), (int, float)):
            payload["time_from"] = float(payload["time_from"])
        if isinstance(payload.get("time_to"), (int, float)):
            payload["time_to"] = float(payload["time_to"])
        query = MemoryQuery.from_dict(payload)
        res = svc.query(query)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/vision-memory/update", summary="更新视觉记忆", description="字段级更新记忆记录 (白名单字段)")
async def vision_memory_update(payload: Dict[str, Any] = None):
    try:
        svc = _get_vision_memory_service()
        payload = payload or {}
        memory_id = payload.pop("memory_id", None) or payload.pop("id", None)
        if not memory_id:
            return {"success": False, "error": "缺少 memory_id"}
        fields = {k: v for k, v in payload.items() if v is not None}
        if not fields:
            return {"success": False, "error": "无更新字段"}
        res = svc.update(memory_id, **fields)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/vision-memory/recent-context", summary="最近视觉上下文", description="生成最近视觉记忆上下文文本 (给 Agent 使用)")
async def vision_memory_recent_context(limit: int = 5):
    try:
        svc = _get_vision_memory_service()
        if limit <= 0:
            limit = 5
        context = svc.recent_visual_context(limit=min(limit, 50))
        return {"success": True, "context": context, "count": svc.count()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/vision-memory/logs", summary="记忆日志查询", description="查询视觉记忆操作日志")
async def vision_memory_logs(
    event: Optional[str] = None,
    action: Optional[str] = None,
    store: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    try:
        svc = _get_vision_memory_service()
        return {
            "success": True,
            "logs": svc.get_logs(event=event, action=action, store=store, status=status, limit=limit),
            "stats": svc.get_log_stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/vision-memory/logs", summary="清空记忆日志", description="清空所有视觉记忆操作日志")
async def vision_memory_clear_logs():
    try:
        svc = _get_vision_memory_service()
        n = svc.clear_logs()
        return {"success": True, "cleared": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/vision-memory/count", summary="记忆总数", description="当前视觉记忆记录总数")
async def vision_memory_count():
    try:
        svc = _get_vision_memory_service()
        return {"success": True, "count": svc.count()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/vision-memory/all", summary="清空视觉记忆", description="清空所有视觉记忆记录 (需权限)")
async def vision_memory_clear_all():
    try:
        svc = _get_vision_memory_service()
        res = svc.clear()
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/vision-memory/{memory_id}", summary="删除单条记忆", description="按 id 删除单条视觉记忆记录 (需权限)")
async def vision_memory_delete(memory_id: str):
    try:
        svc = _get_vision_memory_service()
        res = svc.delete(memory_id)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/vision-memory/{memory_id}", summary="获取单条记忆", description="按 id 获取单条视觉记忆记录 (需权限)")
async def vision_memory_get(memory_id: str):
    try:
        svc = _get_vision_memory_service()
        res = svc.retrieve(memory_id)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== Personality Engine V3.4 ====================

def _get_personality_service():
    """获取 PersonalityService 单例 (按 config 自动加载权限)"""
    from backend.personality.service import get_service
    svc = get_service(db_path=config.personality_db_path)
    if not svc._initialized:
        svc.load_config({
            "personality_enabled": config.personality_enabled,
            "allow_sensitive": config.personality_allow_sensitive,
            "max_profiles": config.personality_max_profiles,
            "db_path": config.personality_db_path,
        })
    return svc


@app.get("/personality/status", summary="人格引擎状态", description="获取 Personality Engine 子系统状态 (V3.4)")
async def personality_status():
    try:
        svc = _get_personality_service()
        return {"success": True, "status": svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/permission", summary="获取人格权限", description="获取当前 Personality Engine 权限配置")
async def personality_get_permission():
    try:
        svc = _get_personality_service()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/permission", summary="更新人格权限", description="字段级更新 Personality Engine 权限 (None=不修改)")
async def personality_update_permission(payload: Dict[str, Any] = None):
    try:
        svc = _get_personality_service()
        if payload is None:
            payload = {}
        updates = {k: v for k, v in payload.items() if v is not None}
        if updates:
            perm = svc.update_permission(**updates)
            return {"success": True, "permission": perm.to_dict()}
        return {"success": True, "permission": svc.get_permission(), "note": "无更新字段"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/reset-permission", summary="重置人格权限", description="重置为默认 (全部拒绝)")
async def personality_reset_permission():
    try:
        svc = _get_personality_service()
        svc.reset_permission()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/profiles", summary="保存人格档案", description="保存人格档案 (需权限, 敏感字段过滤, 数量上限)")
async def personality_save(payload: Dict[str, Any]):
    try:
        svc = _get_personality_service()
        from backend.personality.schema import PersonalityProfile
        if not payload:
            return {"success": False, "error": "缺少请求体"}
        profile = PersonalityProfile.from_dict(payload)
        res = svc.save(profile)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/profiles", summary="检索人格档案", description="按条件检索人格档案 (关键词/维度/活跃)")
async def personality_query(
    keyword: Optional[str] = None,
    active_only: bool = False,
    limit: int = 20,
    offset: int = 0,
):
    try:
        svc = _get_personality_service()
        from backend.personality.schema import PersonalityQuery
        query = PersonalityQuery(
            keyword=keyword, active_only=active_only,
            limit=min(limit, 100), offset=max(offset, 0),
        )
        res = svc.query(query)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.put("/personality/profiles/{profile_id}", summary="更新人格档案", description="字段级更新人格档案 (白名单字段)")
async def personality_update(profile_id: str, payload: Dict[str, Any] = None):
    try:
        svc = _get_personality_service()
        payload = payload or {}
        fields = {k: v for k, v in payload.items() if v is not None}
        if not fields:
            return {"success": False, "error": "无更新字段"}
        res = svc.update(profile_id, **fields)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/personality/profiles/{profile_id}", summary="删除人格档案", description="按 id 删除人格档案 (需权限)")
async def personality_delete(profile_id: str):
    try:
        svc = _get_personality_service()
        res = svc.delete(profile_id)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/profiles/{profile_id}", summary="获取单个人格档案", description="按 id 获取人格档案 (需权限)")
async def personality_get(profile_id: str):
    try:
        svc = _get_personality_service()
        res = svc.retrieve(profile_id)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/current", summary="加载当前人格", description="加载默认人格 (无活跃档案时创建默认人格并设为当前)")
async def personality_load_default():
    try:
        svc = _get_personality_service()
        res = svc.load_default()
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/current", summary="获取当前人格", description="获取当前活跃人格档案")
async def personality_get_current():
    try:
        svc = _get_personality_service()
        res = svc.get_current_profile()
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/current/{profile_id}", summary="切换当前人格", description="切换当前人格 (置 active, 其他档案取消 active)")
async def personality_switch(profile_id: str):
    try:
        svc = _get_personality_service()
        res = svc.switch_profile(profile_id)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/style", summary="生成人格风格指令", description="生成当前人格的风格指令文本 (供 LLM 使用)")
async def personality_style():
    try:
        svc = _get_personality_service()
        res = svc.personality_style()
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/personality/assess", summary="一致性评估", description="评估文本与当前人格的一致性 (0.0 ~ 1.0)")
async def personality_assess(payload: Dict[str, Any] = None):
    try:
        svc = _get_personality_service()
        payload = payload or {}
        text = payload.get("text", "")
        res = svc.assess_consistency(text)
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/context", summary="人格上下文", description="生成人格上下文文本 (供 LLM System Prompt, 无权限返回空串)")
async def personality_context():
    try:
        svc = _get_personality_service()
        context = svc.build_persona_context()
        return {"success": True, "context": context}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/logs", summary="人格日志查询", description="查询人格操作日志")
async def personality_logs(
    event: Optional[str] = None,
    action: Optional[str] = None,
    store: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    try:
        svc = _get_personality_service()
        return {
            "success": True,
            "logs": svc.get_logs(event=event, action=action, store=store, status=status, limit=limit),
            "stats": svc.get_log_stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/personality/logs", summary="清空人格日志", description="清空所有人格操作日志")
async def personality_clear_logs():
    try:
        svc = _get_personality_service()
        n = svc.clear_logs()
        return {"success": True, "cleared": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/personality/count", summary="人格档案总数", description="当前人格档案记录总数")
async def personality_count():
    try:
        svc = _get_personality_service()
        return {"success": True, "count": svc.count()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/personality/all", summary="清空人格档案", description="清空所有人格档案记录 (需权限)")
async def personality_clear_all():
    try:
        svc = _get_personality_service()
        res = svc.clear()
        return {"success": res.success, **res.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== Vision Action V1.0 ====================

def _get_action_service():
    """获取 ActionService 单例 (按 config 自动加载权限)"""
    from backend.action.service import get_service
    svc = get_service()
    if not svc._initialized:
        svc.load_config({
            "action_enabled": config.action_enabled,
            "require_confirm_high_risk": config.action_require_confirm_high_risk,
        })
    return svc


@app.get("/action/status", summary="行动系统状态", description="获取 Vision Action 子系统状态 (V1.0)")
async def action_status():
    try:
        svc = _get_action_service()
        return {"success": True, "status": svc.status()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/action/permission", summary="获取行动权限", description="获取当前 Vision Action 权限配置")
async def action_get_permission():
    try:
        svc = _get_action_service()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/action/permission", summary="更新行动权限", description="字段级更新 Vision Action 权限 (None=不修改)")
async def action_update_permission(payload: Dict[str, Any] = None):
    try:
        svc = _get_action_service()
        if payload is None:
            payload = {}
        updates = {k: v for k, v in payload.items() if v is not None}
        if updates:
            cfg = svc.update_permission(**updates)
            return {"success": True, "permission": cfg.to_dict()}
        return {"success": True, "permission": svc.get_permission(), "note": "无更新字段"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/action/reset-permission", summary="重置行动权限", description="重置为默认 (全部拒绝)")
async def action_reset_permission():
    try:
        svc = _get_action_service()
        svc.reset_permission()
        return {"success": True, "permission": svc.get_permission()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/action/request", summary="提交行动请求", description="提交行动请求 (权限检查 → 风险评估 → 执行; 高风险需 confirmed=true)")
async def action_request(payload: Dict[str, Any]):
    try:
        svc = _get_action_service()
        from backend.action.schema import ActionRequest
        if not payload:
            return {"success": False, "error": "缺少请求体"}
        request = ActionRequest.from_dict(payload)
        confirmed = bool(payload.get("confirmed", False))
        op = svc.execute(request, confirmed=confirmed)
        return {"success": op.success, **op.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/action/status/{action_id}", summary="查询行动状态", description="按 action_id 查询行动状态 (从历史记录)")
async def action_status_detail(action_id: str):
    try:
        svc = _get_action_service()
        result = svc.get_status(action_id)
        if result is None:
            return {"success": False, "status": "not_found", "error": f"行动不存在: {action_id}"}
        return {"success": True, "result": result.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/action/{action_id}/cancel", summary="取消行动", description="取消行动 (路由到执行器)")
async def action_cancel(action_id: str):
    try:
        svc = _get_action_service()
        op = svc.cancel(action_id)
        return {"success": op.success, **op.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/action/history", summary="行动历史", description="检索历史行动记录 (状态过滤, 最新在前)")
async def action_history(
    status: Optional[str] = None,
    limit: int = 50,
):
    try:
        svc = _get_action_service()
        from backend.action.schema import ActionQuery
        records = svc.history(ActionQuery(status=status, limit=min(limit, 200)))
        return {"success": True, "records": records, "count": len(records)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/action/metrics", summary="行动指标", description="行动性能指标 (action_count / success_rate / approval_rate / execution_latency / failure_rate)")
async def action_metrics():
    try:
        svc = _get_action_service()
        return {"success": True, "metrics": svc.get_log_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/action/logs", summary="行动日志查询", description="查询行动操作日志")
async def action_logs(
    event: Optional[str] = None,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
):
    try:
        svc = _get_action_service()
        return {
            "success": True,
            "logs": svc.get_logs(event=event, action_type=action_type, status=status, limit=limit),
            "stats": svc.get_log_stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/action/logs", summary="清空行动日志", description="清空所有行动操作日志")
async def action_clear_logs():
    try:
        svc = _get_action_service()
        n = svc.clear_logs()
        return {"success": True, "cleared": n}
    except Exception as e:
        return {"success": False, "error": str(e)}


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