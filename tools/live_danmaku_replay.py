"""S5 本地弹幕回放 CLI（不连 B站、不推流）。

用法：
  python tools/live_danmaku_replay.py --demo --speed 4 --out artifacts/live_s5/replay_report.json
  python tools/live_danmaku_replay.py --script cache/live/danmaku_script.jsonl --pick-interval-ms 800
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.connector_replay import ReplayConnector, demo_script  # noqa: E402
from backend.live.event_store import EventStore  # noqa: E402
from backend.live.scheduler import TopicScheduler  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="YHLZ S5 弹幕本地回放")
    parser.add_argument("--script", help="JSONL 脚本（每行 offset_ms+event）")
    parser.add_argument("--demo", action="store_true", help="使用内置演示脚本")
    parser.add_argument("--speed", type=float, default=1.0, help="回放倍速（默认 1.0）")
    parser.add_argument("--pick-interval-ms", type=int, default=1000)
    parser.add_argument("--ttl", type=float, default=30.0)
    parser.add_argument("--capacity", type=int, default=100)
    parser.add_argument("--cold-idle", type=float, default=30.0)
    parser.add_argument("--events-log", default=str(ROOT / "cache" / "live" / "danmaku_events.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "live_s5" / "replay_report.json"))
    args = parser.parse_args()

    if args.demo:
        items = demo_script()
    elif args.script:
        items = ReplayConnector.load_script(Path(args.script))
    else:
        parser.error("需要 --demo 或 --script")

    store = EventStore(path=Path(args.events_log), persist=True)
    scheduler = TopicScheduler(ttl_s=args.ttl, capacity=args.capacity,
                               cold_idle_s=args.cold_idle)
    connector = ReplayConnector(store, scheduler, speed=args.speed,
                                pick_interval_ms=args.pick_interval_ms)

    def on_event(record: dict, _event) -> None:
        mark = "OK " if record["accepted"] else "DUP"
        print(f"[{record['offset_ms']:>6}ms] {mark} {record['sender']}: {record['text']}")

    def on_turn(turn: dict) -> None:
        label = "final" if turn.get("at_offset_ms") is None else f"{turn['at_offset_ms']:>6}ms"
        if turn.get("kind") == "cold":
            print(f"[{label}] COLD idle={turn.get('idle_s')}s")
        else:
            print(f"[{label}] TURN {turn['turn_id']} "
                  f"priority={turn['priority']} sources={turn['source_count']} "
                  f"topic={turn['topic_text']!r}")

    report = connector.run(items, on_event=on_event, on_turn=on_turn)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "events": len(report["events"]),
        "turns": len(report["turns"]),
        "store": report["store"]["counters"],
        "scheduler": report["scheduler"]["counters"],
        "out": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
