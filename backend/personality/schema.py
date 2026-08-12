"""
YHLZ Personality Engine V3.4 - 人格层数据结构

职责:
    - 定义统一人格档案 (PersonalityProfile)
    - 检索条件 (PersonalityQuery)
    - 枚举: 人格维度 / 操作状态
    - 不依赖任何外部库 (仅 stdlib + typing)
    - 不依赖 Agent / Voice / Vision (自包含, 便于独立测试)

设计原则:
    - 不可变 (frozen dataclass)
    - 类型注解完整
    - 兼容 JSON 序列化 (to_dict / from_dict)
    - 人格数据独立存储 (绝不写入 Agent Memory)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------
# 枚举
# ----------------------------------------------------------------------

class PersonalityTrait(str, Enum):
    """人格维度"""
    FRIENDLINESS = "friendliness"      # 友好度
    HUMOR = "humor"                    # 幽默感
    RIGOR = "rigor"                    # 严谨度
    WARMTH = "warmth"                  # 热情度 / 温度
    CONCISENESS = "conciseness"        # 简洁度

    @classmethod
    def default_traits(cls) -> Dict[str, float]:
        """默认人格维度 (全 3.0, 中性)"""
        return {t.value: 3.0 for t in cls}


class PersonalityStatus(str, Enum):
    """人格操作状态"""
    OK = "ok"                          # 成功
    ERROR = "error"                    # 通用错误
    PERMISSION_DENIED = "denied"       # 权限拒绝
    NO_STORE = "no_store"              # 无可用存储
    EMPTY_INPUT = "empty_input"        # 输入为空
    NOT_FOUND = "not_found"            # 档案不存在
    INVALID = "invalid"                # 输入不合法 (敏感字段/分数越界)


# ----------------------------------------------------------------------
# 子结构
# ----------------------------------------------------------------------

@dataclass
class PersonalityPreferences:
    """互动偏好

    Attributes:
        address_user: 称呼用户方式 (如 '你' / '您')
        response_length: 回应长度偏好 (简洁 / 适中 / 详细)
        use_emojis: 是否使用表情符号
    """
    address_user: str = "你"
    response_length: str = "简洁"
    use_emojis: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address_user": self.address_user,
            "response_length": self.response_length,
            "use_emojis": self.use_emojis,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "PersonalityPreferences":
        if not d:
            return cls()
        return cls(
            address_user=str(d.get("address_user", "你")),
            response_length=str(d.get("response_length", "简洁")),
            use_emojis=bool(d.get("use_emojis", False)),
        )


# ----------------------------------------------------------------------
# 顶层档案
# ----------------------------------------------------------------------

@dataclass
class PersonalityProfile:
    """人格档案

    字段:
        profile_id:   档案唯一 ID
        name:         人格名称
        description:  人格描述
        traits:       人格维度 (friendliness / humor / rigor / warmth / conciseness, 0.0 ~ 5.0)
        tone:         说话风格 (语气 / 用词 / 句式)
        preferences:  互动偏好
        guidelines:   行为准则 (该做什么 / 不该做什么)
        active:       是否活跃
        created_at:   创建时间
        updated_at:   更新时间
    """
    profile_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "YHLZ 默认人格"
    description: str = ""
    traits: Dict[str, float] = field(default_factory=PersonalityTrait.default_traits)
    tone: str = ""
    preferences: PersonalityPreferences = field(default_factory=PersonalityPreferences)
    guidelines: List[str] = field(default_factory=list)
    active: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ── 序列化 ──────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        """转 dict"""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "description": self.description,
            "traits": {k: round(v, 2) for k, v in self.traits.items()},
            "tone": self.tone,
            "preferences": self.preferences.to_dict(),
            "guidelines": self.guidelines,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonalityProfile":
        """从 dict 构造"""
        now = time.time()
        traits = dict(d.get("traits", {}))
        # 保证全部维度存在 (缺失补默认 3.0)
        for t in PersonalityTrait:
            traits.setdefault(t.value, 3.0)
        return cls(
            profile_id=d.get("profile_id", uuid.uuid4().hex),
            name=d.get("name", "YHLZ 默认人格"),
            description=d.get("description", ""),
            traits=traits,
            tone=d.get("tone", ""),
            preferences=PersonalityPreferences.from_dict(d.get("preferences")),
            guidelines=list(d.get("guidelines", []) or []),
            active=bool(d.get("active", False)),
            created_at=float(d.get("created_at", now)),
            updated_at=float(d.get("updated_at", now)),
        )

    # ── 工厂方法 ──────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        name: str,
        description: str = "",
        traits: Optional[Dict[str, float]] = None,
        tone: str = "",
        preferences: Optional[Dict[str, Any]] = None,
        guidelines: Optional[List[str]] = None,
        active: bool = False,
    ) -> "PersonalityProfile":
        """构造人格档案"""
        t = PersonalityTrait.default_traits()
        if traits:
            for k, v in traits.items():
                t[k] = float(v)
        return cls(
            name=name,
            description=description,
            traits=t,
            tone=tone,
            preferences=PersonalityPreferences.from_dict(preferences),
            guidelines=guidelines or [],
            active=active,
        )

    @classmethod
    def default_profile(cls) -> "PersonalityProfile":
        """YHLZ 默认人格 (温暖 / 简洁 / 耐心 / 陪伴感)"""
        return cls.create(
            name="YHLZ 默认人格",
            description="温暖、简洁、耐心、具有陪伴感的 AI Companion 人格",
            traits={
                PersonalityTrait.FRIENDLINESS.value: 4.5,
                PersonalityTrait.HUMOR.value: 3.0,
                PersonalityTrait.RIGOR.value: 3.5,
                PersonalityTrait.WARMTH.value: 4.5,
                PersonalityTrait.CONCISENESS.value: 4.0,
            },
            tone="温暖、亲切、自然, 像老朋友一样交流",
            preferences={
                "address_user": "你",
                "response_length": "简洁",
                "use_emojis": False,
            },
            guidelines=[
                "保持温暖友善的交流方式",
                "回答简洁不啰嗦",
                "有耐心, 逐步引导",
                "尊重用户隐私",
            ],
            active=True,
        )


# ----------------------------------------------------------------------
# 检索条件
# ----------------------------------------------------------------------

@dataclass
class PersonalityQuery:
    """人格检索条件

    Attributes:
        keyword:     关键词过滤 (匹配名称 / 描述 / 语气)
        trait_filter: 维度过滤 (如 {'warmth': 4.0} 匹配 warmth >= 4.0)
        active_only: 仅返回活跃人格
        limit:       返回数量上限
        offset:      偏移量 (分页)
    """
    keyword: Optional[str] = None
    trait_filter: Optional[Dict[str, float]] = None
    active_only: bool = False
    limit: int = 20
    offset: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keyword": self.keyword,
            "trait_filter": self.trait_filter,
            "active_only": self.active_only,
            "limit": self.limit,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonalityQuery":
        return cls(
            keyword=d.get("keyword"),
            trait_filter=d.get("trait_filter"),
            active_only=bool(d.get("active_only", False)),
            limit=int(d.get("limit", 20)),
            offset=int(d.get("offset", 0)),
        )


__all__ = [
    "PersonalityTrait",
    "PersonalityStatus",
    "PersonalityPreferences",
    "PersonalityProfile",
    "PersonalityQuery",
]
