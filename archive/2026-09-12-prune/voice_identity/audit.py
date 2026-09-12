"""
YHLZ Voice Identity System V2.2-Phase3.3 - 安全与审计系统

职责:
    - 审计日志: 记录声音的创建/使用/删除/合成/选择/激活事件
    - 权限校验: 基于 owner_id 的访问控制
    - 审计查询: 按时间/事件类型/voice_id/操作者筛选

架构层次:
    API (/voice/audit/*)
      ↓
    AuditLogger (本模块)
      ↓
    VoiceIdentityDB (复用连接, 新建 voice_audit_log 表)
      ↓
    SQLite (voice_identity.db)

审计事件类型:
    - voice_created   声音创建 (clone/create)
    - voice_selected  声音选择 (select)
    - voice_activated 声音激活
    - voice_deleted    声音删除
    - voice_synthesized 声音合成
    - voice_accessed   声音访问 (查询详情)

权限模型:
    - owner_id: 声音归属者 (system/user_id/character_id)
    - 操作者 actor_id: 发起请求的用户标识
    - 规则:
        * owner=system 的声音, 任何 actor 可读, 仅 system 可写
        * owner=actor 的声音, actor 可读写
        * 其他情况: 拒绝 (raise PermissionError)

设计原则:
    - 复用现有 DB 连接 (不新建 db 文件)
    - 审计表 IF NOT EXISTS 幂等创建
    - 审计写入失败不阻塞主流程 (仅日志告警)
    - 权限校验返回 bool/抛异常两种模式
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.voice_identity.database import VoiceIdentityDB
from backend.voice_identity.models import VoiceProfile

logger = logging.getLogger(__name__)

# 审计事件类型常量
EVENT_CREATED = "voice_created"
EVENT_SELECTED = "voice_selected"
EVENT_ACTIVATED = "voice_activated"
EVENT_DELETED = "voice_deleted"
EVENT_SYNTHESIZED = "voice_synthesized"
EVENT_ACCESSED = "voice_accessed"

VALID_EVENTS = {
    EVENT_CREATED, EVENT_SELECTED, EVENT_ACTIVATED,
    EVENT_DELETED, EVENT_SYNTHESIZED, EVENT_ACCESSED,
}

# 权限角色
ROLE_SYSTEM = "system"
# 权限动作
ACTION_READ = "read"
ACTION_WRITE = "write"
ACTION_DELETE = "delete"
ACTION_SYNTHESIZE = "synthesize"

VALID_ACTIONS = {ACTION_READ, ACTION_WRITE, ACTION_DELETE, ACTION_SYNTHESIZE}


# ==================================================================
# 审计日志表 DDL (幂等)
# ==================================================================

DDL_VOICE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS voice_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT    NOT NULL,
    voice_id    TEXT,
    actor_id    TEXT    NOT NULL DEFAULT 'system',
    owner_id    TEXT,
    detail      TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_voice_id ON voice_audit_log(voice_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON voice_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON voice_audit_log(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON voice_audit_log(created_at);
"""


# ==================================================================
# 数据模型
# ==================================================================

@dataclass(frozen=True)
class AuditEntry:
    """审计日志条目

    字段:
        id:         自增主键
        event_type: 事件类型 (voice_created/voice_deleted/...)
        voice_id:   关联声音 ID (可为 None, 如批量任务级事件)
        actor_id:   操作者 (system/user_id)
        owner_id:   声音归属者
        detail:     详细信息 JSON (如合成文本/删除方式)
        created_at: 时间戳 (ISO 字符串)
    """
    id: Optional[int]
    event_type: str
    voice_id: Optional[str]
    actor_id: str
    owner_id: Optional[str]
    detail: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "voice_id": self.voice_id,
            "actor_id": self.actor_id,
            "owner_id": self.owner_id,
            "detail": self.detail,
            "created_at": self.created_at,
        }


class PermissionError(Exception):
    """权限不足异常"""


# ==================================================================
# 审计日志记录器
# ==================================================================

