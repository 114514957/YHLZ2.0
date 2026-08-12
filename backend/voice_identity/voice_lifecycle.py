"""
YHLZ Voice Identity System V2.3-Phase4 - Voice Lifecycle Management

职责:
    - 声音生命周期状态流转: created → ready → active → inactive → archived → deleted
    - archive_voice(): 归档声音 (ready/active/inactive → archived)
    - restore_voice(): 恢复归档声音 (archived → ready)
    - cleanup_unused_voice(): 按使用时长自动降级
        * 90 天未使用 → inactive
        * 180 天未使用 → archived

生命周期状态机:
    creating → ready → active (选中激活)
              ready → inactive (90d 未用)
              inactive → archived (180d 未用)
              archived → ready (restore_voice 恢复)
    任意 → deleted (delete_voice)

设计原则:
    - 复用 VoiceIdentityService / Manager / DB, 不绕过现有层
    - 归档不删除数据 (保留 Profile + Cache, 仅状态变更)
    - 归档声音不可被 select_voice 激活 (Registry discoverable_only 过滤)
    - 自动清理可配置阈值 (默认 90/180 天)
    - 返回结构化报告 (CleanupReport)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.voice_identity.database import VoiceIdentityDB, get_db
from backend.voice_identity.models import VoiceProfile
from backend.voice_identity.schema import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_DELETED,
    STATUS_INACTIVE,
    STATUS_READY,
)

logger = logging.getLogger(__name__)

# 默认生命周期阈值 (天)
DEFAULT_INACTIVE_DAYS = 90
DEFAULT_ARCHIVE_DAYS = 180


# ==================================================================
# 数据模型
# ==================================================================

@dataclass
class LifecycleResult:
    """单个声音生命周期操作结果"""
    voice_id: str
    success: bool
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "voice_id": self.voice_id,
            "success": self.success,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "error": self.error,
        }


@dataclass
class CleanupReport:
    """批量清理报告"""
    inactive_count: int = 0          # 本次降级为 inactive 的数量
    archived_count: int = 0          # 本次归档的数量
    skipped_count: int = 0           # 跳过 (已归档/已删除/未就绪) 的数量
    errors: List[str] = field(default_factory=list)
    details: List[LifecycleResult] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return self.inactive_count + self.archived_count + self.skipped_count

    def to_dict(self) -> dict:
        return {
            "inactive_count": self.inactive_count,
            "archived_count": self.archived_count,
            "skipped_count": self.skipped_count,
            "total_processed": self.total_processed,
            "errors": self.errors,
            "details": [d.to_dict() for d in self.details],
        }


# ==================================================================
# 生命周期管理器
# ==================================================================

class VoiceLifecycle:
    """声音生命周期管理器

    构造参数:
        svc:  VoiceIdentityService (用于查询/更新 profile)
        db:   VoiceIdentityDB (复用连接; 缺省用 svc.db 或全局单例)
    """

    def __init__(self, svc=None, db: Optional[VoiceIdentityDB] = None):
        if svc is None:
            from backend.voice_identity.service import VoiceIdentityService
            svc = VoiceIdentityService()
        self._svc = svc
        self._db = db or svc.db or get_db()

    # ------------------------------------------------------------------
    # 单声音操作
    # ------------------------------------------------------------------

    def archive_voice(self, voice_id: str) -> LifecycleResult:
        """归档声音 (ready/active/inactive → archived)

        规则:
            - 不存在 → 失败
            - 已 deleted → 失败 (不可归档已删除)
            - 已 archived → 幂等成功 (不重复操作)
            - 其他状态 → 转为 archived
        """
        try:
            profile = self._svc.get_voice(voice_id)
            if profile is None:
                return LifecycleResult(voice_id, False, error="声音不存在")
            old = profile.status
            if old == STATUS_DELETED:
                return LifecycleResult(voice_id, False, old_status=old,
                                       error="已删除声音不可归档")
            if old == STATUS_ARCHIVED:
                return LifecycleResult(voice_id, True, old_status=old,
                                       new_status=STATUS_ARCHIVED)
            # 更新状态
            self._db.update_profile(voice_id, {"status": STATUS_ARCHIVED})
            logger.info(f"声音已归档: {voice_id} ({old} → archived)")
            return LifecycleResult(voice_id, True, old_status=old,
                                   new_status=STATUS_ARCHIVED)
        except Exception as e:
            logger.error(f"归档声音失败 {voice_id}: {e}")
            return LifecycleResult(voice_id, False, error=str(e))

    def restore_voice(self, voice_id: str) -> LifecycleResult:
        """恢复归档声音 (archived/inactive → ready)

        规则:
            - 不存在 → 失败
            - 已 deleted → 失败
            - 已 ready/active → 幂等成功
            - archived/inactive → 转为 ready
        """
        try:
            profile = self._svc.get_voice(voice_id)
            if profile is None:
                return LifecycleResult(voice_id, False, error="声音不存在")
            old = profile.status
            if old == STATUS_DELETED:
                return LifecycleResult(voice_id, False, old_status=old,
                                       error="已删除声音不可恢复")
            if old in (STATUS_READY, STATUS_ACTIVE):
                return LifecycleResult(voice_id, True, old_status=old,
                                       new_status=old)
            self._db.update_profile(voice_id, {"status": STATUS_READY})
            logger.info(f"声音已恢复: {voice_id} ({old} → ready)")
            return LifecycleResult(voice_id, True, old_status=old,
                                   new_status=STATUS_READY)
        except Exception as e:
            logger.error(f"恢复声音失败 {voice_id}: {e}")
            return LifecycleResult(voice_id, False, error=str(e))

    def deactivate_voice(self, voice_id: str) -> LifecycleResult:
        """停用声音 (active → inactive; 单声音停用)"""
        try:
            profile = self._svc.get_voice(voice_id)
            if profile is None:
                return LifecycleResult(voice_id, False, error="声音不存在")
            old = profile.status
            if old == STATUS_DELETED:
                return LifecycleResult(voice_id, False, old_status=old,
                                       error="已删除声音不可停用")
            if old == STATUS_INACTIVE:
                return LifecycleResult(voice_id, True, old_status=old,
                                       new_status=STATUS_INACTIVE)
            self._db.update_profile(voice_id, {"status": STATUS_INACTIVE})
            logger.info(f"声音已停用: {voice_id} ({old} → inactive)")
            return LifecycleResult(voice_id, True, old_status=old,
                                   new_status=STATUS_INACTIVE)
        except Exception as e:
            logger.error(f"停用声音失败 {voice_id}: {e}")
            return LifecycleResult(voice_id, False, error=str(e))

    # ------------------------------------------------------------------
    # 批量清理 (按使用时长自动降级)
    # ------------------------------------------------------------------

    def cleanup_unused_voice(
        self,
        inactive_days: int = DEFAULT_INACTIVE_DAYS,
        archive_days: int = DEFAULT_ARCHIVE_DAYS,
        now: Optional[datetime] = None,
    ) -> CleanupReport:
        """按使用时长自动降级未使用声音

        规则:
            - last_used 距今 >= inactive_days 且状态为 ready/active → inactive
            - last_used 距今 >= archive_days 且状态为 inactive/ready/active → archived
            - 无使用记录 (last_used=None) 的就绪声音: 用 created_at 估算
            - 已 archived/deleted 跳过

        参数:
            inactive_days: 未使用降级 inactive 的天数 (默认 90)
            archive_days:  未使用归档的天数 (默认 180)
            now:          当前时间 (测试用; 缺省 datetime.now())

        返回:
            CleanupReport
        """
        report = CleanupReport()
        if now is None:
            now = datetime.now()
        inactive_threshold = now - timedelta(days=inactive_days)
        archive_threshold = now - timedelta(days=archive_days)

        try:
            profiles = self._svc.list_voice(discoverable_only=False)
        except Exception as e:
            report.errors.append(f"列出声音失败: {e}")
            return report

        # 构建 voice_id → last_used 映射
        try:
            usages = self._db.list_all_usage()
            last_used_map: Dict[str, Optional[str]] = {u.voice_id: u.last_used for u in usages}
        except Exception as e:
            report.errors.append(f"查询使用记录失败: {e}")
            last_used_map = {}

        for profile in profiles:
            vid = profile.voice_id
            status = profile.status
            # 跳过终态
            if status in (STATUS_ARCHIVED, STATUS_DELETED):
                report.skipped_count += 1
                continue

            # 确定参考时间: last_used 优先, 回退 created_at
            last_used_str = last_used_map.get(vid)
            ref_time_str = last_used_str or profile.created_at
            if ref_time_str is None:
                # 无时间参考, 跳过
                report.skipped_count += 1
                continue

            try:
                ref_time = datetime.strptime(ref_time_str, "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                report.skipped_count += 1
                continue

            # 180 天未使用 → archived
            if ref_time <= archive_threshold:
                r = self.archive_voice(vid)
                report.details.append(r)
                if r.success:
                    report.archived_count += 1
                else:
                    report.errors.append(f"{vid}: {r.error}")
            # 90 天未使用 → inactive
            elif ref_time <= inactive_threshold:
                r = self.deactivate_voice(vid)
                report.details.append(r)
                if r.success:
                    report.inactive_count += 1
                else:
                    report.errors.append(f"{vid}: {r.error}")
            else:
                report.skipped_count += 1

        logger.info(
            f"生命周期清理完成: inactive={report.inactive_count} "
            f"archived={report.archived_count} skipped={report.skipped_count}"
        )
        return report

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_archived(self) -> List[VoiceProfile]:
        """列出已归档声音"""
        try:
            return self._db.list_profiles(status=STATUS_ARCHIVED)
        except Exception as e:
            logger.error(f"列出归档声音失败: {e}")
            return []

    def list_inactive(self) -> List[VoiceProfile]:
        """列出已停用声音"""
        try:
            return self._db.list_profiles(status=STATUS_INACTIVE)
        except Exception as e:
            logger.error(f"列出停用声音失败: {e}")
            return []


# ==================================================================
# 模块级单例
# ==================================================================

_lifecycle: Optional[VoiceLifecycle] = None
_lc_lock = __import__("threading").Lock()


def get_lifecycle() -> VoiceLifecycle:
    """获取全局 VoiceLifecycle 单例"""
    global _lifecycle
    if _lifecycle is None:
        with _lc_lock:
            if _lifecycle is None:
                _lifecycle = VoiceLifecycle()
    return _lifecycle


def reset_lifecycle() -> None:
    """重置全局单例 (测试用)"""
    global _lifecycle
    with _lc_lock:
        _lifecycle = None
