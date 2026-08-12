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

# 默认 voice_identity（M0.4：替代 character.yaml，单一角色载体扩展）
DEFAULT_VOICE_IDENTITY = {
    "voice_id": "default",
    "engine": "qwen3"
}

# 默认性格配置（原 personality.py 内联）
DEFAULT_PERSONALITY_CONFIG = {
    "name": "元亨",
    "role": "铁哥们",
    "traits": ["义气", "随和", "爽快"],
    "tone": "兄弟腔",
    "language": "中文",
    "description": "元亨是用户的铁哥们, 说话随意亲切, 像兄弟一样相处",
    "voice_identity": DEFAULT_VOICE_IDENTITY.copy()
}

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
PERSONALITY_CONFIG_FILE = DATA_DIR / "personality.json"


class ContextManager:
    """上下文管理器 - 支持上下文缓存"""
    
    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.summary: Optional[str] = None
        # V10.1.8: 压缩缓冲 (溢出消息累积 4 条触发一次工作摘要)
        self._compress_buffer: List[Dict[str, str]] = []
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
        """加载性格配置（M0.4：向后兼容旧 json，自动回填 voice_identity 默认值）"""
        try:
            if PERSONALITY_CONFIG_FILE.exists():
                with open(PERSONALITY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                # M0.4 兼容旧角色：缺 voice_identity 字段时回填默认值（不写盘，仅内存补全）
                if "voice_identity" not in cfg or not isinstance(cfg["voice_identity"], dict):
                    cfg["voice_identity"] = DEFAULT_VOICE_IDENTITY.copy()
                else:
                    # 字段级补全：voice_id / engine 任一缺失则回填
                    vi = cfg["voice_identity"]
                    if not vi.get("voice_id"):
                        vi["voice_id"] = DEFAULT_VOICE_IDENTITY["voice_id"]
                    if not vi.get("engine"):
                        vi["engine"] = DEFAULT_VOICE_IDENTITY["engine"]
                return cfg
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
        name = cfg.get("name", DEFAULT_PERSONALITY_CONFIG["name"])
        role = cfg.get("role", DEFAULT_PERSONALITY_CONFIG["role"])
        traits = "、".join(cfg.get("traits", DEFAULT_PERSONALITY_CONFIG["traits"]))
        tone = cfg.get("tone", DEFAULT_PERSONALITY_CONFIG["tone"])
        desc = cfg.get("description", DEFAULT_PERSONALITY_CONFIG["description"])
        return (
            f"你是{name}，用户的{role}。\n"
            f"性格特点：{traits}。\n"
            f"语气：{tone}。\n"
            f"{desc}\n"
            "请用简洁、自然的中文回复用户。"
        )

    def _get_personality_config(self):
        """获取性格配置"""
        return self._load_personality_config()

    def _update_personality(self, **kwargs):
        """更新性格配置（M0.4：voice_identity 单独处理，避免整对象覆盖误伤）"""
        cfg = self._load_personality_config()
        # voice_identity 走字段级 merge，避免传错对象导致 voice_id/engine 丢失
        if "voice_identity" in kwargs and isinstance(kwargs["voice_identity"], dict):
            new_vi = dict(cfg.get("voice_identity", DEFAULT_VOICE_IDENTITY))
            new_vi.update(kwargs.pop("voice_identity"))
            # 校验：合并后必须含 voice_id/engine，缺失回填默认
            if not new_vi.get("voice_id"):
                new_vi["voice_id"] = DEFAULT_VOICE_IDENTITY["voice_id"]
            if not new_vi.get("engine"):
                new_vi["engine"] = DEFAULT_VOICE_IDENTITY["engine"]
            cfg["voice_identity"] = new_vi
        # 其余字段直接 update
        cfg.update(kwargs)
        self._save_personality_config(cfg)
        logger.info(f"性格配置已更新: {kwargs}")

    def _reset_personality(self):
        """重置性格配置"""
        self._save_personality_config(DEFAULT_PERSONALITY_CONFIG.copy())
        logger.info("性格配置已重置为默认值")

    # ── Voice Identity（M0.4：personality.json 单源扩展，替代 character.yaml）──
    def _get_voice_identity(self) -> dict:
        """获取当前角色的 voice_identity（始终返回完整 dict，含 voice_id + engine）"""
        cfg = self._load_personality_config()
        return cfg.get("voice_identity", DEFAULT_VOICE_IDENTITY.copy())

    def _update_voice_identity(self, voice_id: str = None, engine: str = None) -> dict:
        """更新 voice_identity 字段（字段级 merge，None 表示不修改）"""
        vi = self._get_voice_identity()
        if voice_id is not None:
            vi["voice_id"] = voice_id
        if engine is not None:
            vi["engine"] = engine
        # 走 _update_personality 的字段级 merge 路径，确保持久化与校验
        self._update_personality(voice_identity=vi)
        # 重新读取, 返回经过 _update_personality 校验回填后的真实持久化值
        # (防止传入空字符串等 falsy 值时, 返回未校验的中间态)
        persisted = self._get_voice_identity()
        logger.info(f"voice_identity 已更新: {persisted}")
        return persisted

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
        添加消息到历史 (V10.1.8: 短期窗口 8 条 ~4轮, 超窗压缩)
        
        Args:
            role: 角色 ('user' 或 'assistant')
            content: 消息内容
        """
        self.history.append({
            "role": role,
            "content": content
        })
        # V10.1.8 短期窗口: 最多 8 条消息 (~4轮完整对话)
        MAX_HISTORY_MESSAGES = 8
        if len(self.history) > MAX_HISTORY_MESSAGES:
            # 超窗: 溢出消息进入压缩缓冲 (累积 4 条触发一次压缩)
            overflow = self.history[:-MAX_HISTORY_MESSAGES]
            self.history = self.history[-MAX_HISTORY_MESSAGES:]
            self._compress_buffer.extend(overflow)
            if len(self._compress_buffer) >= 4:
                batch = self._compress_buffer
                self._compress_buffer = []
                self._compress_to_working_summary(batch)
        
        # 更新token数（精确计算）
        self._update_token_count()
        
        # 检查是否需要摘要
        if self.token_count >= self.summary_threshold:
            logger.info(f"Token数: {self.token_count}，触发自动摘要")
            # 使用异步任务生成摘要，不阻塞主线程
            import asyncio
            asyncio.create_task(self._generate_summary())

    def _compress_to_working_summary(self, messages: list) -> None:
        """V10.1.8 对话压缩: 超窗消息转工作摘要 (规则提取)

        保留: 用户目标 / 当前任务 / 已确认结论 / 未完成事项 / 关键实体
        """
        if not messages:
            return
        try:
            goals = []
            tasks = []
            conclusions = []
            todos = []
            entities = []
            for msg in messages:
                content = str(msg.get("content", ""))
                if not content:
                    continue
                for kw in ("目标", "想", "要", "希望", "打算"):
                    if kw in content and len(content) < 200:
                        goals.append(content[:120])
                        break
                for kw in ("任务", "完成", "处理", "实现"):
                    if kw in content:
                        tasks.append(content[:120])
                        break
                if msg.get("role") == "assistant" and \
                        any(k in content for k in
                            ("结论", "所以", "因此", "确定", "确认")):
                    conclusions.append(content[:150])
                if any(k in content for k in
                       ("待", "未完成", "下一步", "还需要")):
                    todos.append(content[:100])
                for kw in ("项目", "系统", "模块", "配置"):
                    if kw in content:
                        entities.append(content[:80])
                        break
            lines = []
            if goals:
                lines.append("用户目标: " + " | ".join(
                    list(dict.fromkeys(goals))[:3]))
            if tasks:
                lines.append("当前任务: " + " | ".join(
                    list(dict.fromkeys(tasks))[:3]))
            if conclusions:
                lines.append("已确认结论: " + " | ".join(
                    list(dict.fromkeys(conclusions))[:3]))
            if todos:
                lines.append("未完成事项: " + " | ".join(
                    list(dict.fromkeys(todos))[:3]))
            if entities:
                lines.append("关键实体: " + " | ".join(
                    list(dict.fromkeys(entities))[:3]))
            summary = "；".join(lines)
            if summary:
                self.summary = summary
                logger.info(f"[Context] 工作摘要已更新: {summary[:80]}")
        except Exception as e:
            logger.warning(f"[Context] 压缩失败: {e}")

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

    # Voice Identity 公共接口（M0.4：替代 character.yaml 双源真相）
    def get_voice_identity(self) -> dict:
        """获取当前角色的 voice_identity（含 voice_id + engine，缺省自动回填）"""
        return self._get_voice_identity()

    def update_voice_identity(self, voice_id: str = None, engine: str = None) -> dict:
        """更新 voice_identity（字段级 merge，None 表示不修改；持久化到 personality.json）"""
        return self._update_voice_identity(voice_id=voice_id, engine=engine)
    
    # 记忆管理接口（V3.0 委托给 backend.agent.memory 系统, 替代旧 stub）
    def _get_memory_manager(self):
        """惰性获取 Agent MemoryManager (避免循环导入)"""
        if not hasattr(self, "_agent_memory_mgr"):
            try:
                from backend.agent.memory import get_memory_manager
                self._agent_memory_mgr = get_memory_manager()
            except Exception as e:
                logger.warning(f"无法加载 agent.memory, 退化为 stub: {e}")
                self._agent_memory_mgr = None
        return self._agent_memory_mgr

    def add_memory(self, content: str, category: str = "general", 
                   importance: int = 1, related_topics: List[str] = None,
                   emotion_tag: str = None) -> str:
        """添加记忆 (V3.0 委托给 agent.memory)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return self._add_long_term_memory(
                content=content, category=category, importance=importance,
                related_topics=related_topics, emotion_tag=emotion_tag,
            )
        # category 映射: general → fact
        mem_category = "fact" if category == "general" else category
        if mem_category not in ("fact", "preference", "event", "dialogue", "skill"):
            mem_category = "fact"
        try:
            metadata = {"importance": importance, "related_topics": related_topics or [], "emotion_tag": emotion_tag}
            return mgr.add(content=content, category=mem_category, source="user", metadata=metadata)
        except Exception as e:
            logger.warning(f"agent.memory.add 失败, 退化为 stub: {e}")
            return self._add_long_term_memory(content=content, category=category)

    def search_memories(self, query: str, max_results: int = 5) -> List[Dict]:
        """搜索记忆 (V3.0 委托给 agent.memory)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return self._get_relevant_memories(query, limit=max_results)
        try:
            entries = mgr.search(query, limit=max_results)
            return [e.to_dict() for e in entries]
        except Exception as e:
            logger.warning(f"agent.memory.search 失败, 退化为 stub: {e}")
            return self._get_relevant_memories(query, limit=max_results)

    def get_all_memories(self) -> List[Dict]:
        """获取所有记忆 (V3.0 委托给 agent.memory)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return self._get_long_term_memories(limit=100)
        try:
            entries = mgr.list_all(limit=100)
            return [e.to_dict() for e in entries]
        except Exception as e:
            logger.warning(f"agent.memory.list 失败, 退化为 stub: {e}")
            return self._get_long_term_memories(limit=100)

    # V3.0: 向后兼容 main.py 的旧方法名 (add_long_term_memory / get_relevant_memories / get_long_term_memories)
    def add_long_term_memory(self, content: str, category: str = "general",
                             importance: int = 1, related_topics: List[str] = None,
                             emotion_tag: str = None) -> str:
        """向后兼容别名: 委托给 add_memory"""
        return self.add_memory(content=content, category=category, importance=importance,
                               related_topics=related_topics, emotion_tag=emotion_tag)

    def get_relevant_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """向后兼容别名: 委托给 search_memories"""
        return self.search_memories(query, max_results=limit)

    def get_long_term_memories(self, limit: int = 100) -> List[Dict]:
        """向后兼容别名: 委托给 get_all_memories"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return self._get_long_term_memories(limit=limit)
        try:
            entries = mgr.list_all(limit=limit)
            return [e.to_dict() for e in entries]
        except Exception as e:
            logger.warning(f"agent.memory.list 失败, 退化为 stub: {e}")
            return self._get_long_term_memories(limit=limit)

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆 (V3.0 新增)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return False
        try:
            return mgr.delete(memory_id)
        except Exception as e:
            logger.warning(f"agent.memory.delete 失败: {e}")
            return False

    def update_memory(self, memory_id: str, **fields) -> bool:
        """更新记忆 (V3.0 新增)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            return False
        try:
            return mgr.update(memory_id, **fields)
        except Exception as e:
            logger.warning(f"agent.memory.update 失败: {e}")
            return False
    
    def clear_all_memories(self):
        """清空所有记忆 (V3.0 委托给 agent.memory)"""
        mgr = self._get_memory_manager()
        if mgr is None:
            self._clear_all_memories()
            return
        try:
            mgr.clear()
        except Exception as e:
            logger.warning(f"agent.memory.clear 失败: {e}")
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