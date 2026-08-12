"""
YHLZ 前端 Settings 层 (设置管理)
"""
from __future__ import annotations

from frontend.settings.manager import (
    SETTING_GROUPS,
    SettingsManager,
    SettingsManagerError,
)

__all__ = [
    "SETTING_GROUPS",
    "SettingsManager",
    "SettingsManagerError",
]
