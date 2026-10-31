"""P4 evidence matrix: 50-message group window, summary sources, chat degrade,
vision capability contract and sticker library scope (offline).

Usage:
    .venv\\Scripts\\python.exe tools\\qq_bridge_p4_matrix.py --out artifacts\\qq_lite\\p4_<id>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))


def case_group_history_50(base: pathlib.Path) -> dict:
    from backend.qq_group_store import GroupHistoryStore

    store = GroupHistoryStore(base / "group_history.db", bot_uin="3655185302",
                              turns=50)
    seq_m61 = 0
    for i in range(1, 61):        # m1..m60
        sender = "100" if i % 2 else "200"
        text = f"第{i}条" + ("有问题吗？" if i == 20 else "")
        store.add(group_id="A", message_id=f"m{i}", sender_id=sender,
                  sender_name="甲" if sender == "100" else "乙", text=text,
                  at=1000 + i)
    store.add(group_id="B", message_id="b1", sender_id="300", text="别群消息")
    store.add(group_id="A", message_id="m30", sender_id="100", text="dup")
    seq_m61 = store.add(group_id="A", message_id="m61", sender_id="100",
                        text="当前消息", at=2000)
    window = store.window("A", before_seq=seq_m61)
    ids = [m["message_id"] for m in window]
    window_ok = ids == [f"m{i}" for i in range(11, 61)]
    no_cross = all(m["message_id"].startswith("m") for m in window)
    block = store.context_block("A", before_seq=seq_m61)
    summary_ids_ok = all(("[m" in line) for line in block["summary"].splitlines()
                         if line.strip() and not line.startswith("["))
    # partial completeness for a short group
    store.add(group_id="C", message_id="c1", sender_id="1", text="hi")
    partial = store.context_block("C")
    partial_ok = partial["completeness"].startswith("partial")
    # backfill contract: unsupported + dedupe merge
    merge = store.merge_backfill([
        {"group_id": "A", "message_id": "m62", "sender_id": "100", "text": "补"},
        {"group_id": "A", "message_id": "m11", "sender_id": "100", "text": "dup"},
    ])
    merge_ok = merge["inserted"] == 1 and merge["supported"] is False
    (base / "summary_example.txt").write_text(block["summary"], encoding="utf-8")
    (base / "group_history_50.json").write_text(json.dumps({
        "window_size": len(ids), "first": ids[0] if ids else "",
        "last": ids[-1] if ids else "", "ids": ids,
        "completeness": block["completeness"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all((window_ok, no_cross, summary_ids_ok, partial_ok, merge_ok))
    return {"pass": bool(ok), "window_ok": window_ok,
            "window_size": len(ids), "first": ids[0] if ids else "",
            "last": ids[-1] if ids else "", "no_cross_group": no_cross,
            "summary_all_facts_have_source": summary_ids_ok,
            "partial_completeness": partial["completeness"],
            "backfill": merge}


def case_vision_capabilities(base: pathlib.Path) -> dict:
    from backend.qq_stickers import NullVision, StickerStore, vision_available

    store = StickerStore(base / "stickers.db", media_dir=base / "media")
    img = base / "x.jpg"
    img.write_bytes(b"fake-image-content")
    info = store.ingest(str(img), source_message_id="m1", source_kind="group",
                        source_id="1", scope="group:1")
    # no vision -> stays pending, job pending
    store.recognize(info["asset_id"], None)
    status = store.summary()
    torch_loaded = "torch" not in sys.modules and "funasr" not in sys.modules
    report = {
        "vision_configured": vision_available(),
        "judge": type(NullVision()).__name__,
        "asset_status": status.get("assets", {}),
        "job_status": status.get("jobs", {}),
        "torch_or_funasr_loaded": not torch_loaded,
    }
    (base / "vision_capabilities.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = (not vision_available() and status.get("assets", {}).get("pending") == 1
          and status.get("jobs", {}).get("pending") == 1 and torch_loaded)
    return {"pass": bool(ok), **report}


STICKER_RESULT = {
    "decision": "accept", "is_reusable_sticker": True, "confidence": 0.92,
    "description": "小猫躺平，表达累了或不想动",
    "keywords": ["累了", "躺平", "休息", "摸鱼"],
    "emotion": ["疲惫", "无奈"],
    "use_when": ["轻松闲聊中抱怨疲劳", "自嘲想休息"],
    "avoid_when": ["对方认真求助"], "ocr_text": "不想动了",
    "contains_private_info": False,
}


def _write(path: pathlib.Path, payload: bytes) -> None:
    path.write_bytes(payload)


def case_sticker_eval(base: pathlib.Path) -> dict:
    from backend.qq_stickers import StickerStore, validate_result

    store = StickerStore(base / "stickers.db", media_dir=base / "media")

    class FakeVision:
        name = "fake-vision-v1"
        available = True

        def judge(self, path):
            name = pathlib.Path(path).name
            if name.startswith("sticker"):
                return dict(STICKER_RESULT)
            if name.startswith("photo"):
                return {"decision": "reject", "is_reusable_sticker": False,
                        "confidence": 0.30, "description": "普通照片",
                        "keywords": ["照片", "风景", "记录"],
                        "emotion": [], "use_when": [], "avoid_when": [],
                        "contains_private_info": False}
            if name.startswith("shot"):
                data = dict(STICKER_RESULT)
                data["description"] = "包含个人信息的截图"
                data["contains_private_info"] = True
                return data
            return None

    judge = FakeVision()
    counts = {"active": 0, "rejected": 0, "review": 0, "pending": 0}
    for i in range(20):
        p = base / f"sticker{i}.jpg"
        _write(p, b"sticker-%d" % i)
        info = store.ingest(str(p), source_message_id=f"s{i}",
                            source_kind="group", source_id="1",
                            scope="group:1")
        counts[store.recognize(info["asset_id"], judge.judge(str(p)),
                               model_version=judge.name)] += 1
    for i in range(10):
        p = base / f"photo{i}.jpg"
        _write(p, b"photo-%d" % i)
        info = store.ingest(str(p), source_message_id=f"p{i}",
                            source_kind="group", source_id="1",
                            scope="group:1")
        counts[store.recognize(info["asset_id"], judge.judge(str(p)),
                               model_version=judge.name)] += 1
    for i in range(10):
        p = base / f"shot{i}.jpg"
        _write(p, b"shot-%d" % i)
        info = store.ingest(str(p), source_message_id=f"q{i}",
                            source_kind="group", source_id="1",
                            scope="group:1")
        counts[store.recognize(info["asset_id"], judge.judge(str(p)),
                               model_version=judge.name)] += 1
    counts = {k: v for k, v in counts.items() if v}

    # duplicate content: same bytes -> one asset, one recognition job
    dup = base / "sticker0-copy.jpg"
    _write(dup, b"sticker-0")
    dup_info = store.ingest(str(dup))
    summary = store.summary()
    one_asset_for_dup = dup_info["status"] == "duplicate"
    jobs_total = sum(summary["jobs"].values())

    # near-identical base with different text -> different sha, no merge
    near = base / "sticker0-near.jpg"
    _write(near, b"sticker-0-different-text")
    near_info = store.ingest(str(near))
    no_phash_merge = near_info.get("asset_id") != dup_info.get("asset_id")

    # invalid schema: command-like keywords are data, never executed; unknown
    # fields are rejected by the strict validator
    bad = dict(STICKER_RESULT)
    bad["keywords"] = ["#push", "rm -rf", "hack", "x"]
    valid_command_ok = validate_result(bad) is not None
    unknown = dict(STICKER_RESULT)
    unknown["shell"] = "rm -rf /"
    unknown_rejected = validate_result(unknown) is None

    # scope: group:1 asset not usable in group:2; global would be
    sample = store.search("group:1", "今天好累想摸鱼", limit=5)
    search_ok = 0 < len(sample) <= 5 and all(
        s["asset_id"].startswith("stk_") for s in sample)
    other_scope = store.search("group:2", "今天好累想摸鱼", limit=5)
    scope_ok = other_scope == []
    resolved = store.resolve(sample[0]["asset_id"], "group:1") if sample else ""
    resolve_other = store.resolve(sample[0]["asset_id"], "group:2") if sample else ""
    # cooldown after use
    if sample:
        store.record_use(sample[0]["asset_id"], "group:1", "confirmed")
        cooldown_ok = not store.can_send(sample[0]["asset_id"], "group:1")
    else:
        cooldown_ok = False
    unrelated = store.search("group:1", "完全不相关的技术术语xyz", limit=5)
    no_candidate_ok = unrelated == []

    report = {
        "accepted": counts.get("active", 0),
        "rejected": counts.get("rejected", 0),
        "review": counts.get("review", 0),
        "pending": counts.get("pending", 0),
        "duplicate_one_asset": one_asset_for_dup,
        "recognition_jobs_total": jobs_total,
        "near_same_base_not_merged": no_phash_merge,
        "command_like_keywords_are_data": valid_command_ok,
        "unknown_field_rejected": unknown_rejected,
        "search_candidates": len(sample),
        "resolve_in_scope": bool(resolved),
        "resolve_out_of_scope_empty": resolve_other == "",
        "cooldown_after_use": cooldown_ok,
        "no_candidate_no_send": no_candidate_ok,
        "assets": summary["assets"],
    }
    (base / "sticker_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = (counts.get("active") == 20 and counts.get("rejected") == 20
          and one_asset_for_dup and no_phash_merge
          and valid_command_ok and unknown_rejected and search_ok
          and scope_ok and bool(resolved) and cooldown_ok and no_candidate_ok)
    return {"pass": bool(ok), **report}


def case_summary_sources(base: pathlib.Path) -> dict:
    from backend.qq_group_store import GroupHistoryStore

    store = GroupHistoryStore(base / "summary.db", bot_uin="3655185302")
    for i in range(1, 13):
        store.add(group_id="G", message_id=f"m{i}",
                  sender_id="1" if i % 2 else "2",
                  sender_name="甲" if i % 2 else "乙",
                  text=("今晚开黑吗？" if i == 3 else f"第{i}条内容"),
                  at=100 + i)
    block = store.context_block("G")
    lines = [ln for ln in block["summary"].splitlines() if ln.strip()]
    fact_lines = [ln for ln in lines if ln.startswith("[m")]
    sources_ok = len(fact_lines) > 0 and all("[m" in ln for ln in fact_lines)
    window_ids = block["source_ids"]
    id_match = all(any(ln.startswith(f"[{mid}]") for ln in fact_lines)
                   for mid in window_ids[:3])
    question_ok = "[m3]" in block["summary"]
    (base / "summary_sources.json").write_text(json.dumps({
        "summary": block["summary"], "source_ids": window_ids,
        "fact_lines": fact_lines, "fact_lines_have_ids": sources_ok,
        "first_sources_referenced": id_match,
        "question_has_source": question_ok,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pass": bool(sources_ok and id_match and question_ok),
            "fact_lines_have_ids": sources_ok,
            "first_sources_referenced": id_match,
            "question_has_source": question_ok}


def case_chat_degrade(base: pathlib.Path) -> dict:
    os.environ["YHLZ_QQ_PROFILE"] = "lite"
    os.environ["YHLZ_QQ_STATE_DIR"] = str(base / "state")
    os.environ["YHLZ_QQ_DEV_DB"] = str(base / "state" / "dev_jobs.db")
    import qq_bot as qq
    from unittest.mock import AsyncMock

    calls = {"turn": 0}

    def fake_turn(*a, **k):
        calls["turn"] += 1
        return "chat-ok"

    old_turn = qq._daemon_turn
    qq._daemon_turn = fake_turn
    bridge = qq.QQBridge("unused", "3655185302", pathlib.Path("unused"),
                         masters={"2258374446"})
    bridge.log = lambda m: None
    bridge._say = AsyncMock()
    bridge._deliver = AsyncMock()
    bridge._daemon_ok = lambda: False

    class StubDev:
        def status_text(self):
            return "[利贞] 状态=idle（stub）"

    bridge._lite_dev = StubDev()
    qq._lite_dev = StubDev()

    def event(mid, sender, text):
        return {"post_type": "message", "message_type": "private",
                "user_id": sender, "message_id": mid,
                "message": [{"type": "text", "data": {"text": text}}]}

    async def scenario():
        await bridge.handle(None, event(1, "10086", "你好"))
        first = bridge._say.await_count
        await bridge.handle(None, event(2, "10086", "还在吗"))
        second = bridge._say.await_count
        await bridge.handle(None, event(3, "2258374446", "#devstatus"))
        status_sent = any("[利贞] 状态=" in str(c.args[2])
                          for c in bridge._say.await_args_list)
        bridge._daemon_ok = lambda: True
        await bridge.handle(None, event(4, "10086", "恢复了吗"))
        return first, second, status_sent

    try:
        first, second, status_sent = asyncio.run(scenario())
    finally:
        qq._daemon_turn = old_turn
    degrade_once = first == 1 and second == 1 and calls["turn"] == 1
    ok = degrade_once and status_sent
    report = {"degrade_reply_sent": first >= 1,
              "degrade_rate_limited": second == first,
              "daemon_turn_calls": calls["turn"],
              "control_channel_alive": status_sent,
              "recovered_without_restart": calls["turn"] == 1,
              "torch_loaded": "torch" in sys.modules}
    (base / "chat_degrade.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pass": bool(ok and not report["torch_loaded"]), **report}


def main() -> int:
    ap = argparse.ArgumentParser()
    run_id = time.strftime("p4_%Y%m%dT%H%M%S")
    ap.add_argument("--out",
                    default=str(_ROOT / "artifacts" / "qq_lite" / run_id))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for name, fn in (("group_history_50", case_group_history_50),
                     ("vision_capabilities", case_vision_capabilities),
                     ("sticker_eval", case_sticker_eval),
                     ("summary_sources", case_summary_sources),
                     ("chat_degrade", case_chat_degrade)):
        case_dir = out / name
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            cases[name] = fn(case_dir)
        except Exception as exc:  # noqa: BLE001
            import traceback

            cases[name] = {"pass": False,
                           "error": f"{type(exc).__name__}: {exc}",
                           "trace": traceback.format_exc()[-800:]}
    report = {"run_id": out.name,
              "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "profile": "lite",
              "pass": all(c.get("pass") for c in cases.values()),
              "cases": cases}
    (out / "p4_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[p4] out={out} pass={report['pass']}")
    for name, case in cases.items():
        print(f"[p4] {name} = {case.get('pass')}")
        if not case.get("pass") and case.get("error"):
            print(f"[p4]   error: {case['error']}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
