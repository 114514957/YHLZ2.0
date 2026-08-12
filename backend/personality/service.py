"""
YHLZ Personality Engine V3.4 - 人格 Service

职责:
    - 统一对外 API (Interface 层)
    - 组合 Manager + Permission + Logger
    - 流程: 权限校验 → 存储操作 → 日志记录 → 返回 PersonalityOperationResult
    - 默认人格加载 / 当前人格切换 / 人格 CRUD
    - 风格生成 (personality_style) / 一致性评估 (assess_consistency)
    - 人格上下文 (build_persona_context, 供 LLM System Prompt)

架构位置:
    Interface (FastAPI / 外部调用 / Agent Tool)
        ↓
    Service (本模块)
        ↓
    Manager → Store (Adapter / Storage)

设计原则:
    - 单一入口: 所有人格操作经 Service
    - 权限优先: 操作前先校验权限 (personality_enabled)
    - 日志完整: 记录开始/成功/失败/耗时/异常
    - 配置驱动: 从 config 加载权限与参数
    - 可测试: 提供完整 Mock 注入接口
    - Service 不允许直接操作数据库 (只经 Manager → Store)
"""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.personality.logger import PersonalityLogger
from backend.personality.manager import (
    PersonalityManager,
    get_manager,
    reset_manager,
)
from backend.personality.permission import (
    PersonalityPermission,
    PermissionChecker,
)
from backend.personality.schema import (
    PersonalityProfile,
    PersonalityQuery,
    PersonalityStatus,
    PersonalityTrait,
)

logger = logging.getLogger(__name__)


class PersonalityServiceError(Exception):
    """Personality Service 操作异常"""


@dataclass
class PersonalityOperationResult:
    """人格操作统一结果

    Attributes:
        success:    是否成功
        status:     操作状态 (ok / denied / error / not_found / invalid / no_store)
        error:      失败原因 (None=成功)
        profile_id: 关联档案 id
        profile:    档案对象
        profiles:   档案列表 (query 结果)
        profile_name: 档案名称
        consistency: 一致性评分 (assess 结果)
        style:       风格指令文本 (style 结果)
        count:       影响数量
        latency_ms:  耗时 (毫秒)
    """
    success: bool = False
    status: str = PersonalityStatus.OK.value
    error: Optional[str] = None
    profile_id: Optional[str] = None
    profile: Optional[PersonalityProfile] = None
    profiles: List[PersonalityProfile] = field(default_factory=list)
    profile_name: str = ""
    consistency: Optional[float] = None
    style: str = ""
    count: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "error": self.error,
            "profile_id": self.profile_id,
            "profile": self.profile.to_dict() if self.profile else None,
            "profiles": [p.to_dict() for p in self.profiles],
            "profile_name": self.profile_name,
            "consistency": self.consistency,
            "style": self.style,
            "count": self.count,
            "latency_ms": round(self.latency_ms, 2),
        }


