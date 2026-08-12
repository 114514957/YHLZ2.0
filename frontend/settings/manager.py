"""
YHLZ 前端设置管理器 (Settings Manager)

职责:
    - 四组设置: 基础 / AI / Memory / Developer
    - 持久化到 settings.json
    - 设置变更可追踪 (审计)

设计原则:
    - 设置独立于主界面 (右键菜单/齿轮入口)
    - 分组可解释
    - 线程安全 (RLock)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 设置分组 (可解释)
SETTING_GROUPS: List[str] = [
    "basic",      # 基础: 开机启动/窗口位置/音量/动画
    "ai",         # AI: 模型选择/API配置/算力策略
    "memory",     # Memory: 自动记忆/清理/导出
    "developer",  # Developer: Debug/Runtime日志/Trace
]

# 默认设置 (可解释)
DEFAULT_SETTINGS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "auto_start": False,       # 开机启动
        "window_position": None,   # 窗口位置
        "volume": 0.8,             # 音量
        "animation": True,         # 动画
    },
    "ai": {
        "model": "auto",           # 模型选择
        "api_config": {},          # API 配置
        "compute_policy": "auto",  # 算力策略
    },
    "memory": {
        "auto_memory": True,       # 自动记忆
        "auto_cleanup": False,     # 自动清理
        "export_enabled": True,    # 导出
    },
    "developer": {
        "debug_mode": False,       # Debug 模式
        "runtime_log": True,       # Runtime 日志
        "trace_view": True,        # Trace 查看
    },
}


class SettingsManagerError(Exception):
    """设置管理器异常"""


class SettingsManager:
    """设置管理器 (V10.1 Frontend)

    用法:
        sm = SettingsManager(path="settings.json")
        sm.set("basic", "volume", 0.9)
        v = sm.get("basic", "volume")
        dump = sm.dump()
    """

    def __init__(self, path: str = ""):
        self._lock = threading.RLock()
        self._path = path or str(
            Path(__file__).resolve().parent.parent.parent
            / "frontend_settings.json",
        )
        self._data: Dict[str, Dict[str, Any]] = {
            g: dict(DEFAULT_SETTINGS[g]) for g in SETTING_GROUPS
        }
        self._changes: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """加载持久化设置"""
        p = Path(self._path)
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for group in SETTING_GROUPS:
                if isinstance(saved.get(group), dict):
                    self._data[group].update(saved[group])
        except Exception as e:
            logger.warning(f"[Settings] 加载失败: {e}")

    def get(self, group: str, key: str, default: Any = None) -> Any:
        """读取设置"""
        with self._lock:
            return self._data.get(group, {}).get(key, default)

    def set(self, group: str, key: str, value: Any) -> Dict[str, Any]:
        """写入设置 (记录变更)"""
        with self._lock:
            if group not in SETTING_GROUPS:
                raise SettingsManagerError(
                    f"非法分组: {group} (可选: {SETTING_GROUPS})"
                )
            old = self._data[group].get(key)
            self._data[group][key] = value
            self._changes.append({
                "timestamp": time.time(),
                "group": group,
                "key": key,
                "old": old,
                "new": value,
            })
            if len(self._changes) > 500:
                self._changes = self._changes[-500:]
            self._save()
            return {
                "mode": "rule_based", "ok": True,
                "group": group, "key": key,
                "old": old, "new": value,
            }

    def set_group(self, group: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """批量写入一组设置"""
        with self._lock:
            if group not in SETTING_GROUPS:
                raise SettingsManagerError(
                    f"非法分组: {group}"
                )
            applied = 0
            for k, v in values.items():
                old = self._data[group].get(k)
                self._data[group][k] = v
                self._changes.append({
                    "timestamp": time.time(),
                    "group": group, "key": k,
                    "old": old, "new": v,
                })
                applied += 1
            self._save()
            return {
                "mode": "rule_based", "ok": True,
                "group": group, "applied": applied,
            }

    def dump(self) -> Dict[str, Dict[str, Any]]:
        """全部设置"""
        with self._lock:
            return {
                g: dict(self._data[g]) for g in SETTING_GROUPS
            }

    def changes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """变更记录"""
        with self._lock:
            return list(reversed(self._changes))[:limit]

    def _save(self) -> None:
        """持久化"""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Settings] 保存失败: {e}")

    def stats(self) -> Dict[str, Any]:
        """统计"""
        with self._lock:
            return {
                "mode": "rule_based",
                "path": self._path,
                "groups": list(self._data.keys()),
                "change_count": len(self._changes),
            }

    def clear(self) -> int:
        """清空变更记录 (测试隔离)"""
        with self._lock:
            n = len(self._changes)
            self._changes.clear()
            return n


__all__ = [
    "DEFAULT_SETTINGS",
    "SETTING_GROUPS",
    "SettingsManager",
    "SettingsManagerError",
]
