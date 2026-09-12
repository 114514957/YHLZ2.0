"""
YHLZ Voice Identity System - 数据模型 (V1.1 + V1.2)

职责:
    - 定义三张表对应的 Pydantic 模型: VoiceProfile / VoiceModel / VoiceUsage
    - 类型安全 + JSON 序列化 + DB 行互转

设计原则:
    - 复用项目已有 Pydantic (backend.config 同款), 不引入新依赖
    - 模型与 TTS Adapter 解耦: 仅描述声音身份元数据, 不持有引擎实例
    - 枚举值与 schema.py 常量对齐
    - style / metadata 以 dict 持有, DB 层 JSON 序列化 (V1.2)
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, field_validator


# ── 枚举集合 (用于校验) ──
# V1.4 扩展: 增加 processing (生命周期 CREATED→PROCESSING→READY→ACTIVE→DISABLED)
# V2.3-Phase4 扩展: 增加 inactive / archived (生命周期归档管理)
VALID_STATUS = {
    "creating", "processing", "ready", "active",
    "disabled", "deleted",
    "inactive", "archived",  # V2.3-Phase4
}
VALID_TYPE = {"character", "user", "system"}
VALID_ENGINE = {"qwen3", "gpt_sovits", "edge"}


def _parse_json_field(raw: Any, default: Any) -> Any:
    """DB JSON 列安全反序列化: None/空/非法 → default"""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class VoiceProfile(BaseModel):
    """声音身份主记录 (对应 voice_profiles 表)

    字段语义:
        voice_id:        全局唯一声音标识 (业务主键)
        owner_id:        归属者 (system / user_id / character_id)
        name:            展示名 (如 "元亨默认")
        type:            归属类型 (character/user/system)
        language:        主语言 (zh/en/...)
        status:          生命周期状态 (creating/ready/active/disabled/deleted)
        engine:          绑定引擎 (qwen3/gpt_sovits/edge)
        reference_audio: 参考音频路径 (声音克隆用, V1.2)
        style:           声音风格覆盖 (dict, 对齐 VoiceStyle; V1.2)
        metadata:        任意扩展元数据 (dict; V1.2)
    """
    id: Optional[int] = None
    voice_id: str
    owner_id: str = "system"
    name: str
    type: str = "character"
    language: str = "zh"
    status: str = "creating"
    engine: str = "qwen3"
    reference_audio: Optional[str] = None
    style: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in VALID_TYPE:
            raise ValueError(f"非法 type: {v}, 允许: {VALID_TYPE}")
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in VALID_STATUS:
            raise ValueError(f"非法 status: {v}, 允许: {VALID_STATUS}")
        return v

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, v: str) -> str:
        if v not in VALID_ENGINE:
            raise ValueError(f"非法 engine: {v}, 允许: {VALID_ENGINE}")
        return v

    def to_dict(self) -> dict:
        """JSON 序列化 (排除 None)"""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_row(cls, row) -> "VoiceProfile":
        """从 sqlite3.Row 构造 (style/metadata JSON 反序列化)"""
        return cls(
            id=row["id"],
            voice_id=row["voice_id"],
            owner_id=row["owner_id"],
            name=row["name"],
            type=row["type"],
            language=row["language"],
            status=row["status"],
            engine=row["engine"],
            reference_audio=row["reference_audio"],
            style=_parse_json_field(row["style"], default={}),
            metadata=_parse_json_field(row["metadata"], default={}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class VoiceModel(BaseModel):
    """引擎模型/缓存路径登记 (对应 voice_models 表)

    一个 voice_id 可关联多条模型记录 (如 qwen3 embedding + gpt_sovits 权重)。
    """
    id: Optional[int] = None
    voice_id: str
    engine: str = "qwen3"
    model_path: Optional[str] = None
    cache_path: Optional[str] = None
    hash: Optional[str] = None
    loaded: bool = False
    created_at: Optional[str] = None

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, v: str) -> str:
        if v not in VALID_ENGINE:
            raise ValueError(f"非法 engine: {v}, 允许: {VALID_ENGINE}")
        return v

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_row(cls, row) -> "VoiceModel":
        return cls(
            id=row["id"],
            voice_id=row["voice_id"],
            engine=row["engine"],
            model_path=row["model_path"],
            cache_path=row["cache_path"],
            hash=row["hash"],
            loaded=bool(row["loaded"]),
            created_at=row["created_at"],
        )


class VoiceUsage(BaseModel):
    """声音使用统计 (对应 voice_usage 表)

    每个 voice_id 一行, 记录调用次数/最近使用/累计时长。
    """
    id: Optional[int] = None
    voice_id: str
    usage_count: int = 0
    last_used: Optional[str] = None
    duration: float = 0.0

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_row(cls, row) -> "VoiceUsage":
        return cls(
            id=row["id"],
            voice_id=row["voice_id"],
            usage_count=row["usage_count"],
            last_used=row["last_used"],
            duration=row["duration"],
        )
