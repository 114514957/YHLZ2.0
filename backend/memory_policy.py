"""
YHLZ 2.0 显存策略与控制器 (M0.6)

目标环境: RTX 4060 Laptop 8GB
当前风险: Live 场景 (ASR + Qwen3-TTS 语音克隆 + 流式 TTS + ...) 显存占用约 7.5GB,
         接近 8GB 上限, 多模型同时驻留易 OOM。

设计:
- MemoryPolicy  : 声明式策略 (每类引擎的 can_coexist / vram 估算 / 冲突释放目标)
- MemoryController: 执行策略
    acquire(engine_type)  按策略释放冲突引擎 → 激活目标引擎
    release(engine_type)  释放指定引擎 GPU
    switch(to_engine)     模型切换 (release 冲突 + acquire 目标)
    can_acquire(engine_type) 预检 (策略 + 当前状态)
    get_snapshot()        torch.cuda 显存快照 (allocated/reserved/total)

策略示例 (任务要求):
    voice_engine:
        can_coexist: false   # 语音克隆引擎激活时, 必须释放 ASR

不直接接管 main.py 的引擎生命周期 (M0.6 为验证阶段); 提供可被上层调用的策略 API,
未来 V1 由 Voice Identity Manager / 服务编排层调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 引擎类型常量 ──────────────────────────────────────────────────────
ASR_ENGINE = "asr"
VOICE_TTS_ENGINE = "voice_engine"        # Qwen3-TTS 0.6B 语音克隆 (高显存)
STREAM_TTS_ENGINE = "stream_tts"         # faster-qwen3-tts CustomVoice (高显存)
LLM_ENGINE = "llm"                        # 云端, 不占本地显存


@dataclass
class EnginePolicy:
    """单类引擎的显存策略"""
    can_coexist: bool = True              # 是否允许与其他 GPU 引擎共存
    vram_estimate_gb: float = 0.0         # 显存估算 (GB), 用于预算检查
    release_on_conflict: List[str] = field(default_factory=list)  # 冲突时需释放的引擎类型

    def to_dict(self) -> dict:
        return {
            "can_coexist": self.can_coexist,
            "vram_estimate_gb": self.vram_estimate_gb,
            "release_on_conflict": list(self.release_on_conflict),
        }


# 默认策略 (基于 RTX 4060 Laptop 8GB 实测估算)
DEFAULT_POLICY: Dict[str, EnginePolicy] = {
    # ASR (SenseVoice-Small): ~1.5GB, 可与轻量 TTS 共存, 但不能与语音克隆引擎共存
    ASR_ENGINE: EnginePolicy(
        can_coexist=True,
        vram_estimate_gb=1.5,
        release_on_conflict=[],
    ),
    # 语音克隆引擎 (Qwen3-TTS 0.6B): ~3.0GB, 不能与其他 GPU 引擎共存 (Live 场景接近 OOM)
    VOICE_TTS_ENGINE: EnginePolicy(
        can_coexist=False,
        vram_estimate_gb=3.0,
        release_on_conflict=[ASR_ENGINE, STREAM_TTS_ENGINE],
    ),
    # 流式 TTS (faster-qwen3-tts CustomVoice + CUDA graph): ~3.5GB, 不能共存
    STREAM_TTS_ENGINE: EnginePolicy(
        can_coexist=False,
        vram_estimate_gb=3.5,
        release_on_conflict=[ASR_ENGINE, VOICE_TTS_ENGINE],
    ),
    # LLM: 云端, 不占本地显存
    LLM_ENGINE: EnginePolicy(
        can_coexist=True,
        vram_estimate_gb=0.0,
        release_on_conflict=[],
    ),
}


class MemoryPolicy:
    """显存策略集合 (声明式, 可从 dict 加载)"""

    def __init__(self, policies: Optional[Dict[str, EnginePolicy]] = None):
        self.policies: Dict[str, EnginePolicy] = dict(policies or DEFAULT_POLICY)

    def get(self, engine_type: str) -> EnginePolicy:
        """取策略; 未知引擎返回可共存空策略 (不阻塞)"""
        return self.policies.get(engine_type, EnginePolicy())

    def can_coexist_with(self, engine_type: str, other_types: List[str]) -> bool:
        """engine_type 是否可与 other_types 共存"""
        policy = self.get(engine_type)
        if not policy.can_coexist:
            # 不能共存: 检查 others 是否落在 release_on_conflict 内
            for other in other_types:
                if other in policy.release_on_conflict or other == engine_type:
                    return False
            return True
        # 可共存: 但若对方不能共存且把本引擎列为冲突, 仍判为不可共存
        for other in other_types:
            other_policy = self.get(other)
            if not other_policy.can_coexist and engine_type in other_policy.release_on_conflict:
                return False
        return True

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.policies.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryPolicy":
        policies: Dict[str, EnginePolicy] = {}
        for engine_type, entry in (d or {}).items():
            if isinstance(entry, EnginePolicy):
                policies[engine_type] = entry
                continue
            if isinstance(entry, dict):
                policies[engine_type] = EnginePolicy(
                    can_coexist=bool(entry.get("can_coexist", True)),
                    vram_estimate_gb=float(entry.get("vram_estimate_gb", 0.0)),
                    release_on_conflict=list(entry.get("release_on_conflict", [])),
                )
        return cls(policies)


class MemoryController:
    """显存控制器: 按 MemoryPolicy 执行引擎的获取/释放/切换

    上层通过 register_handler(engine_type, load_fn, release_fn) 注册每类引擎的
    实际加载/释放回调; controller 调用策略时回调这些函数。
    """

    def __init__(self, policy: Optional[MemoryPolicy] = None):
        self.policy = policy or MemoryPolicy()
        # engine_type -> (load_fn, release_fn)
        self._handlers: Dict[str, tuple] = {}
        # 当前已激活 (持有 GPU) 的引擎类型集合
        self._active: set = set()
        self._vram_total_gb: Optional[float] = self._detect_vram_total()

    # ------------------------------------------------------------------
    # 回调注册
    # ------------------------------------------------------------------
    def register_handler(
        self,
        engine_type: str,
        load_fn: Optional[Callable[[], bool]] = None,
        release_fn: Optional[Callable[[], None]] = None,
    ):
        """注册引擎的加载/释放回调

        load_fn:    无参, 返回 bool (是否加载成功)
        release_fn: 无参, 释放该引擎 GPU (如 unload / release_gpu)
        """
        self._handlers[engine_type] = (load_fn, release_fn)
        logger.debug(f"已注册显存处理器: {engine_type}")

    # ------------------------------------------------------------------
    # 策略执行
    # ------------------------------------------------------------------
    def can_acquire(self, engine_type: str) -> bool:
        """预检: 在当前已激活引擎集合下, 是否可获取 engine_type (不实际加载)"""
        policy = self.policy.get(engine_type)
        others = [e for e in self._active if e != engine_type]
        if not self.policy.can_coexist_with(engine_type, others):
            return False
        # 显存预算检查 (估算值, 仅预检)
        if self._vram_total_gb and policy.vram_estimate_gb > 0:
            used = sum(self.policy.get(e).vram_estimate_gb for e in self._active if e != engine_type)
            if used + policy.vram_estimate_gb > self._vram_total_gb:
                logger.warning(
                    f"显存预算超限: 已用 {used:.1f}GB + {engine_type} {policy.vram_estimate_gb:.1f}GB "
                    f"> 总量 {self._vram_total_gb:.1f}GB"
                )
                return False
        return True

    def _release_engine(self, engine_type: str):
        """释放单个引擎 (调用其 release_fn)"""
        handlers = self._handlers.get(engine_type)
        release_fn = handlers[1] if handlers else None
        if release_fn is not None:
            try:
                release_fn()
            except Exception as e:
                logger.error(f"释放引擎 {engine_type} 失败: {e}")
        self._active.discard(engine_type)
        logger.info(f"引擎 {engine_type} 已释放 GPU")

    def acquire(self, engine_type: str, force: bool = False) -> bool:
        """获取引擎: 按策略释放冲突引擎 → 加载目标引擎

        force: True 时即使预算超限也尝试 (策略冲突仍需释放)
        返回是否成功激活
        """
        policy = self.policy.get(engine_type)

        # 1) 释放冲突引擎 (双向检查: 任何与 engine_type 不可共存的已激活引擎都释放)
        #     不只看 engine_type 自身的 release_on_conflict, 也要看对方是否禁止共存
        for other in list(self._active):
            if other == engine_type:
                continue
            if not self.policy.can_coexist_with(engine_type, [other]):
                logger.info(f"策略释放冲突引擎: {other} (为 {engine_type} 让路)")
                self._release_engine(other)

        # 2) 预算预检 (force 可跳过)
        if not force and not self.can_acquire(engine_type):
            logger.warning(f"无法获取 {engine_type}: 策略/预算不允许")
            return False

        # 3) 加载目标引擎
        handlers = self._handlers.get(engine_type)
        load_fn = handlers[0] if handlers else None
        if load_fn is not None:
            try:
                ok = load_fn()
                if not ok:
                    logger.error(f"加载引擎 {engine_type} 失败 (load_fn 返回 False)")
                    return False
            except Exception as e:
                logger.error(f"加载引擎 {engine_type} 异常: {e}")
                return False
        self._active.add(engine_type)
        logger.info(f"引擎 {engine_type} 已激活 (当前持有 GPU: {sorted(self._active)})")
        return True

    def release(self, engine_type: str):
        """释放指定引擎 GPU"""
        if engine_type not in self._active:
            logger.debug(f"引擎 {engine_type} 未激活, 无需释放")
            return
        self._release_engine(engine_type)

    def switch(self, to_engine: str, force: bool = False) -> bool:
        """模型切换: 释放所有与 to_engine 冲突的引擎 → 激活 to_engine

        等价于 acquire, 但语义强调"切换主引擎", 会先释放 to_engine 的全部冲突目标。
        """
        logger.info(f"模型切换 → {to_engine}")
        return self.acquire(to_engine, force=force)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def active_engines(self) -> List[str]:
        return sorted(self._active)

    def is_active(self, engine_type: str) -> bool:
        return engine_type in self._active

    def get_snapshot(self) -> Dict[str, Any]:
        """显存快照: torch.cuda 状态 + 当前激活引擎 + 策略摘要"""
        snap: Dict[str, Any] = {
            "active_engines": self.active_engines,
            "vram_total_gb": self._vram_total_gb,
            "policy": self.policy.to_dict(),
        }
        cuda = self._cuda_snapshot()
        snap.update(cuda)
        return snap

    def _cuda_snapshot(self) -> Dict[str, float]:
        """torch.cuda 显存快照 (无 CUDA 时返回零值)"""
        try:
            import torch
            if not torch.cuda.is_available():
                return {"vram_allocated_gb": 0.0, "vram_reserved_gb": 0.0}
            return {
                "vram_allocated_gb": round(torch.cuda.memory_allocated(0) / (1024 ** 3), 3),
                "vram_reserved_gb": round(torch.cuda.memory_reserved(0) / (1024 ** 3), 3),
            }
        except Exception as e:
            logger.debug(f"获取 CUDA 快照失败: {e}")
            return {"vram_allocated_gb": 0.0, "vram_reserved_gb": 0.0}

    def _detect_vram_total(self) -> Optional[float]:
        """检测 GPU 总显存 (GB)"""
        try:
            import torch
            if not torch.cuda.is_available():
                return None
            return round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 2)
        except Exception:
            return None


# 全局单例 (供上层 import, 未注册 handler 时不影响现有代码)
memory_controller = MemoryController()