class PersonalityService:
    """人格统一服务

    用法:
        svc = PersonalityService()
        svc.load_config(config_dict)
        result = svc.personality_style()

    流程:
        1. 权限校验 (PermissionChecker)
        2. 调用 Manager 路由到 Store
        3. 日志记录
        4. 返回 PersonalityOperationResult
    """

    def __init__(
        self,
        manager: Optional[PersonalityManager] = None,
        permission: Optional[PermissionChecker] = None,
        plog: Optional[PersonalityLogger] = None,
    ):
        self._lock = threading.RLock()
        self._manager: PersonalityManager = manager or PersonalityManager()
        self._permission: PermissionChecker = permission or PermissionChecker()
        self._plog: PersonalityLogger = plog or PersonalityLogger()
        self._initialized = False

    # ── 依赖注入 ──────────────────────────────────────────────────
    def set_manager(self, manager: PersonalityManager) -> None:
        with self._lock:
            self._manager = manager

    def set_permission(self, permission: PermissionChecker) -> None:
        with self._lock:
            self._permission = permission

    def set_logger(self, plog: PersonalityLogger) -> None:
        with self._lock:
            self._plog = plog

    @property
    def manager(self) -> PersonalityManager:
        return self._manager

    @property
    def permission(self) -> PermissionChecker:
        return self._permission

    @property
    def plog(self) -> PersonalityLogger:
        return self._plog

    # ── 配置 ──────────────────────────────────────────────────────
    def load_config(self, config: Dict[str, Any]) -> None:
        """从 dict 加载配置 (权限 + 默认注册)"""
        with self._lock:
            perm = PersonalityPermission.from_dict(config)
            self._permission.load_from_permission(perm)
            self._manager.register_defaults(
                include_memory=True,
                db_path=config.get("db_path"),
            )
            self._initialized = True
        logger.info(f"PersonalityService 配置已加载: {perm.to_dict()}")

    def load_permission(self, permission: PersonalityPermission) -> None:
        self._permission.load_from_permission(permission)

    def update_permission(self, **kwargs) -> PersonalityPermission:
        return self._permission.update(**kwargs)

    def get_permission(self) -> Dict[str, Any]:
        return self._permission.to_dict()

    def reset_permission(self) -> None:
        self._permission.reset()

    # ── 保存 ──────────────────────────────────────────────────────
    def save(self, profile: PersonalityProfile) -> PersonalityOperationResult:
        """保存人格档案 (需权限, 敏感字段过滤)"""
        start = _time.perf_counter()

        # 1. 权限校验 (总开关 + 敏感信息)
        allowed, reason = self._permission.check_save(profile)
        if not allowed:
            latency = (_time.perf_counter() - start) * 1000
            status = (
                PersonalityStatus.PERMISSION_DENIED.value
                if "总开关" in reason
                else PersonalityStatus.INVALID.value
            )
            self._plog.log_fail(
                store=self._store_name(), action="save",
                status=status, error=reason, latency_ms=latency,
            )
            return PersonalityOperationResult(
                success=False, status=status, error=reason, latency_ms=latency,
            )

        # 2. 数量上限
        max_profiles = self._permission.permission.max_profiles
        if max_profiles > 0:
            try:
                existing = self._manager.get_default_store().count()
                already = existing
                if already >= max_profiles:
                    latency = (_time.perf_counter() - start) * 1000
                    reason = f"人格档案数量已达上限 ({max_profiles})"
                    self._plog.log_fail(
                        store=self._store_name(), action="save",
                        status=PersonalityStatus.INVALID.value,
                        error=reason, latency_ms=latency,
                    )
                    return PersonalityOperationResult(
                        success=False, status=PersonalityStatus.INVALID.value,
                        error=reason, latency_ms=latency,
                    )
            except Exception:
                pass

        # 3. 存储操作
        try:
            profile_id = self._manager.save(profile)
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            logger.error(f"[Personality] 保存异常: {e}", exc_info=True)
            self._plog.log_fail(
                store=self._store_name(), action="save",
                status=PersonalityStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"保存失败: {e}", latency_ms=latency,
            )

        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_success(
            store=self._store_name(), action="save",
            profile_id=profile_id, profile_name=profile.name,
            latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile_id, profile=profile,
            profile_name=profile.name, count=1, latency_ms=latency,
        )

    # ── 默认人格 / 当前人格 ────────────────────────────────────────
    def load_default(self) -> PersonalityOperationResult:
        """加载默认人格

        行为:
            - 若存储中无任何档案 → 创建 YHLZ 默认人格并设为当前
            - 若存在活跃档案 → 直接作为当前人格
        """
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("load", reason, start)
        try:
            store = self._manager.get_default_store()
            if store is None:
                latency = (_time.perf_counter() - start) * 1000
                return PersonalityOperationResult(
                    success=False, status=PersonalityStatus.NO_STORE.value,
                    error="无可用存储", latency_ms=latency,
                )
            profiles = store.query(PersonalityQuery(active_only=True, limit=1))
            if profiles:
                current = profiles[0]
            else:
                # 无活跃档案: 创建默认人格并保存
                current = PersonalityProfile.default_profile()
                store.save(current)
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            logger.error(f"[Personality] 默认人格加载异常: {e}", exc_info=True)
            self._plog.log_fail(
                store=self._store_name(), action="load",
                status=PersonalityStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"加载失败: {e}", latency_ms=latency,
            )

        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_success(
            store=self._store_name(), action="load",
            profile_id=current.profile_id, profile_name=current.name,
            latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=current.profile_id, profile=current,
            profile_name=current.name, count=1, latency_ms=latency,
        )

    def switch_profile(self, profile_id: str) -> PersonalityOperationResult:
        """切换当前人格 (置 active, 其他档案取消 active)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("switch", reason, start)
        if not profile_id:
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.EMPTY_INPUT.value,
                error="profile_id 为空", latency_ms=latency,
            )
        try:
            store = self._manager.get_default_store()
            target = store.retrieve(profile_id)
            if target is None:
                latency = (_time.perf_counter() - start) * 1000
                self._plog.log_fail(
                    store=self._store_name(), action="switch",
                    status=PersonalityStatus.NOT_FOUND.value,
                    error=f"档案不存在: {profile_id}", latency_ms=latency,
                )
                return PersonalityOperationResult(
                    success=False, status=PersonalityStatus.NOT_FOUND.value,
                    error=f"档案不存在: {profile_id}",
                    profile_id=profile_id, latency_ms=latency,
                )
            # 取消其他活跃档案
            for p in store.query(PersonalityQuery(active_only=True, limit=100)):
                if p.profile_id != profile_id:
                    store.update(p.profile_id, active=False)
            store.update(profile_id, active=True)
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            logger.error(f"[Personality] 切换异常: {e}", exc_info=True)
            self._plog.log_fail(
                store=self._store_name(), action="switch",
                status=PersonalityStatus.ERROR.value,
                error=f"{type(e).__name__}: {e}", latency_ms=latency,
            )
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"切换失败: {e}", profile_id=profile_id, latency_ms=latency,
            )

        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_success(
            store=self._store_name(), action="switch",
            profile_id=profile_id, profile_name=target.name,
            latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile_id, profile=target,
            profile_name=target.name, count=1, latency_ms=latency,
        )

    def get_current_profile(self) -> PersonalityOperationResult:
        """获取当前人格 (活跃档案, 无则加载默认)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("load", reason, start)
        try:
            store = self._manager.get_default_store()
            if store is None:
                latency = (_time.perf_counter() - start) * 1000
                return PersonalityOperationResult(
                    success=False, status=PersonalityStatus.NO_STORE.value,
                    error="无可用存储", latency_ms=latency,
                )
            profiles = store.query(PersonalityQuery(active_only=True, limit=1))
            if profiles:
                current = profiles[0]
            else:
                current = PersonalityProfile.default_profile()
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            logger.error(f"[Personality] 当前人格获取异常: {e}", exc_info=True)
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"获取失败: {e}", latency_ms=latency,
            )

        latency = (_time.perf_counter() - start) * 1000
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=current.profile_id, profile=current,
            profile_name=current.name, count=1, latency_ms=latency,
        )

    # ── CRUD ──────────────────────────────────────────────────────
    def retrieve(self, profile_id: str) -> PersonalityOperationResult:
        """按 id 获取档案 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("retrieve", reason, start)
        try:
            profile = self._manager.get_default_store().retrieve(profile_id)
        except Exception as e:
            logger.error(f"[Personality] 获取异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"获取失败: {e}", profile_id=profile_id, latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if profile is None:
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.NOT_FOUND.value,
                error=f"档案不存在: {profile_id}", profile_id=profile_id,
                latency_ms=latency,
            )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile_id, profile=profile,
            profile_name=profile.name, count=1, latency_ms=latency,
        )

    def query(self, query: PersonalityQuery) -> PersonalityOperationResult:
        """按条件检索档案 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("query", reason, start)
        try:
            profiles = self._manager.get_default_store().query(query)
        except Exception as e:
            logger.error(f"[Personality] 检索异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"检索失败: {e}", latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profiles=profiles, count=len(profiles), latency_ms=latency,
        )

    def update(self, profile_id: str, **fields) -> PersonalityOperationResult:
        """更新档案字段 (白名单, 需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("update", reason, start)
        try:
            ok = self._manager.get_default_store().update(profile_id, **fields)
        except Exception as e:
            logger.error(f"[Personality] 更新异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"更新失败: {e}", profile_id=profile_id, latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if not ok:
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.NOT_FOUND.value,
                error=f"档案不存在: {profile_id}", profile_id=profile_id,
                latency_ms=latency,
            )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile_id, count=1, latency_ms=latency,
        )

    def delete(self, profile_id: str) -> PersonalityOperationResult:
        """删除档案 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("delete", reason, start)
        try:
            ok = self._manager.get_default_store().delete(profile_id)
        except Exception as e:
            logger.error(f"[Personality] 删除异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"删除失败: {e}", profile_id=profile_id, latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        if not ok:
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.NOT_FOUND.value,
                error=f"档案不存在: {profile_id}", profile_id=profile_id,
                latency_ms=latency,
            )
        self._plog.log_success(
            store=self._store_name(), action="delete",
            profile_id=profile_id, latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile_id, count=1, latency_ms=latency,
        )

    def clear(self) -> PersonalityOperationResult:
        """清空所有档案 (需权限)"""
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("clear", reason, start)
        try:
            n = self._manager.get_default_store().clear()
        except Exception as e:
            logger.error(f"[Personality] 清空异常: {e}", exc_info=True)
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.ERROR.value,
                error=f"清空失败: {e}", latency_ms=latency,
            )
        latency = (_time.perf_counter() - start) * 1000
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            count=n, latency_ms=latency,
        )

    def count(self) -> int:
        """当前档案总数 (不校验权限, 用于状态展示)"""
        try:
            store = self._manager.get_default_store()
            return store.count() if store is not None else 0
        except Exception as e:
            logger.warning(f"[Personality] 计数失败: {e}")
            return 0

    # ── 风格生成 ──────────────────────────────────────────────────
    def personality_style(self) -> PersonalityOperationResult:
        """生成当前人格风格指令

        输出示例:
            你是 YHLZ。
            你的交流方式: 温暖 / 简洁 / 耐心 / 具有陪伴感。
            行为准则: ...
        """
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("style", reason, start)
        current = self.get_current_profile()
        if not current.success:
            return current
        profile = current.profile

        # 依据人格维度生成风格描述
        t = profile.traits
        style_parts = []
        if t.get(PersonalityTrait.WARMTH.value, 0) >= 4:
            style_parts.append("温暖")
        if t.get(PersonalityTrait.FRIENDLINESS.value, 0) >= 4:
            style_parts.append("友好")
        if t.get(PersonalityTrait.HUMOR.value, 0) >= 4:
            style_parts.append("幽默")
        if t.get(PersonalityTrait.CONCISENESS.value, 0) >= 4:
            style_parts.append("简洁")
        if t.get(PersonalityTrait.RIGOR.value, 0) >= 4:
            style_parts.append("严谨")
        if t.get(PersonalityTrait.WARMTH.value, 0) >= 4:
            style_parts.append("具有陪伴感")
        if not style_parts:
            style_parts.append("自然")

        lines = [
            f"你是 {profile.name}。",
            f"你的交流方式: {' / '.join(style_parts)}。",
        ]
        if profile.tone:
            lines.append(f"说话风格: {profile.tone}。")
        if profile.preferences.address_user:
            lines.append(f"称呼用户: {profile.preferences.address_user}。")
        if profile.preferences.response_length:
            lines.append(f"回应长度: {profile.preferences.response_length}。")
        if profile.preferences.use_emojis:
            lines.append("允许使用表情符号, 增强亲和力。")
        else:
            lines.append("不使用表情符号。")
        if profile.guidelines:
            lines.append("行为准则:")
            for g in profile.guidelines:
                lines.append(f"- {g}")

        style_text = "\n".join(lines)
        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_success(
            store=self._store_name(), action="style",
            profile_id=profile.profile_id, profile_name=profile.name,
            latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile.profile_id, profile_name=profile.name,
            profile=profile, style=style_text, count=1, latency_ms=latency,
        )

    # ── 一致性评估 ────────────────────────────────────────────────
    def assess_consistency(self, text: str) -> PersonalityOperationResult:
        """评估文本与当前人格的一致性 (0.0 ~ 1.0)

        基于规则的启发式评估:
            - 简洁度: 文本长度与 conciseness 维度的匹配
            - 温暖度: 是否包含温暖/礼貌用词 (warmth + friendliness)
            - 表情: 是否按偏好使用 emoji
        """
        start = _time.perf_counter()
        allowed, reason = self._permission.check_enabled()
        if not allowed:
            return self._denied("assess", reason, start)
        if not text or not text.strip():
            latency = (_time.perf_counter() - start) * 1000
            return PersonalityOperationResult(
                success=False, status=PersonalityStatus.EMPTY_INPUT.value,
                error="评估文本为空", latency_ms=latency,
            )

        current = self.get_current_profile()
        if not current.success:
            return current
        profile = current.profile
        t = profile.traits

        score = 0.0
        weights = 0.0

        # 1. 简洁度 (权重 0.4)
        length = len(text)
        target_conciseness = t.get(PersonalityTrait.CONCISENESS.value, 3.0)
        if target_conciseness >= 4:
            concise_score = 1.0 if length <= 200 else max(0.0, 1.0 - (length - 200) / 600)
        elif target_conciseness <= 2:
            concise_score = 1.0 if length >= 200 else length / 200
        else:
            concise_score = 1.0
        score += concise_score * 0.4
        weights += 0.4

        # 2. 温暖度 (权重 0.4)
        warm_keywords = ["谢谢", "请", "你好", "加油", "别担心", "没关系", "很好",
                         "可以呀", "没问题", "辛苦", "抱歉", "理解", "支持"]
        target_warmth = (t.get(PersonalityTrait.WARMTH.value, 0.0)
                         + t.get(PersonalityTrait.FRIENDLINESS.value, 0.0)) / 2
        warm_hits = sum(1 for kw in warm_keywords if kw in text)
        if target_warmth >= 4:
            warm_score = min(1.0, warm_hits / 2.0)
        elif target_warmth <= 2:
            warm_score = 1.0 if warm_hits == 0 else max(0.0, 1.0 - warm_hits * 0.5)
        else:
            warm_score = 1.0
        score += warm_score * 0.4
        weights += 0.4

        # 3. 表情偏好 (权重 0.2)
        import re as _re
        emoji_pattern = _re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
        has_emoji = bool(emoji_pattern.search(text))
        if profile.preferences.use_emojis:
            emoji_score = 1.0 if has_emoji else 0.5
        else:
            emoji_score = 1.0 if not has_emoji else 0.5
        score += emoji_score * 0.2
        weights += 0.2

        consistency = round(score / weights, 4)
        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_success(
            store=self._store_name(), action="assess",
            profile_id=profile.profile_id, profile_name=profile.name,
            latency_ms=latency, consistency=consistency,
            metadata={"text_length": length},
        )
        return PersonalityOperationResult(
            success=True, status=PersonalityStatus.OK.value,
            profile_id=profile.profile_id, profile_name=profile.name,
            profile=profile, consistency=consistency, count=1, latency_ms=latency,
        )

    # ── 人格上下文 (P1: 注入 LLM System Prompt) ──────────────────
    def build_persona_context(self) -> str:
        """生成人格上下文文本 (供 LLM System Prompt)

        无权限时返回空字符串 (不阻塞对话主流程)。
        """
        allowed, _ = self._permission.check_enabled()
        if not allowed:
            return ""
        style_result = self.personality_style()
        if not style_result.success:
            return ""
        profile = style_result.profile
        lines = [
            f"[人格档案] {profile.name}",
            f"[人格描述] {profile.description}" if profile.description else "",
            style_result.style,
        ]
        return "\n".join(l for l in lines if l)

    # ── 内部工具 ──────────────────────────────────────────────────
    def _store_name(self) -> str:
        store = self._manager.get_default_store()
        return store.name if store is not None else "none"

    def _denied(self, action: str, reason: str, start: float) -> PersonalityOperationResult:
        latency = (_time.perf_counter() - start) * 1000
        self._plog.log_fail(
            store=self._store_name(), action=action,
            status=PersonalityStatus.PERMISSION_DENIED.value,
            error=reason, latency_ms=latency,
        )
        return PersonalityOperationResult(
            success=False,
            status=PersonalityStatus.PERMISSION_DENIED.value,
            error=reason,
            latency_ms=latency,
        )

    # ── Store 管理 ────────────────────────────────────────────────
    def list_stores(self) -> List[Dict[str, Any]]:
        return self._manager.list_stores()

    # ── 日志查询 ──────────────────────────────────────────────────
    def get_logs(
        self,
        event: Optional[str] = None,
        action: Optional[str] = None,
        store: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        entries = self._plog.query(
            event=event, action=action, store=store, status=status, limit=limit
        )
        return [e.to_dict() for e in entries]

    def get_log_stats(self) -> Dict[str, Any]:
        return self._plog.stats()

    def clear_logs(self) -> int:
        return self._plog.clear()

    # ── 状态 ──────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        return {
            "version": "3.4.0",
            "initialized": self._initialized,
            "permission": self._permission.to_dict(),
            "manager": self._manager.status(),
            "profile_count": self.count(),
            "log_stats": self._plog.stats(),
        }


# ── 全局单例 ─────────────────────────────────────────────────────
_global_service: Optional[PersonalityService] = None
_service_lock = threading.Lock()


def get_service(db_path: Optional[str] = None) -> PersonalityService:
    """获取全局 PersonalityService 单例

    Args:
        db_path: 首次创建时指定 SQLite 数据库路径 (None=默认)
    """
    global _global_service
    with _service_lock:
        if _global_service is None:
            mgr = get_manager(db_path=db_path)
            _global_service = PersonalityService(manager=mgr)
        return _global_service


def reset_service() -> None:
    """重置全局 Service (测试用)"""
    global _global_service
    with _service_lock:
        _global_service = None
    reset_manager()


__all__ = [
    "PersonalityService",
    "PersonalityServiceError",
    "PersonalityOperationResult",
    "get_service",
    "reset_service",
]
