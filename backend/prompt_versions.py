# -*- coding: utf-8 -*-
"""提示词版本/回滚（台账 1256·工作站第二片之一）。

问题：工作台能改 26 块提示词，但**改坏了回不去**，也看不出"什么时候改了什么"。

做法：
  · 每次 `/prompt/set`（保存）前后，把**整个 overrides 文件**存一份快照到
    `config/prompt_overrides.history/<时间戳>.json`
  · 每个快照额外写一行索引 `index.jsonl`（ts / 改的块 / 前值摘要）
  · 提供 list / diff / restore：restore 只回滚**指定块**或整份
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUR = ROOT / "config" / "prompt_overrides.json"
HIST = ROOT / "config" / "prompt_overrides.history"
INDEX = HIST / "index.jsonl"
MAX_KEEP = 200

__all__ = ["snapshot", "versions", "restore_block", "restore_all", "diff_block"]


def _read_cur() -> dict:
    try:
        if CUR.exists():
            return json.loads(io.open(CUR, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        pass
    return {}


def snapshot(*, key: str = "", note: str = "") -> str:
    """存一份快照，返回时间戳字符串。"""
    try:
        HIST.mkdir(parents=True, exist_ok=True)
        data = _read_cur()
        ts = time.strftime("%Y%m%d_%H%M%S") + ("_%03d" % (int(time.time() * 1000) % 1000))
        p = HIST / ("%s.json" % ts)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        with io.open(INDEX, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "key": key, "note": note[:80],
                                "blocks": sorted(data)}, ensure_ascii=False) + "\n")
        # 只留最近 MAX_KEEP 份，防无限增长
        files = sorted(HIST.glob("*.json"))
        for old in files[:-MAX_KEEP]:
            try:
                old.unlink()
            except Exception:  # noqa: BLE001
                pass
        return ts
    except Exception:  # noqa: BLE001
        return ""


def versions(limit: int = 30, key: str = "") -> list[dict]:
    """最近的快照（可按块过滤）。"""
    rows: list[dict] = []
    try:
        if INDEX.exists():
            for ln in io.open(INDEX, encoding="utf-8", errors="replace"):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                if key and r.get("key") and r["key"] != key:
                    continue
                rows.append(r)
    except Exception:  # noqa: BLE001
        pass
    return rows[-limit:][::-1]


def _load_ts(ts: str) -> dict:
    p = HIST / ("%s.json" % ts)
    if not p.exists():
        return {}
    try:
        return json.loads(io.open(p, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        return {}


def diff_block(ts_a: str, ts_b: str, key: str) -> dict:
    a = str(_load_ts(ts_a).get(key) or "")
    b = str(_load_ts(ts_b).get(key) or "")
    return {"key": key, "a_len": len(a), "b_len": len(b),
            "changed": a != b, "a": a[:1200], "b": b[:1200]}


def restore_block(key: str, ts: str) -> dict:
    """把某块恢复到指定快照。返回 {ok, key, ts, changed}。"""
    snap = _load_ts(ts)
    if not snap or key not in snap:
        return {"ok": False, "error": "快照里没有这个块"}
    cur = _read_cur()
    before = str(cur.get(key) or "")
    target = str(snap.get(key) or "")
    if before == target:
        return {"ok": True, "key": key, "ts": ts, "changed": 0}
    snapshot(key=key, note="restore-before")
    if target:
        cur[key] = target
    else:
        cur.pop(key, None)
    CUR.parent.mkdir(parents=True, exist_ok=True)
    CUR.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "key": key, "ts": ts, "changed": 1}


def restore_all(ts: str) -> dict:
    snap = _load_ts(ts)
    if not snap:
        return {"ok": False, "error": "快照不存在"}
    snapshot(key="*", note="restore-all-before")
    CUR.parent.mkdir(parents=True, exist_ok=True)
    CUR.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "ts": ts, "blocks": len(snap)}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("当前 overrides 块数：", len(_read_cur()))
    print("已有快照：", len(versions(200)))
    for v in versions(5):
        print("  ", v)