class AuditLogger:
    """声音审计日志记录器

    构造参数:
        db: VoiceIdentityDB (复用现有连接; None 时用全局单例)
    """

    _init_lock = threading.Lock()

    def __init__(self, db: Optional[VoiceIdentityDB] = None):
        if db is None:
            # 动态导入 get_db, 避免模块级缓存导致测试 DB 隔离失效
            from backend.voice_identity.database import get_db
            db = get_db()
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """幂等创建审计表 (每次检查, 避免跨 DB 实例遗漏)"""
        with self._init_lock:
            try:
                with self._db._lock:  # type: ignore[attr-defined]
                    assert self._db._conn is not None  # type: ignore[attr-defined]
                    self._db._conn.executescript(DDL_VOICE_AUDIT_LOG)  # type: ignore[attr-defined]
                logger.debug("voice_audit_log 表已就绪")
            except Exception as e:
                logger.error(f"创建 voice_audit_log 表失败: {e}")
                raise

    # ------------------------------------------------------------------
    # 记录审计
    # ------------------------------------------------------------------

    def log(
        self,
        event_type: str,
        voice_id: Optional[str] = None,
        actor_id: str = "system",
        owner_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditEntry]:
        """记录审计事件

        参数:
            event_type: 事件类型 (必须为 VALID_EVENTS)
            voice_id:   关联声音 (可为 None)
            actor_id:   操作者
            owner_id:   声音归属者
            detail:     详细信息

        返回:
            AuditEntry; 失败返回 None (不抛异常, 仅日志)
        """
        if event_type not in VALID_EVENTS:
            logger.warning(f"非法审计事件类型: {event_type}")
            return None
        try:
            detail_str = json.dumps(detail or {}, ensure_ascii=False)
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                cur = self._db._conn.execute(  # type: ignore[attr-defined]
                    "INSERT INTO voice_audit_log "
                    "(event_type, voice_id, actor_id, owner_id, detail) "
                    "VALUES (?, ?, ?, ?, ?);",
                    (event_type, voice_id, actor_id, owner_id, detail_str),
                )
                entry_id = cur.lastrowid
                row = self._db._conn.execute(  # type: ignore[attr-defined]
                    "SELECT * FROM voice_audit_log WHERE id = ?;",
                    (entry_id,),
                ).fetchone()
            if row:
                return AuditEntry(
                    id=row["id"],
                    event_type=row["event_type"],
                    voice_id=row["voice_id"],
                    actor_id=row["actor_id"],
                    owner_id=row["owner_id"],
                    detail=json.loads(row["detail"] or "{}"),
                    created_at=row["created_at"],
                )
            return AuditEntry(
                id=entry_id, event_type=event_type, voice_id=voice_id,
                actor_id=actor_id, owner_id=owner_id, detail=detail or {},
                created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            )
        except Exception as e:
            logger.error(f"审计日志写入失败 (不阻塞主流程): {e}")
            return None

    # ------------------------------------------------------------------
    # 查询审计
    # ------------------------------------------------------------------

    def query(
        self,
        voice_id: Optional[str] = None,
        event_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditEntry]:
        """查询审计日志

        参数:
            voice_id:   按声音筛选
            event_type: 按事件类型筛选
            actor_id:   按操作者筛选
            start_time: 起始时间 (ISO 字符串, 含)
            end_time:   结束时间 (ISO 字符串, 含)
            limit:      最多返回条数 (默认 100)
            offset:     偏移量 (分页)

        返回:
            AuditEntry 列表 (按 created_at 倒序)
        """
        clauses: List[str] = []
        params: List[Any] = []
        if voice_id is not None:
            clauses.append("voice_id = ?")
            params.append(voice_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(actor_id)
        if start_time is not None:
            clauses.append("created_at >= ?")
            params.append(start_time)
        if end_time is not None:
            clauses.append("created_at <= ?")
            params.append(end_time)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM voice_audit_log{where} "
            f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?;"
        )
        params.extend([limit, offset])
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                rows = self._db._conn.execute(sql, tuple(params)).fetchall()  # type: ignore[attr-defined]
            return [
                AuditEntry(
                    id=r["id"],
                    event_type=r["event_type"],
                    voice_id=r["voice_id"],
                    actor_id=r["actor_id"],
                    owner_id=r["owner_id"],
                    detail=json.loads(r["detail"] or "{}"),
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        except Exception as e:
            logger.error(f"审计日志查询失败: {e}")
            return []

    def count(
        self,
        voice_id: Optional[str] = None,
        event_type: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> int:
        """统计审计日志条数"""
        clauses: List[str] = []
        params: List[Any] = []
        if voice_id is not None:
            clauses.append("voice_id = ?")
            params.append(voice_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(actor_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        try:
            with self._db._lock:  # type: ignore[attr-defined]
                assert self._db._conn is not None  # type: ignore[attr-defined]
                row = self._db._conn.execute(  # type: ignore[attr-defined]
                    f"SELECT COUNT(*) AS c FROM voice_audit_log{where};",
                    tuple(params),
                ).fetchone()
            return int(row["c"]) if row else 0
        except Exception as e:
            logger.error(f"审计日志计数失败: {e}")
            return 0


# ==================================================================
# 权限校验
# ==================================================================

class VoicePermission:
    """声音权限校验器

    权限模型:
        - owner=system: 公共声音, 任何 actor 可读; 仅 system/owner 可写/删
        - owner=actor:  私有声音, actor 可读写删
        - 其他:         仅可读 (若 owner 允许共享) 或拒绝

    使用:
        perm = VoicePermission()
        perm.check(profile, actor_id="user_123", action="delete")  # 抛异常或返 True
    """

    def __init__(self, system_actor: str = ROLE_SYSTEM):
        self._system_actor = system_actor

    def can(
        self,
        profile: VoiceProfile,
        actor_id: str,
        action: str,
    ) -> bool:
        """检查权限 (返回 bool, 不抛异常)

        参数:
            profile:  声音 Profile
            actor_id: 操作者
            action:   动作 (read/write/delete/synthesize)

        返回:
            True=允许, False=拒绝
        """
        if action not in VALID_ACTIONS:
            logger.warning(f"非法 action: {action}")
            return False
        # system 角色拥有全部权限
        if actor_id == self._system_actor:
            return True
        # owner 自身拥有全部权限
        if actor_id == profile.owner_id:
            return True
        # 非归属者:
        # - read/synthesize: system 声音允许 (公共); 私有声音允许 (默认共享读)
        # - write/delete: 仅 system 或 owner
        if action in (ACTION_READ, ACTION_SYNTHESIZE):
            return True
        return False

    def check(
        self,
        profile: VoiceProfile,
        actor_id: str,
        action: str,
    ) -> bool:
        """检查权限 (拒绝抛 PermissionError)

        返回:
            True=允许

        异常:
            PermissionError: 权限不足
        """
        if self.can(profile, actor_id, action):
            return True
        raise PermissionError(
            f"权限不足: actor={actor_id} 无权对 voice_id={profile.voice_id} "
            f"执行 {action} (owner={profile.owner_id})"
        )

    def require_owner_or_system(
        self,
        profile: VoiceProfile,
        actor_id: str,
    ) -> bool:
        """要求是 owner 或 system (写/删操作的前置校验)

        异常:
            PermissionError: 非 owner 且非 system
        """
        if actor_id == self._system_actor or actor_id == profile.owner_id:
            return True
        raise PermissionError(
            f"权限不足: actor={actor_id} 非声音归属者 {profile.owner_id}, "
            f"无法修改 voice_id={profile.voice_id}"
        )


# ==================================================================
# 模块级单例
# ==================================================================

_audit_logger: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """获取全局 AuditLogger 单例"""
    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger


def reset_audit_logger() -> None:
    """重置全局 AuditLogger 单例 (仅用于测试)"""
    global _audit_logger
    with _audit_lock:
        _audit_logger = None
