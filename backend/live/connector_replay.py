"""S5 本地弹幕回放器：把脚本事件按时间轴灌入 EventStore + TopicScheduler。

不连 B站、不推流、不发送任何平台消息；仅用于本地编排/延迟验证与证据生成。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from backend.live.event_store import EventStore
from backend.live.events import LiveEvent, now_ms
from backend.live.scheduler import TopicScheduler


class ReplayConnector:
    def __init__(self, store: EventStore, scheduler: Optional[TopicScheduler] = None,
                 *, speed: float = 1.0, pick_interval_ms: int = 1000,
                 sleep_fn: Callable[[float], None] = time.sleep):
        self.store = store
        self.scheduler = scheduler
        self.speed = max(0.01, float(speed))
        self.pick_interval_s = max(0.05, pick_interval_ms / 1000.0)
        self._sleep = sleep_fn

    @staticmethod
    def load_script(path: Path) -> list[dict[str, Any]]:
        text = Path(path).read_text(encoding="utf-8")
        if text.lstrip().startswith("["):
            items = json.loads(text)
        else:
            items = [json.loads(line) for line in text.splitlines() if line.strip()]
        items.sort(key=lambda item: int(item.get("offset_ms", 0)))
        return items

    def run(self, items: list[dict[str, Any]],
            on_event: Optional[Callable[[dict, LiveEvent], None]] = None,
            on_turn: Optional[Callable[[dict], None]] = None) -> dict[str, Any]:
        report: dict[str, Any] = {
            "started_ms": now_ms(), "speed": self.speed,
            "events": [], "turns": [], "dropped_dup": 0,
        }
        prev_offset_ms = 0
        next_pick_s = 0.0

        def drain_picks(offset_s: float, force: bool = False) -> None:
            nonlocal next_pick_s
            if self.scheduler is None:
                return
            while True:
                if not force and offset_s < next_pick_s:
                    break
                turn = self.scheduler.pick()
                if not turn:
                    break
                label = None if force else int(offset_s * 1000)
                turn = {"at_offset_ms": label, **turn}
                report["turns"].append(turn)
                if on_turn:
                    on_turn(turn)
                if force:
                    continue
                next_pick_s = offset_s + self.pick_interval_s

        for item in items:
            offset_s = max(0.0, int(item.get("offset_ms", 0)) / 1000.0)
            drain_picks(offset_s)
            delay_s = (offset_s - prev_offset_ms / 1000.0) / self.speed
            if delay_s > 0:
                self._sleep(delay_s)
            prev_offset_ms = int(offset_s * 1000)

            event = LiveEvent.from_dict(dict(item.get("event") or {}))
            ingest = self.store.ingest(event)
            offer = None
            if ingest["accepted"] and self.scheduler is not None:
                offer = self.scheduler.offer(event)
            else:
                report["dropped_dup"] += 0 if ingest["accepted"] else 1
            record = {
                "offset_ms": int(offset_s * 1000),
                "event_id": event.event_id,
                "sender": event.display_name,
                "text": event.text,
                "kind": event.kind,
                "accepted": ingest["accepted"],
                "offer": offer,
            }
            report["events"].append(record)
            if on_event:
                on_event(record, event)

        drain_picks(prev_offset_ms / 1000.0, force=True)
        report["finished_ms"] = now_ms()
        report["store"] = self.store.summary()
        if self.scheduler is not None:
            report["scheduler"] = self.scheduler.summary()
        return report


def demo_script() -> list[dict[str, Any]]:
    """内置演示脚本：普通弹幕、刷屏同题、礼物、主人控制、空白冷场。"""
    def chat(offset_ms: int, sender: str, text: str, **extra) -> dict[str, Any]:
        event = {"event_id": f"demo-{offset_ms}-{sender}", "room_id": "demo",
                 "kind": "chat", "sender_id": f"u-{sender}", "display_name": sender,
                 "text": text, "source_ts": 0}
        event.update(extra)
        return {"offset_ms": offset_ms, "event": event}

    items = [
        chat(0, "阿澈", "元亨你能看到弹幕吗"),
        chat(1500, "小满", "第一次来，主播是什么模型"),
        chat(3000, "路人甲", "你是真人吗"),
        chat(3400, "路人乙", "你是真人吗"),
        chat(3600, "路人丙", "你是真人吗？"),
        chat(6000, "舰长青禾", "加油", kind="guard", priority="key"),
        chat(7000, "小火龙", "送了一个小电视", kind="gift", priority="key"),
        chat(9000, "老爹", "元亨，做个自检。", priority="owner"),
        chat(10500, "小满", "利贞是谁呀？"),
        chat(12000, "阿澈", "刚才那个问题你还没回答"),
    ]
    return items
