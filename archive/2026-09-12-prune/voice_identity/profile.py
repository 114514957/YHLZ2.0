"""
YHLZ Voice Identity System V1.2 - Voice Profile 管理系统

职责:
    - 在 V1.1 数据层之上提供 VoiceProfile 业务对象 CRUD
    - 自动生成唯一 voice_id
    - Profile 状态机管理 (creating/ready/disabled/deleted)

Profile 必含字段 (对齐 V1.2 Prompt):
    voice_id / name / type / owner / reference_audio / engine / style / metadata

设计原则:
    - 仅依赖 V1.1 database, 不触碰 TTS / 引擎 (与 V1.3 Registry 解耦)
    - 软删优先 (status=deleted), 保留硬删能力
    - 状态转移受校验, 非法转移抛 VoiceProfileError
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from backend.voice_identity.database import VoiceIdentityDB, get_db
from backend.voice_identity.models import VoiceProfile

logger = logging.getLogger(__name__)


class VoiceProfileError(Exception):
    """Voice Profile 业务异常"""


# ── 状态转移表 (V1.4 完整生命周期 CREATED→PROCESSING→READY→ACTIVE→DISABLED) ──
# 软删 deleted 为终态, 仅硬删可移除
_TRANSITIONS: Dict[str, set] = {
    "creating":   {"processing", "ready", "disabled", "deleted"},
    "processing": {"ready", "disabled", "deleted"},
    "ready":      {"active", "disabled", "deleted", "creating", "processing"},
    "active":     {"ready", "disabled", "deleted"},
    "disabled":   {"ready", "deleted", "creating"},
    "deleted":    set(),  # 终态
}

# slug 正则: 仅保留 a-z0-9, 其余 → '_'
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """名称 → slug (非 ASCII / 空 → 'voice')"""
    s = name.strip().lower()
    if not s or not s.isascii():
        return "voice"
    s = _SLUG_RE.sub("_", s).strip("_")
    return s or "voice"


class VoiceProfileStore:
    """Voice Profile 业务存储 (CRUD + 状态机)

    线程安全由底层 VoiceIdentityDB 保证。
    """

    def __init__(self, db: Optional[VoiceIdentityDB] = None):
        self._db = db or get_db()

    # ------------------------------------------------------------------
    # ID 生成
    # ------------------------------------------------------------------

    def _generate_voice_id(self, name: str) -> str:
        """生成唯一 voice_id: {slug(name)}_{8hex}; 冲突重试"""
        for _ in range(8):
            candidate = f"{_slug(name)}_{uuid.uuid4().hex[:8]}"
            if self._db.get_profile_by_id(candidate) is None:
                return candidate
        # 极端情况: 退化为纯 uuid
        return f"voice_{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        type: str = "character",
        owner: str = "system",
        engine: str = "qwen3",
        voice_id: Optional[str] = None,
        reference_audio: Optional[str] = None,
        style: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        language: str = "zh",
        status: str = "creating",
    ) -> VoiceProfile:
        """创建 Profile (voice_id 缺省自动生成); 返回完整对象"""
        # voice_id 唯一性: 自动生成或显式校验
        if voice_id is None:
            voice_id = self._generate_voice_id(name)
        elif self._db.get_profile_by_id(voice_id) is not None:
            raise VoiceProfileError(f"voice_id 已存在: {voice_id}")

        profile = VoiceProfile(
            voice_id=voice_id,
            name=name,
            type=type,
            owner_id=owner,
            engine=engine,
            reference_audio=reference_audio,
            style=style or {},
            metadata=metadata or {},
            language=language,
            status=status,
        )
        self._db.insert_profile(profile)
        logger.info(f"Profile 已创建: voice_id={voice_id} name={name} type={type}")
        return self._db.get_profile_by_id(voice_id)

    def get(self, voice_id: str) -> Optional[VoiceProfile]:
        """读取 Profile (不存在返回 None)"""
        return self._db.get_profile_by_id(voice_id)

    def update(self, voice_id: str, **fields) -> VoiceProfile:
        """更新 Profile 字段; 返回更新后对象

        允许字段: name/type/owner/engine/reference_audio/style/metadata/language/status
        (status 直接赋值不走状态机校验; 推荐用 mark_ready/disable 等方法转移状态)
        """
        if self._db.get_profile_by_id(voice_id) is None:
            raise VoiceProfileError(f"voice_id 不存在: {voice_id}")
        # owner → owner_id 映射
        if "owner" in fields:
            fields["owner_id"] = fields.pop("owner")
        n = self._db.update_profile(voice_id, fields)
        if n == 0:
            raise VoiceProfileError(f"无有效字段可更新: {voice_id}")
        logger.info(f"Profile 已更新: voice_id={voice_id} fields={list(fields.keys())}")
        return self._db.get_profile_by_id(voice_id)

    def delete(self, voice_id: str, soft: bool = True) -> bool:
        """删除 Profile
        soft=True (默认): 标记 status=deleted (保留数据)
        soft=False: 物理删除 (级联清理 model/usage)
        """
        if self._db.get_profile_by_id(voice_id) is None:
            return False
        if soft:
            self._db.update_profile(voice_id, {"status": "deleted"})
            logger.info(f"Profile 已软删: voice_id={voice_id}")
        else:
            self._db.delete_profile(voice_id)
            logger.info(f"Profile 已硬删: voice_id={voice_id}")
        return True

    def list(
        self,
        owner: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> List[VoiceProfile]:
        """按条件列出 Profile (默认全部, 含 deleted)"""
        return self._db.list_profiles(owner=owner, type_=type, status=status, engine=engine)

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------

    def _transition(self, voice_id: str, target: str) -> VoiceProfile:
        """校验并执行状态转移; 非法转移抛 VoiceProfileError"""
        profile = self._db.get_profile_by_id(voice_id)
        if profile is None:
            raise VoiceProfileError(f"voice_id 不存在: {voice_id}")
        current = profile.status
        if target not in _TRANSITIONS.get(current, set()):
            raise VoiceProfileError(
                f"非法状态转移: {current} → {target} (voice_id={voice_id})"
            )
        if current == target:
            return profile
        self._db.update_profile(voice_id, {"status": target})
        logger.info(f"Profile 状态转移: {voice_id} {current} → {target}")
        return self._db.get_profile_by_id(voice_id)

    def mark_ready(self, voice_id: str) -> VoiceProfile:
        """→ ready (可从 creating/processing/active/disabled)"""
        return self._transition(voice_id, "ready")

    def mark_processing(self, voice_id: str) -> VoiceProfile:
        """→ processing (V1.4: 模型/缓存准备中, 可从 creating/ready)"""
        return self._transition(voice_id, "processing")

    def activate(self, voice_id: str) -> VoiceProfile:
        """→ active (V1.4: 激活, 可从 ready)"""
        return self._transition(voice_id, "active")

    def deactivate(self, voice_id: str) -> VoiceProfile:
        """active → ready (V1.4: 去激活, 保留可发现)"""
        return self._transition(voice_id, "ready")

    def disable(self, voice_id: str) -> VoiceProfile:
        """→ disabled"""
        return self._transition(voice_id, "disabled")

    def enable(self, voice_id: str) -> VoiceProfile:
        """disabled → ready (语义别名)"""
        return self._transition(voice_id, "ready")

    def mark_creating(self, voice_id: str) -> VoiceProfile:
        """→ creating (重新处理)"""
        return self._transition(voice_id, "creating")
