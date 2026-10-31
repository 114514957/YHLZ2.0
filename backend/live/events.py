"""S5 直播事件模型（台账 0679/0683）。

标准事件字段、幂等键与弱去重契约。显示名与文本一律按数据对待，
不得拼接成系统指令；B站弹幕与 QQ 身份互不继承。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

KINDS = ("chat", "gift", "super_chat", "guard", "system")
PRIORITIES = ("normal", "key", "owner")
ID_QUALITIES = ("native", "weak")
MAX_TEXT_CHARS = 500


def now_ms() -> int:
    return int(time.time() * 1000)


def weak_event_id(room_id: str, sender_id: str, source_ts: int, text: str) -> str:
    digest = hashlib.sha1(
        f"{room_id}|{sender_id}|{source_ts}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"weak:{digest}"


@dataclass
class LiveEvent:
    event_id: str
    platform: str = "bilibili"
    room_id: str = ""
    kind: str = "chat"
    sender_id: str = ""
    display_name: str = ""
    text: str = ""
    source_ts: int = 0
    received_at: int = 0
    reply_to: Optional[str] = None
    id_quality: str = "native"
    priority: str = "normal"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"bad kind: {self.kind}")
        if self.priority not in PRIORITIES:
            raise ValueError(f"bad priority: {self.priority}")
        if self.id_quality not in ID_QUALITIES:
            raise ValueError(f"bad id_quality: {self.id_quality}")
        if not self.event_id:
            if self.id_quality == "weak":
                self.event_id = weak_event_id(
                    self.room_id, self.sender_id, self.source_ts, self.text)
            else:
                raise ValueError("native event_id required")
        if not self.received_at:
            self.received_at = now_ms()
        self.text = str(self.text or "")[:MAX_TEXT_CHARS]
        self.display_name = str(self.display_name or "")[:64]

    @property
    def dedup_key(self) -> str:
        return f"{self.platform}:{self.room_id}:{self.event_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "platform": self.platform,
            "room_id": self.room_id, "kind": self.kind,
            "sender_id": self.sender_id, "display_name": self.display_name,
            "text": self.text, "source_ts": self.source_ts,
            "received_at": self.received_at, "reply_to": self.reply_to,
            "id_quality": self.id_quality, "priority": self.priority,
            "meta": dict(self.meta or {}),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LiveEvent":
        known = {k: data.get(k) for k in (
            "event_id", "platform", "room_id", "kind", "sender_id",
            "display_name", "text", "source_ts", "received_at", "reply_to",
            "id_quality", "priority")}
        known = {k: v for k, v in known.items() if v is not None}
        meta = data.get("meta")
        if isinstance(meta, dict):
            known["meta"] = meta
        return LiveEvent(**known)
