"""
YHLZ Embodied AI V6.0 - 状态恢复 (State Restore)

职责:
    - 恢复流程:
      Load Snapshot → Checksum Verify → Schema Verify →
      Identity Verify → Memory Verify → Activate
    - 要求: 恢复失败不能崩溃 (跳过 + 记录 + 审计)

设计原则:
    - 每步校验独立 (可定位失败环节)
    - 校验失败 → skip (不激活该域), 记录原因
    - 纯规则, 无黑盒
    - 线程安全 (RLock)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from backend.embodied.companion.persistence.snapshot import (
    SNAPSHOT_DOMAINS,
    CompanionSnapshot,
)

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """恢复操作异常"""


# 恢复阶段 (可解释)
RESTORE_STEPS: List[str] = [
    "load",              # 加载快照
    "checksum_verify",   # 完整性校验
    "schema_verify",     # 结构版本校验
    "identity_verify",   # 身份校验
    "memory_verify",     # 记忆校验
    "activate",          # 激活
]


class RestoreManager:
    """状态恢复管理器 (失败不崩溃)

    用法:
        restore = RestoreManager(snapshot_builder)
        result = restore.restore(snapshot, appliers)
    """

    def __init__(self, snapshot: Optional[CompanionSnapshot] = None,
                 schema_version: str = "9.5.0",
                 identity_fingerprint: str = ""):
        self._lock = threading.RLock()
        self._snapshot = snapshot or CompanionSnapshot()
        self._schema_version = str(schema_version)
        self._identity_fingerprint = str(identity_fingerprint)

    # ── 恢复主入口 ───────────────────────────────────────────────
    def restore(
        self,
        snapshot: Dict[str, Any],
        appliers: Optional[Dict[str, Callable]] = None,
    ) -> Dict[str, Any]:
        """执行完整恢复流程

        Args:
            snapshot: 快照 dict
            appliers: 域 → 应用函数 {(domain): fn(state) -> bool}
                (缺省域不激活)

        Returns:
            {
                'restore_id', 'steps': [...], 'activated': [...],
                'skipped': [...], 'success': bool, 'mode',
                'restored_at',
            }
        """
        with self._lock:
            steps: List[Dict[str, Any]] = []
            activated: List[str] = []
            skipped: List[str] = []

            def record_step(step: str, ok: bool, detail: str) -> None:
                steps.append({
                    "step": step, "ok": ok, "detail": detail,
                })

            # 1. Load
            if not snapshot or not isinstance(snapshot, dict):
                record_step("load", False, "快照为空")
                return self._result(steps, activated, skipped, False)
            record_step("load", True, f"快照 {snapshot.get('snapshot_id', '?')}")
            # 2. Checksum Verify
            ok, reason = self._snapshot.verify(snapshot)
            if not ok:
                record_step("checksum_verify", False, reason)
                return self._result(steps, activated, skipped, False)
            record_step("checksum_verify", True, reason)
            # 3. Schema Verify
            ok, reason = self._schema_verify(snapshot)
            if not ok:
                record_step("schema_verify", False, reason)
                return self._result(steps, activated, skipped, False)
            record_step("schema_verify", True, reason)
            # 4. Identity Verify
            ok, reason = self._identity_verify(snapshot)
            record_step("identity_verify", ok, reason)
            if not ok:
                return self._result(steps, activated, skipped, False)
            # 5. Memory Verify + Activate (逐域, 失败跳过)
            state = snapshot.get("state", {})
            for domain in SNAPSHOT_DOMAINS:
                if domain not in state:
                    continue
                mem_ok, mem_reason = self._memory_verify(
                    domain, state[domain],
                )
                record_step(f"memory_verify:{domain}", mem_ok,
                            mem_reason)
                if not mem_ok:
                    skipped.append(domain)
                    continue
                applied = self._apply(appliers, domain, state[domain])
                if applied:
                    record_step(f"activate:{domain}", True, "已激活")
                    activated.append(domain)
                else:
                    skipped.append(domain)
                    record_step(f"activate:{domain}", False,
                                "无应用器或应用失败")
            success = bool(activated)
            record_step("activate", success,
                        f"激活 {len(activated)} 域, 跳过 {len(skipped)}")
            return self._result(steps, activated, skipped, success)

    # ── 子步骤 (可解释) ─────────────────────────────────────────
    def _schema_verify(self, snapshot: Dict[str, Any]) -> tuple:
        """结构版本校验: 快照 version 前缀匹配当前版本"""
        version = str(snapshot.get("version", ""))
        if not version:
            return False, "快照版本为空"
        if version.split(".")[0] != self._schema_version.split(".")[0]:
            return False, (
                f"版本不兼容: 快照 {version}, 当前 "
                f"{self._schema_version} (主版本不同, 降级跳过)"
            )
        return True, f"版本兼容: {version}"

    def _identity_verify(self, snapshot: Dict[str, Any]) -> tuple:
        """身份校验: 身份指纹一致"""
        state = snapshot.get("state", {})
        identity = state.get("identity", {})
        if not identity:
            return True, "快照无身份域 (跳过身份校验)"
        stored = str(identity.get("fingerprint", ""))
        if self._identity_fingerprint and stored and \
                stored != self._identity_fingerprint:
            return False, f"身份指纹不匹配: 快照 {stored}"
        return True, "身份校验通过"

    @staticmethod
    def _memory_verify(domain: str, data: Any) -> tuple:
        """记忆校验: 域数据基本合法性"""
        if data is None:
            return False, f"域 {domain} 数据为空"
        if isinstance(data, list):
            if len(data) > 100000:
                return False, f"域 {domain} 数据量异常 ({len(data)})"
            return True, f"域 {domain} {len(data)} 条"
        if isinstance(data, dict):
            return True, f"域 {domain} dict"
        return False, f"域 {domain} 类型非法"

    @staticmethod
    def _apply(
        appliers: Optional[Dict[str, Callable]],
        domain: str, data: Any,
    ) -> bool:
        """调用域应用器 (异常不崩溃)"""
        if not appliers or domain not in appliers:
            return False
        try:
            result = appliers[domain](data)
            return result is not False
        except Exception as e:
            logger.warning(f"[Restore] 域 {domain} 应用失败: {e}")
            return False

    def _result(self, steps, activated, skipped, success) -> Dict[str, Any]:
        return {
            "restore_id": "rest_" + __import__("uuid").uuid4().hex[:8],
            "steps": steps,
            "activated": activated,
            "skipped": skipped,
            "success": success,
            "mode": "rule_based",
            "restored_at": __import__("time").time(),
        }

    # ── 统计 ─────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        return {
            "mode": "rule_based",
            "schema_version": self._schema_version,
            "identity_fingerprint": (
                self._identity_fingerprint or "未设置"
            ),
        }


__all__ = [
    "RESTORE_STEPS",
    "RestoreError",
    "RestoreManager",
]
