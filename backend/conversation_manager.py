"""
YHLZ 2.0 连续对话管理器
优化目标：流畅连续对话、上下文保持、打断机制、自然交互
支持：
- 多轮对话上下文管理
- 智能打断（边听边说）
- 话题追踪
- 对话状态管理
- 多模态输入（语音/文本/视觉）
"""

import asyncio
import logging
import json
from typing import List, Dict, Optional, Callable, Any
from enum import Enum
from collections import deque

from backend.config import config

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"


class ConversationManager:
    """连续对话管理器"""
    
    def __init__(self):
        self._state = ConversationState.IDLE
        self._history: deque = deque(maxlen=50)
        self._current_topic = ""
        self._topic_history = []
        self._is_interrupted = False
        self._interrupt_event = asyncio.Event()
        self._response_buffer = ""
        self._speaking_task = None
        
        self._asr_engine = None
        self._llm_engine = None
        self._tts_engine = None
        self._vad_engine = None
        self._audio_buffer = None
        
        self._on_state_change: Optional[Callable] = None
        self._on_message: Optional[Callable] = None
        
        self._init_fallback_llm()
        
        logger.info("连续对话管理器初始化完成")
    
    def _init_fallback_llm(self):
        """初始化回退LLM引擎"""
        try:
            from backend.llm_engine import llm_engine
            if llm_engine.is_connected:
                self._llm_engine = llm_engine
                logger.info("已连接LLM引擎")
            else:
                logger.info("LLM引擎未连接，使用本地回退模式")
        except Exception as e:
            logger.info(f"无法加载LLM引擎: {e}，使用本地回退模式")
    
    def set_engines(self, asr_engine=None, llm_engine=None, tts_engine=None, 
                    vad_engine=None, audio_buffer=None):
        """设置依赖引擎"""
        self._asr_engine = asr_engine
        self._llm_engine = llm_engine
        self._tts_engine = tts_engine
        self._vad_engine = vad_engine
        self._audio_buffer = audio_buffer
    
    def set_callbacks(self, on_state_change=None, on_message=None):
        """设置回调函数"""
        self._on_state_change = on_state_change
        self._on_message = on_message
    
    async def _notify_state_change(self, new_state: ConversationState):
        """通知状态变化（支持异步）"""
        if self._on_state_change:
            try:
                result = self._on_state_change(new_state.value)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"状态变化回调失败: {e}")
    
    async def _notify_message(self, message_type: str, content: str):
        """通知消息（支持异步）"""
        if self._on_message:
            try:
                result = self._on_message(message_type, content)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"消息回调失败: {e}")
    
    def get_state(self) -> str:
        """获取当前状态"""
        return self._state.value
    
    def get_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return list(self._history)
    
    def get_current_topic(self) -> str:
        """获取当前话题"""
        return self._current_topic
    
    def clear_history(self):
        """清空对话历史"""
        self._history.clear()
        self._current_topic = ""
        self._topic_history = []
        logger.info("对话历史已清空")
    
    async def interrupt(self):
        """打断当前对话"""
        self._is_interrupted = True
        self._interrupt_event.set()
        
        if self._audio_buffer:
            self._audio_buffer.interrupt()
        
        self._state = ConversationState.INTERRUPTED
        await self._notify_state_change(self._state)
        
        logger.info("对话已打断")
    
    async def handle_audio_input(self, audio_data: bytes, sample_rate: int = 16000):
        """处理音频输入（语音对话入口）"""
        # 蓝图1.5: 回声过滤 — 本机扬声器播放中的输入直接丢弃
        if self._is_self_echo():
            return
        
        self._state = ConversationState.LISTENING
        await self._notify_state_change(self._state)
        
        try:
            import numpy as np
            audio_np = np.frombuffer(audio_data, dtype=np.float32)
            
            if self._vad_engine:
                has_speech = self._vad_engine.detect_speech(audio_np, sample_rate)
                if not has_speech:
                    return
            
            if self._asr_engine:
                text = await asyncio.to_thread(
                    self._asr_engine.transcribe,
                    audio_np,
                    sample_rate
                )
                
                if text and text.strip():
                    await self.handle_text_input(text.strip())
        
        except Exception as e:
            logger.error(f"处理音频输入失败: {e}")
    
    async def handle_text_input(self, text: str):
        """处理文本输入"""
        if not text.strip():
            return
        
        # 蓝图1.5: 回声过滤 — 落在自播窗口内的输入视为AI自嗨, 丢弃
        if self._is_self_echo():
            logger.info(f"[回声过滤] 丢弃自播窗口内的输入: {text[:30]}...")
            return
        
        logger.info(f"收到输入: {text}")
        await self._notify_message("user", text)
        
        self._state = ConversationState.THINKING
        await self._notify_state_change(self._state)
        
        self._is_interrupted = False
        self._interrupt_event.clear()
        
        await self._process_dialogue(text)
    
    def _is_self_echo(self) -> bool:
        """检查当前输入是否落在本机自播窗口内 (蓝图1.5 回声过滤)"""
        if not config.echo_filter_enabled:
            return False
        if not self._audio_buffer:
            return False
        return self._audio_buffer.is_within_self_play_window()
    
    async def _process_dialogue(self, user_input: str):
        """处理完整对话流程"""
        try:
            await self._update_topic(user_input)
            
            self._history.append({
                "role": "user",
                "content": user_input
            })
            
            messages = self._build_messages()
            
            self._state = ConversationState.SPEAKING
            await self._notify_state_change(self._state)
            
            if not self._llm_engine:
                logger.info("LLM引擎未设置，使用本地回退模式")
                full_response = self._generate_fallback_response(user_input)
                
                await self._notify_message("assistant_chunk", full_response)
                await self._notify_message("assistant", full_response)
            else:
                full_response = ""
                
                async for chunk in self._llm_engine.generate_stream(messages):
                    if self._is_interrupted:
                        logger.info("对话被打断")
                        break
                    
                    full_response += chunk
                    await self._notify_message("assistant_chunk", chunk)
                    
                    if self._tts_engine and self._audio_buffer:
                        await self._synthesize_and_play(chunk)
            
            if full_response and not self._is_interrupted:
                self._history.append({
                    "role": "assistant",
                    "content": full_response
                })
            
            self._state = ConversationState.IDLE
            await self._notify_state_change(self._state)
        
        except Exception as e:
            logger.error(f"处理对话失败: {e}")
            self._state = ConversationState.IDLE
            await self._notify_state_change(self._state)
    
    def _generate_fallback_response(self, user_input: str) -> str:
        """生成本地回退响应"""
        import random
        
        greetings = ["嘿！", "哟！", "嗨！", "哥们儿！"]
        questions = ["哥们儿, 有啥事儿？", "哟, 来啦！咋了？", "嘿哥们, 说吧！"]

        user_lower = user_input.lower()

        if any(g in user_lower for g in ["你好", "hello", "hi", "嗨"]):
            return random.choice(greetings) + " 哥们儿, 有啥事儿？"

        elif any(q in user_lower for q in ["什么", "怎么", "为什么", "怎么样"]):
            return "这问题问得好！不过现在没连上大脑, 等连上了咱再聊。"

        elif any(q in user_lower for q in ["名字", "叫什么"]):
            return "我叫元亨, 你的铁哥们！"
        
        elif any(q in user_lower for q in ["天气", "温度"]):
            return "今天天气看起来不错！具体天气信息需要连接LLM服务后查询。"
        
        elif any(q in user_lower for q in ["再见", "拜拜", "bye"]):
            return "再见！祝你有美好的一天！"
        
        else:
            responses = [
                f"你说：{user_input}。我明白了！",
                f"收到！关于'{user_input}'这个话题，我很感兴趣。",
                f"我理解你的意思了。让我们继续聊聊吧！",
                f"{user_input}，这是一个有趣的话题。"
            ]
            return random.choice(responses)
    
    async def _synthesize_and_play(self, text: str):
        """合成语音并播放（流式）"""
        if not self._tts_engine or not self._audio_buffer:
            return
        
        try:
            async for audio_chunk, sr in self._tts_engine.stream_synthesize_text(text):
                if self._is_interrupted:
                    break
                if audio_chunk is not None:
                    self._audio_buffer.add_audio(audio_chunk, sr)
            # 蓝图1.3: 正常合成完成标记 done 哨兵
            if not self._is_interrupted:
                self._audio_buffer.mark_stream_done()
        except Exception as e:
            logger.error(f"语音合成失败: {e}")
    
    def _build_messages(self) -> List[Dict[str, str]]:
        """构建发送给LLM的消息列表"""
        messages = []
        
        system_prompt = self._build_system_prompt()
        messages.append({"role": "system", "content": system_prompt})
        
        messages.extend(list(self._history))
        
        return messages
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        prompt = """
你是一个智能AI助手，能够与人进行流畅的连续对话。

规则：
1. 保持对话连贯，记住之前的对话内容
2. 回答简洁自然，不要过于冗长
3. 如果用户问的是之前讨论过的话题，要记得上下文
4. 支持语音交互，回答要适合朗读
5. 如果被打断，请停止回答
6. 保持友好、专业的语气

当前话题：{}
""".strip()
        
        return prompt.format(self._current_topic)
    
    async def _update_topic(self, user_input: str):
        """更新当前话题"""
        keywords = self._extract_keywords(user_input)
        
        if keywords:
            self._current_topic = ", ".join(keywords[:3])
            
            if self._current_topic not in self._topic_history:
                self._topic_history.append(self._current_topic)
                if len(self._topic_history) > 10:
                    self._topic_history = self._topic_history[-10:]
            
            logger.info(f"当前话题: {self._current_topic}")
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简化版）"""
        keywords = []
        
        stop_words = {"的", "是", "在", "有", "和", "了", "我", "你", "他", "她", "它", "这", "那", "什么", "怎么", "为什么", "因为", "所以", "但是", "如果"}
        
        words = text.split()
        
        for word in words:
            clean_word = ''.join([c for c in word if c.isalpha() or c.isdigit()])
            if clean_word and len(clean_word) >= 2 and clean_word not in stop_words:
                keywords.append(clean_word)
        
        return keywords
    
    async def start_conversation(self):
        """开始对话模式"""
        logger.info("对话模式已启动")
        self._state = ConversationState.IDLE
        await self._notify_state_change(self._state)
    
    async def end_conversation(self):
        """结束对话模式"""
        await self.interrupt()
        self._state = ConversationState.IDLE
        await self._notify_state_change(self._state)
        logger.info("对话模式已结束")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取对话统计信息"""
        return {
            "state": self._state.value,
            "history_length": len(self._history),
            "current_topic": self._current_topic,
            "topic_history": self._topic_history,
            "is_interrupted": self._is_interrupted,
        }


conversation_manager = ConversationManager()