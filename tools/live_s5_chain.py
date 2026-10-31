"""S5 全链本地回放：弹幕 → 去重/聚合/选题 → Gemma → TTS 入队（可选）。

不连 B站、不推流；未武装 live 服务时 TTS 仅入队并 TTL 过期，不会出声。
用法：
  python tools/live_s5_chain.py --demo --speed 6 --out artifacts/live_s5/chain_report.json
  python tools/live_s5_chain.py --demo --no-llm --tts off
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.connector_replay import ReplayConnector, demo_script  # noqa: E402
from backend.live.conversation import (  # noqa: E402
    LiveConversation, LiveConversationConfig, LiveConversationError,
)
from backend.live.event_store import EventStore  # noqa: E402
from backend.live.scheduler import TopicScheduler  # noqa: E402
from backend.live.tts_bridge import LiveTTSBridge  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="YHLZ S5 全链本地回放")
    parser.add_argument("--script")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--speed", type=float, default=4.0)
    parser.add_argument("--pick-interval-ms", type=int, default=800)
    parser.add_argument("--ttl", type=float, default=30.0)
    parser.add_argument("--capacity", type=int, default=100)
    parser.add_argument("--context-raw", type=int, default=6)
    parser.add_argument("--lm-url", default="http://127.0.0.1:8081")
    parser.add_argument("--model", default="gemma-4-e4b")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--tts", choices=["off", "enqueue"], default="enqueue")
    parser.add_argument("--keep-queue", action="store_true")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--events-log", default=str(ROOT / "cache" / "live" / "danmaku_events.jsonl"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "live_s5" / "chain_report.json"))
    args = parser.parse_args()

    if args.no_llm and args.tts == "enqueue":
        parser.error("--no-llm 时没有回复文本，请配合 --tts off")

    items = demo_script() if args.demo else ReplayConnector.load_script(Path(args.script))
    store = EventStore(path=Path(args.events_log), persist=True)
    scheduler = TopicScheduler(ttl_s=args.ttl, capacity=args.capacity)
    connector = ReplayConnector(store, scheduler, speed=args.speed,
                                pick_interval_ms=args.pick_interval_ms)
    conversation = None if args.no_llm else LiveConversation(LiveConversationConfig(
        base_url=args.lm_url, model=args.model, context_raw=args.context_raw))
    bridge = LiveTTSBridge.from_config() if args.tts == "enqueue" else None

    report: dict = {"started_ms": int(time.time() * 1000), "turns": [],
                    "config": {"no_llm": args.no_llm, "tts": args.tts,
                               "speed": args.speed, "lm_url": args.lm_url}}
    stop_after = max(1, args.max_turns)

    def on_turn(turn: dict) -> None:
        if len(report["turns"]) >= stop_after:
            return
        record: dict = {"turn": turn}
        reply = None
        if conversation is not None:
            try:
                llm = conversation.respond(turn, store.recent_raw(args.context_raw))
                record["llm"] = {"llm_ms": llm["llm_ms"], "usage": llm["usage"]}
                reply = llm["text"]
                record["reply"] = reply
            except LiveConversationError as exc:
                record["llm_error"] = str(exc)
        if bridge is not None and reply:
            record["tts"] = bridge.speak(reply)
        report["turns"].append(record)
        label = turn.get("turn_id")
        status = record.get("llm_error") or (reply or "(no reply)")
        print(f"[{label}] {turn.get('kind')} -> {status}")

    replay = connector.run(items, on_turn=on_turn)
    if bridge is not None and not args.keep_queue:
        report["clear"] = bridge.clear()

    report["replay"] = {"events": len(replay["events"]),
                        "dropped_dup": replay["dropped_dup"],
                        "turns_total": len(replay["turns"])}
    report["store"] = replay["store"]
    report["scheduler"] = replay["scheduler"]
    report["llm_total_ms"] = sum(t.get("llm", {}).get("llm_ms", 0) for t in report["turns"])
    report["tts_total_synth_ms"] = sum(t.get("tts", {}).get("total_synth_ms", 0)
                                       for t in report["turns"])
    report["finished_ms"] = int(time.time() * 1000)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "turns": len(report["turns"]),
        "llm_total_ms": report["llm_total_ms"],
        "tts_total_synth_ms": report["tts_total_synth_ms"],
        "scheduler": report["scheduler"]["counters"],
        "out": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
