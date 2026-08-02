"""
YHLZ 2.0 上下文管理器
管理对话历史，自动摘要，防止Token溢出
集成性格设定和记忆库（内联实现，无外部依赖）
优化：高效Token计数 + 异步摘要 + 上下文缓存
"""

import logging
import hashlib
import json
from typing import List, Dict, Optional
import sys
from pathlib import Path
from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from .config import config

logger = logging.getLogger(__name__)

# 默认性格配置（原 personality.py 内联）
DEFAULT_PERSONALITY_CONFIG = {
    "name": "元亨",
    "role": "AI助手",
    "traits": ["友好", "专业", "乐于助人"],
    "tone": "温和",
    "language": "中文",
    "description": "元亨是一个友好的AI助手，专注于帮助用户解决问题"
}

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PERSONALITY_CONFIG_FILE = DATA_DIR / "personality.json"


class ContextManager:
    """上下文管理器 - 支持上下文缓存"""
    
    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.summary: Optional[str] = None
        self.max_history = config.max_context_tokens
        self.summary_threshold = config.summary_threshold
        self.token_count = 0
        
        # 初始化token编码器
        self._token_encoder = self._init_token_encoder()
        
        # 延迟加载依赖
        self._llm_engine = None
        
        # 上下文缓存
        self._context_cache = OrderedDict()
        self._cache_max_size = 100
        self._cache_enabled = True
    
    def _init_token_encoder(self):
        """初始化token编码器（用于精确计数）"""
        try:
            import tiktoken
            encoder = tiktoken.get_encoding("cl100k_base")
            logger.info("Token编码器初始化成功")
            return encoder
        except ImportError:
            logger.warning("tiktoken未安装，将使用字符估算")
            return None
    
    def _count_tokens(self, text: str) -> int:
        """计算文本的token数"""
        if self._token_encoder:
            return len(self._token_encoder.encode(text))
        else:
            # 简单估算：每个字符约0.5个token
            return int(len(text) * 0.5)
    
    def _get_llm_engine(self):
        """延迟加载LLM引擎"""
        if self._llm_engine is None:
            from .llm_engine import llm_engine
            self._llm_engine = llm_engine
        return self._llm_engine
    
    # ── 性格管理（内联，原 personality.py）──────────────────────────────
    def _load_personality_config(self) -> dict:
        """加载性格配置"""
        try:
            if PERSONALITY_CONFIG_FILE.exists():
                with open(PERSONALITY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"加载性格配置失败: {e}")
        return DEFAULT_PERSONALITY_CONFIG.copy()

    def _save_personality_config(self, cfg: dict):
        """保存性格配置"""
        try:
            with open(PERSONALITY_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存性格配置失败: {e}")

    def _get_system_prompt(self) -> str:
        """生成系统提示词"""
        cfg = self._load_personality_config()
        name = cfg.get("name", "元亨")
        role = cfg.get("role", "AI助手")
        traits = "、".join(cfg.get("traits", ["友好"]))
        tone = cfg.get("tone", "温和")
        desc = cfg.get("description", "")
        return (
            f"你是{name}，一个{role}。\n"
            f"性格特点：{traits}。\n"
            f"语气：{tone}。\n"
            f"{desc}\n"
            "请用简洁、自然的中文回复用户。"
        )

    def _get_personality_config(self):
        """获取性格配置"""
        return self._load_personality_config()

    def _update_personality(self, **kwargs):
        """更新性格配置"""
        cfg = self._load_personality_config()
        cfg.update(kwargs)
        self._save_personality_config(cfg)
        logger.info(f"性格配置已更新: {kwargs}")

    def _reset_personality(self):
        """重置性格配置"""
        self._save_personality_config(DEFAULT_PERSONALITY_CONFIG.copy())
        logger.info("性格配置已重置为默认值")

    # ── 记忆管理（内联，原 memory_v2.py 空壳）────────────────────────────
    def _extract_memory(self, user_message: str, ai_response: str):
        """提取对话记忆（Demo空壳）"""
        pass

    def _generate_memory_prompt(self, last_user_message: str) -> Optional[str]:
        """生成记忆提示（Demo空壳）"""
        return None

    def _add_long_term_memory(self, content: str, category: str = "general",
                              importance: int = 1, related_topics: List[str] = None,
                              emotion_tag: str = None) -> str:
        return "memory_stub"

    def _get_relevant_memories(self, query: str, limit: int = 5) -> List[Dict]:
        return []

    def _get_long_term_memories(self, limit: int = 100) -> List[Dict]:
        return []

    def _clear_all_memories(self):
        pass

    def _add_emotion_record(self, emotion: str, intensity: float, context: str = "", source: str = "user"):
        pass

    def _get_emotion_trend(self, hours: int = 24) -> Dict[str, float]:
        return {"neutral": 1.0}

    def _get_all_contacts(self) -> List[Dict]:
        return []

    def _get_contact(self, name: str) -> Optional[Dict]:
        return None

    def _get_full_context_dict(self) -> Dict:
        return {"personality": "friendly", "memories": [], "emotion_trend": {"neutral": 1.0}}
    
    def _generate_context_key(self, history: List[Dict[str, str]]) -> str:
        """生成上下文缓存键"""
        key_str = json.dumps(history, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached_context(self, history: List[Dict[str, str]]) -> Optional[str]:
        """获取缓存的摘要"""
        if not self._cache_enabled:
            return None
        
        cache_key = self._generate_context_key(history)
        
        if cache_key in self._context_cache:
            self._context_cache.move_to_end(cache_key)
            logger.debug(f"上下文缓存命中: {cache_key[:8]}")
            return self._context_cache[cache_key]
        
        return None
    
    def _set_cached_context(self, history: List[Dict[str, str]], summary: str):
        """设置上下文缓存"""
        if not self._cache_enabled:
            return
        
        cache_key = self._generate_context_key(history)
        
        if len(self._context_cache) >= self._cache_max_size:
            self._context_cache.popitem(last=False)
        
        self._context_cache[cache_key] = summary
    
    def clear_context_cache(self):
        """清空上下文缓存"""
        self._context_cache.clear()
        logger.info("上下文缓存已清空")
    
    def set_context_cache_enabled(self, enabled: bool):
        """启用/禁用上下文缓存"""
        self._cache_enabled = enabled
        logger.info(f"上下文缓存 {'已启用' if enabled else '已禁用'}")
    
    def add_message(self, role: str, content: str):
        """
        添加消息到历史
        
        Args:
            role: 角色 ('user' 或 'assistant')
            content: 消息内容
        """
        self.history.append({
            "role": role,
            "content": content
        })
        
        # 更新token数（精确计算）
        self._update_token_count()
        
        # 检查是否需要摘要
        if self.token_count >= self.summary_threshold:
            logger.info(f"Token数: {self.token_count}，触发自动摘要")
            # 使用异步任务生成摘要，不阻塞主线程
            import asyncio
            asyncio.create_task(self._generate_summary())
    
    def add_dialogue(self, user_message: str, ai_response: str):
        """
        添加完整对话（用户消息+AI回复）
        
        Args:
            user_message: 用户消息
            ai_response: AI回复
        """
        self.add_message("user", user_message)
        self.add_message("assistant", ai_response)
        
        # 自动提取记忆（异步执行，不阻塞）
        import asyncio
        asyncio.create_task(self._async_extract_memory(user_message, ai_response))
    
    async def _async_extract_memory(self, user_message: str, ai_response: str):
        """异步提取记忆"""
        try:
            self._extract_memory(user_message, ai_response)
            logger.info("对话记忆已自动提取")
        except Exception as e:
            logger.error(f"记忆提取失败: {e}")
    
    def get_context(self, recent_messages: int = 10) -> List[Dict[str, str]]:
        """
        获取上下文（包含性格设定和记忆）
        
        Args:
            recent_messages: 最近消息数量
        
        Returns:
            上下文消息列表
        """
        context = []
        
        # 添加性格设定（系统提示词）
        system_prompt = self._get_system_prompt()
        context.append({
            "role": "system",
            "content": system_prompt
        })
        
        # 添加记忆提示（如果有相关记忆）
        if self.history:
            last_user_message = self.history[-1]["content"] if self.history[-1]["role"] == "user" else ""
            memory_prompt = self._generate_memory_prompt(last_user_message)
            if memory_prompt:
                context.append({
                    "role": "system",
                    "content": memory_prompt
                })
        
        # 添加对话摘要（如果有）
        if self.summary:
            context.append({
                "role": "system",
                "content": f"对话摘要：{self.summary}"
            })
        
        # 添加最近的消息
        start_idx = max(0, len(self.history) - recent_messages)
        context.extend(self.history[start_idx:])
        
        return context
    
    async def _generate_summary(self):
        """
        生成对话摘要（异步）
        """
        if len(self.history) < 2:
            return
        
        try:
            logger.info("开始生成对话摘要")
            
            # 准备摘要请求
            history_text = "\n".join([
                f"{msg['role']}: {msg['content']}"
                for msg in self.history
            ])
            
            summary_prompt = f"""请为以下对话生成一个简洁的摘要（不超过100字）：

{history_text}

摘要："""
            
            messages = [
                {"role": "system", "content": "你是一个专业的对话摘要生成器。"},
                {"role": "user", "content": summary_prompt}
            ]
            
            # 生成摘要
            llm_engine = self._get_llm_engine()
            summary = await llm_engine.generate(
                messages,
                temperature=0.3,
                max_tokens=200
            )
            
            self.summary = summary.strip()
            logger.info(f"对话摘要生成完成: {self.summary}")
            
            # 清空历史，保留摘要
            self.history = []
            self._update_token_count()
            
        except Exception as e:
            logger.error(f"生成摘要失败: {e}")
    
    def _update_token_count(self):
        """更新token计数（精确计算）"""
        total_tokens = 0
        
        # 计算历史消息的token数
        for msg in self.history:
            total_tokens += self._count_tokens(msg["content"])
        
        # 计算摘要的token数
        if self.summary:
            total_tokens += self._count_tokens(self.summary)
        
        self.token_count = total_tokens
        logger.debug(f"当前Token数: {self.token_count}")
    
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.summary = None
        self.token_count = 0
        logger.info("对话历史已清空")
    
    def get_token_count(self) -> int:
        """获取当前token数"""
        return self.token_count
    
    def is_near_limit(self) -> bool:
        """检查是否接近token限制"""
        return self.token_count >= self.summary_threshold
    
    # 性格管理接口
    def get_personality_config(self):
        """获取性格配置"""
        return self._get_personality_config()
    
    def update_personality(self, **kwargs):
        """更新性格配置"""
        self._update_personality(**kwargs)
        logger.info(f"性格配置已更新: {kwargs}")
    
    def reset_personality(self):
        """重置性格配置"""
        self._reset_personality()
        logger.info("性格配置已重置")
    
    # 记忆管理接口（内联空壳实现）
    def add_memory(self, content: str, category: str = "general", 
                   importance: int = 1, related_topics: List[str] = None,
                   emotion_tag: str = None) -> str:
        """添加记忆"""
        return self._add_long_term_memory(
            content=content, 
            category=category, 
            importance=importance, 
            related_topics=related_topics,
            emotion_tag=emotion_tag
        )
    
    def search_memories(self, query: str, max_results: int = 5) -> List[Dict]:
        """搜索记忆"""
        return self._get_relevant_memories(query, limit=max_results)
    
    def get_all_memories(self) -> List[Dict]:
        """获取所有记忆"""
        return self._get_long_term_memories(limit=100)
    
    def clear_all_memories(self):
        """清空所有记忆"""
        self._clear_all_memories()
        logger.info("记忆库已清空")
    
    def add_emotion_record(self, emotion: str, intensity: float, context: str = "", source: str = "user"):
        """添加情感记录"""
        self._add_emotion_record(emotion, intensity, context, source)
    
    def get_emotion_trend(self, hours: int = 24) -> Dict[str, float]:
        """获取情感趋势"""
        return self._get_emotion_trend(hours)
    
    def get_contacts(self) -> List[Dict]:
        """获取所有联系人"""
        return self._get_all_contacts()
    
    def get_contact(self, name: str) -> Optional[Dict]:
        """获取联系人"""
        return self._get_contact(name)
    
    def get_full_context(self) -> Dict:
        """获取完整上下文（包含人格、记忆、情感）"""
        return self._get_full_context_dict()


# 全局上下文管理器实例
context_manager = ContextManager()