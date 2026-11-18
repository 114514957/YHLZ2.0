"""记忆图谱选择器（2026-11-18）：v2 默认，`YHLZ_KG_V2=0` 回滚旧的 entity_graph+PPR。

只做两件事：给一轮对话拼「已知事实」提示块；把一轮问答抽进图。
v1 与 v2 的数据库完全分开（cache/entity_graph.db vs cache/kg/kg_v2.db），互不迁移。
"""
from __future__ import annotations

import os

__all__ = ["v2_enabled", "context_for", "ingest"]


def v2_enabled() -> bool:
    return str(os.getenv("YHLZ_KG_V2", "1")).strip().lower() not in ("0", "false", "off", "no")


def context_for(text: str) -> str:
    if v2_enabled():
        try:
            from backend import kg_v2

            return kg_v2.context_for(text)
        except Exception:  # noqa: BLE001
            return ""
    parts = []
    try:
        from backend import entity_graph

        eg = entity_graph.context_for(text)
        if eg:
            parts.append(eg)
    except Exception:  # noqa: BLE001
        pass
    try:
        from backend import associations

        asc = associations.context_for(text)
        if asc:
            parts.append(asc)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


async def ingest(text: str, source: str = "turn") -> int:
    if v2_enabled():
        try:
            from backend import kg_v2

            return await kg_v2.ingest(text, source=source)
        except Exception:  # noqa: BLE001
            return 0
    try:
        from backend import entity_graph

        return await entity_graph.ingest_text(text)
    except Exception:  # noqa: BLE001
        return 0
