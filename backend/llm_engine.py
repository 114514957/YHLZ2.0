"""
YHLZ 2.0 LLM引擎模块
基于DeepSeek/阿里云通义千问，支持流式输出和多模态视觉输入
优化目标：低延迟、实时响应、预热机制、缓存策略
"""

import asyncio
import logging
import sys
import base64
import hashlib
import json
import time
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Optional, Union
from functools import lru_cache
from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI
from backend.config import config

logger = logging.getLogger(__name__)


class LLMEngine:
    """LLM引擎 - 支持低延迟流式输出和缓存策略"""
    
    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.is_connected = False
        self.provider = config.api_provider
        self._init_client()
        self.stream_buffer = ""
        self.flush_threshold = 1  # 每收到1个字符就立即输出（最低延迟）
        
        # 缓存机制
        self._response_cache = OrderedDict()
        self._cache_max_size = 1000
        self._cache_ttl = 300  # 缓存有效期（秒）
        self._cache_enabled = True
        
        # 统计信息
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_requests = 0
    
    def _init_client(self):
        """初始化API客户端"""
        if not config.is_valid:
            logger.warning(f"{config.api_provider} API Key未配置，LLM引擎将使用离线模式")
            return
        
        try:
            if config.api_provider == "dashscope":
                self.client = AsyncOpenAI(
                    api_key=config.dashscope_api_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
                self.is_connected = True
                logger.info(f"阿里云通义千问 API连接成功，模型: {config.dashscope_model}")
            else:
                self.client = AsyncOpenAI(
                    api_key=config.deepseek_api_key,
                    base_url=config.deepseek_base_url
                )
                self.is_connected = True
                logger.info(f"DeepSeek API连接成功，模型: {config.deepseek_model}")
            
            # 预热标记（在第一次使用时进行预热）
            self._needs_warmup = True
            
        except Exception as e:
            logger.error(f"API连接失败: {e}")
            self.is_connected = False
    
    def _generate_cache_key(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> str:
        """生成缓存键"""
        key_str = json.dumps(messages, sort_keys=True) + f"_{temperature}_{max_tokens}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached_response(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int) -> Optional[str]:
        """获取缓存的响应"""
        if not self._cache_enabled:
            return None
        
        cache_key = self._generate_cache_key(messages, temperature, max_tokens)
        
        if cache_key in self._response_cache:
            entry = self._response_cache[cache_key]
            now = time.time()
            
            if now - entry['timestamp'] < self._cache_ttl:
                self._cache_hits += 1
                self._response_cache.move_to_end(cache_key)
                logger.debug(f"缓存命中: {cache_key[:8]}")
                return entry['response']
            else:
                del self._response_cache[cache_key]
        
        self._cache_misses += 1
        return None
    
    def _set_cached_response(self, messages: List[Dict[str, str]], temperature: float, max_tokens: int, response: str):
        """设置缓存响应"""
        if not self._cache_enabled:
            return
        
        cache_key = self._generate_cache_key(messages, temperature, max_tokens)
        
        if len(self._response_cache) >= self._cache_max_size:
            self._response_cache.popitem(last=False)
        
        self._response_cache[cache_key] = {
            'response': response,
            'timestamp': time.time()
        }
    
    def clear_cache(self):
        """清空缓存"""
        self._response_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.info("LLM缓存已清空")
    
    def set_cache_enabled(self, enabled: bool):
        """启用/禁用缓存"""
        self._cache_enabled = enabled
        logger.info(f"LLM缓存 {'已启用' if enabled else '已禁用'}")
    
    def set_cache_size(self, size: int):
        """设置缓存大小"""
        self._cache_max_size = size
    
    def set_cache_ttl(self, ttl: int):
        """设置缓存TTL（秒）"""
        self._cache_ttl = ttl
    
    def get_cache_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        return {
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'total': self._total_requests,
            'hit_rate': round(self._cache_hits / max(self._total_requests, 1) * 100, 2),
            'cache_size': len(self._response_cache)
        }
    
    async def _warmup(self):
        """预热API连接，避免首次请求延迟"""
        if not self.is_connected or not self.client:
            return
        
        try:
            logger.info("正在预热LLM引擎...")
            # 发送一个简短的预热请求
            await self.client.chat.completions.create(
                model=config.dashscope_model if config.api_provider == "dashscope" else config.deepseek_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
                stream=False
            )
            logger.info("LLM引擎预热完成")
            self._needs_warmup = False
        except Exception as e:
            logger.warning(f"LLM预热失败（不影响使用）: {e}")
    
    async def check_connection(self) -> bool:
        """检查API连接状态"""
        if not self.client:
            return False
        
        try:
            await asyncio.wait_for(
                self.client.models.list(),
                timeout=5.0
            )
            return True
        except Exception as e:
            logger.warning(f"API连接检查失败: {e}")
            self.is_connected = False
            return False
    
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        flush_threshold: int = 1  # 低延迟模式：每1个token就输出
    ) -> AsyncGenerator[str, None]:
        """
        低延迟流式生成回复
        
        Args:
            messages: 对话历史
            temperature: 温度参数
            max_tokens: 最大token数
            flush_threshold: 刷新阈值，越小延迟越低
        
        Yields:
            生成的文本片段（低延迟模式下每次yield单个字符）
        """
        if not self.is_connected or not self.client:
            logger.warning("LLM引擎离线，使用离线回复")
            async for chunk in self._get_offline_response():
                yield chunk
            return
        
        # 第一次使用时进行预热
        if hasattr(self, '_needs_warmup') and self._needs_warmup:
            await self._warmup()
        
        try:
            logger.info(f"开始LLM流式生成，提供商: {config.api_provider}，消息数: {len(messages)}")
            
            model = config.dashscope_model if config.api_provider == "dashscope" else config.deepseek_model
            
            # 打印请求的完整参数
            logger.info(f"请求参数：model={model}, temperature={temperature}, max_tokens={max_tokens}")
            
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": False}  # 减少元数据传输
            )
            
            full_response = ""
            buffer = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    buffer += content
                    full_response += content
                    
                    # 低延迟模式：立即输出
                    while len(buffer) >= flush_threshold:
                        yield buffer[:flush_threshold]
                        buffer = buffer[flush_threshold:]
            
            # 输出剩余内容
            if buffer:
                yield buffer
            
            logger.info(f"LLM流式生成完成，完整回复: {full_response[:200]}...")
            
        except Exception as e:
            logger.error(f"LLM生成失败: {e}")
            async for chunk in self._get_offline_response():
                yield chunk
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        use_cache: bool = True
    ) -> str:
        """一次性生成完整回复（支持缓存）"""
        self._total_requests += 1
        
        if use_cache:
            cached_response = self._get_cached_response(messages, temperature, max_tokens)
            if cached_response is not None:
                logger.info(f"使用缓存响应，长度: {len(cached_response)}")
                return cached_response
        
        full_response = ""
        async for chunk in self.generate_stream(messages, temperature, max_tokens):
            full_response += chunk
        
        if use_cache and full_response and not self._get_cached_response(messages, temperature, max_tokens):
            self._set_cached_response(messages, temperature, max_tokens, full_response)
        
        return full_response

    async def generate_with_image(
        self,
        prompt: str,
        image_base64: str,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> str:
        """
        使用多模态模型分析图像并生成回复
        
        Args:
            prompt: 用户问题/提示
            image_base64: Base64编码的图像数据
            temperature: 温度参数
            max_tokens: 最大token数
        
        Returns:
            模型回复文本
        """
        if not self.is_connected or not self.client:
            logger.warning("LLM引擎离线，使用离线回复")
            return "抱歉，我现在处于离线状态，无法分析图像。"

        try:
            model = config.vl_model
            logger.info(f"开始多模态图像分析，模型: {model}")

            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]

            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False
            )

            result = response.choices[0].message.content.strip()
            logger.info(f"多模态分析完成，回复长度: {len(result)}")
            return result

        except Exception as e:
            logger.error(f"多模态图像分析失败: {e}")
            return f"图像分析失败: {e}"

    async def generate_stream_with_image(
        self,
        prompt: str,
        image_base64: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        flush_threshold: int = 1
    ) -> AsyncGenerator[str, None]:
        """
        使用多模态模型分析图像并流式生成回复
        
        Args:
            prompt: 用户问题/提示
            image_base64: Base64编码的图像数据
            temperature: 温度参数
            max_tokens: 最大token数
            flush_threshold: 刷新阈值
        
        Yields:
            生成的文本片段
        """
        if not self.is_connected or not self.client:
            logger.warning("LLM引擎离线，使用离线回复")
            async for chunk in self._get_offline_response():
                yield chunk
            return

        try:
            model = config.vl_model
            logger.info(f"开始多模态图像分析(流式)，模型: {model}")

            content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]

            stream = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": False}
            )

            full_response = ""
            buffer = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    buffer += content
                    full_response += content

                    while len(buffer) >= flush_threshold:
                        yield buffer[:flush_threshold]
                        buffer = buffer[flush_threshold:]

            if buffer:
                yield buffer

            logger.info(f"多模态流式分析完成，回复长度: {len(full_response)}")

        except Exception as e:
            logger.error(f"多模态图像分析失败: {e}")
            async for chunk in self._get_offline_response():
                yield chunk
    
    async def _get_offline_response(self) -> AsyncGenerator[str, None]:
        """离线模式回复"""
        offline_responses = [
            "抱歉，我现在处于离线状态。请检查您的网络连接。",
            "网络似乎不太稳定，我暂时无法连接到服务器。",
            "很抱歉，我暂时无法访问云端大脑。请稍后再试。"
        ]
        
        import random
        response = random.choice(offline_responses)
        
        for char in response:
            yield char
            await asyncio.sleep(0.01)


# 全局LLM引擎实例
llm_engine = LLMEngine()
