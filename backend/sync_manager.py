"""
YHLZ 2.0 多模态同步管理器
参考Lumi_Nox/Mio的毫秒级同步设计
统一管理语音、视觉、情感的时间戳同步
"""

import time
import logging
import asyncio
from typing import List, Dict, Any, Callable, Optional
from collections import deque

logger = logging.getLogger(__name__)


class SyncEvent:
    """同步事件"""
    
    def __init__(self, event_type: str, data: Dict[str, Any], timestamp: float = None):
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.processed = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.event_type,
            'data': self.data,
            'timestamp': self.timestamp,
            'processed': self.processed
        }


class SyncManager:
    """多模态同步管理器"""
    
    def __init__(self):
        self._events: deque = deque(maxlen=1000)
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._running = False
        self._process_task = None
        self._lock = asyncio.Lock()
        # 蓝图D6: WebSocket 广播客户端列表
        self._ws_clients: set = set()
        
        self._register_default_handlers()
        logger.info("多模态同步管理器初始化完成")
    
    def _register_default_handlers(self):
        """注册默认事件处理器"""
        self.register_handler('mouth_sync', self._handle_mouth_sync)
        self.register_handler('emotion_change', self._handle_emotion_change)
        self.register_handler('speech_start', self._handle_speech_start)
        self.register_handler('speech_end', self._handle_speech_end)
        self.register_handler('tts_chunk', self._handle_tts_chunk)
    
    def register_handler(self, event_type: str, handler: Callable):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 处理函数，接收event参数
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"注册事件处理器: {event_type}")
    
    def unregister_handler(self, event_type: str, handler: Callable):
        """
        注销事件处理器
        
        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type in self._event_handlers:
            self._event_handlers[event_type].remove(handler)
            logger.debug(f"注销事件处理器: {event_type}")
    
    def record_event(self, event_type: str, data: Dict[str, Any], timestamp: float = None):
        """
        记录同步事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            timestamp: 时间戳（可选，默认当前时间）
        """
        event = SyncEvent(event_type, data, timestamp)
        self._events.append(event)
        logger.debug(f"记录事件: {event_type} at {event.timestamp:.3f}")
        
        self._notify_handlers(event)
        # 蓝图D6: 广播到所有连接的桌面宠物客户端
        self._broadcast(event)
    
    def register_ws_client(self, ws):
        """蓝图D6: 注册 WebSocket 客户端"""
        self._ws_clients.add(ws)
        logger.info(f"WebSocket 客户端已注册 (总数: {len(self._ws_clients)})")
    
    def unregister_ws_client(self, ws):
        """蓝图D6: 注销 WebSocket 客户端"""
        self._ws_clients.discard(ws)
        logger.info(f"WebSocket 客户端已注销 (总数: {len(self._ws_clients)})")
    
    def _broadcast(self, event: SyncEvent):
        """蓝图D6: 广播事件到所有 WebSocket 客户端"""
        if not self._ws_clients:
            return
        import json
        msg = json.dumps(event.to_dict())
        dead_clients = set()
        for ws in list(self._ws_clients):
            try:
                asyncio.create_task(ws.send_text(msg))
            except Exception:
                dead_clients.add(ws)
        for ws in dead_clients:
            self._ws_clients.discard(ws)
    
    def _notify_handlers(self, event: SyncEvent):
        """通知所有注册的处理器"""
        if event.event_type in self._event_handlers:
            for handler in self._event_handlers[event.event_type]:
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as e:
                    logger.error(f"事件处理器错误 ({event.event_type}): {e}")
    
    def get_recent_events(self, event_type: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的事件
        
        Args:
            event_type: 事件类型（可选，返回所有类型）
            limit: 返回数量限制
            
        Returns:
            事件列表
        """
        events = list(self._events)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in events[-limit:]]
    
    def start(self):
        """启动同步管理器"""
        if self._running:
            return
        
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info("多模态同步管理器已启动")
    
    def stop(self):
        """停止同步管理器"""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None
        logger.info("多模态同步管理器已停止")
    
    async def _process_loop(self):
        """事件处理循环"""
        while self._running:
            try:
                async with self._lock:
                    while self._events:
                        event = self._events.popleft()
                        if not event.processed:
                            self._process_event(event)
                            event.processed = True
                
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"同步管理器循环错误: {e}")
    
    def _process_event(self, event: SyncEvent):
        """处理单个事件"""
        pass
    
    def _handle_mouth_sync(self, event: SyncEvent):
        """处理口型同步事件"""
        mouth_open = event.data.get('value', 0.0)
        logger.debug(f"口型同步: {mouth_open:.2f}")
    
    def _handle_emotion_change(self, event: SyncEvent):
        """处理情感变化事件"""
        emotion = event.data.get('emotion', 'neutral')
        intensity = event.data.get('intensity', 1.0)
        logger.debug(f"情感变化: {emotion} ({intensity:.2f})")
    
    def _handle_speech_start(self, event: SyncEvent):
        """处理语音开始事件"""
        logger.debug("语音开始")
    
    def _handle_speech_end(self, event: SyncEvent):
        """处理语音结束事件"""
        logger.debug("语音结束")
    
    def _handle_tts_chunk(self, event: SyncEvent):
        """处理TTS音频块事件"""
        audio_length = event.data.get('length', 0)
        logger.debug(f"TTS音频块: {audio_length} samples")
    
    def sync_emotion(self, emotion: str, intensity: float = 1.0):
        """
        同步情感状态
        
        Args:
            emotion: 情感类型
            intensity: 强度 (0-1)
        """
        self.record_event('emotion_change', {
            'emotion': emotion,
            'intensity': intensity
        })
    
    def sync_speech_start(self):
        """同步语音开始"""
        self.record_event('speech_start', {})
    
    def sync_speech_end(self):
        """同步语音结束"""
        self.record_event('speech_end', {})
    
    def sync_tts_chunk(self, audio_length: int):
        """
        同步TTS音频块
        
        Args:
            audio_length: 音频长度（样本数）
        """
        self.record_event('tts_chunk', {
            'length': audio_length
        })
    
    def get_status(self) -> Dict[str, Any]:
        """获取同步管理器状态"""
        return {
            'running': self._running,
            'event_count': len(self._events),
            'handler_count': {k: len(v) for k, v in self._event_handlers.items()}
        }


# 全局同步管理器实例
sync_manager = SyncManager()
