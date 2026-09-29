"""Offline OneBot message replay tool for dedup testing (Step 4 prep).

Replays saved OneBot messages through the qq_bot dedup logic without
executing side effects.  Verifies duplicate message_id is rejected.

Usage:
    python tools/qq_replay_test.py
"""
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MESSAGE_DEDUP_TTL = 15 * 60  # 15 min TTL
MESSAGE_DEDUP_LIMIT = 2048


class DedupSimulator:
    """Simulates the qq_bot dedup logic for offline testing."""

    def __init__(self):
        self._seen: OrderedDict[tuple, float] = OrderedDict()

    def is_duplicate(self, message_id: str, user_id: str = "",
                     group_id: str = "", now: float = 0.0) -> bool:
        if not message_id:
            return True  # legacy events without IDs cannot be deduplicated
        key = (str(user_id or ""), str(group_id or ""), str(message_id))
        while self._seen:
            first, ts = next(iter(self._seen.items()))
            if now - ts < MESSAGE_DEDUP_TTL:
                break
            self._seen.pop(first)
        if key in self._seen:
            return True
        self._seen[key] = now
        while len(self._seen) > MESSAGE_DEDUP_LIMIT:
            self._seen.popitem(last=False)
        return False


def run_replay() -> dict:
    sim = DedupSimulator()
    test_msgs = [
        {"message_id": "test_001", "user_id": "2258374446", "group_id": "",
         "text": "第一条消息", "now": 1000.0},
        {"message_id": "test_001", "user_id": "2258374446", "group_id": "",
         "text": "第一条消息（重复）", "now": 1001.0},
        {"message_id": "test_002", "user_id": "2258374446", "group_id": "",
         "text": "第二条消息", "now": 1002.0},
        {"message_id": "test_003", "user_id": "12345", "group_id": "1094579571",
         "text": "群消息", "now": 1003.0},
        {"message_id": "test_003", "user_id": "12345", "group_id": "1094579571",
         "text": "群消息（重复）", "now": 1004.0},
        {"message_id": "test_004", "user_id": "2258374446", "group_id": "",
         "text": "不同用户同ID", "now": 1005.0},
        {"message_id": "test_004", "user_id": "99999", "group_id": "",
         "text": "不同用户同ID（应通过）", "now": 1006.0},
        {"message_id": "", "user_id": "2258374446", "group_id": "",
         "text": "无ID消息（应被拒）", "now": 1007.0},
    ]
    results = []
    for msg in test_msgs:
        is_dup = sim.is_duplicate(
            msg["message_id"], msg["user_id"], msg["group_id"], msg["now"])
        results.append({
            "message_id": msg["message_id"] or "(empty)",
            "user_id": msg["user_id"],
            "group_id": msg["group_id"] or "(dm)",
            "is_duplicate": is_dup,
            "processed": not is_dup,
        })
    return {
        "total": len(results),
        "processed": sum(1 for r in results if r["processed"]),
        "duplicates_rejected": sum(1 for r in results if r["is_duplicate"]),
        "results": results,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = run_replay()
    print(json.dumps(report, ensure_ascii=False, indent=1))

    errors = []
    # test_001 duplicate rejected
    if not report["results"][1]["is_duplicate"]:
        errors.append("test_001 duplicate NOT rejected")
    # test_003 duplicate rejected
    if not report["results"][4]["is_duplicate"]:
        errors.append("test_003 duplicate NOT rejected")
    # test_004 different users same ID should pass
    if report["results"][6]["is_duplicate"]:
        errors.append("test_004 different-user same-ID rejected (should pass)")
    # empty ID rejected
    if not report["results"][7]["is_duplicate"]:
        errors.append("empty message_id NOT rejected")

    if errors:
        print("ERRORS:", errors)
        return 1
    print("PASS: dedup correctly rejected duplicates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
