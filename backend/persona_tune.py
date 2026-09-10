"""Persona tuning (ledger 0226): propose OCEAN five-dim tweaks, owner approves.

Never auto-writes persona. Flow: propose() reads persona_dims + recent memory,
asks the local model for <=2 small suggestions (text-level, 限幅: keep the
original meaning, only adjust emphasis/wording), writes
cache/persona_tuning_pending.json + notifies. apply() applies approved ids to
data/persona_dims.json (version bump + history).
"""
from __future__ import annotations

import json
import pathlib
import time
import urllib.request

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
DIMS_FILE = _PROJECT / "data" / "persona_dims.json"
PENDING = _PROJECT / "cache" / "persona_tuning_pending.json"


def _dims() -> list[str]:
    try:
        d = json.loads(DIMS_FILE.read_text(encoding="utf-8"))
        return [str(x) for x in (d.get("dims") or [])][:5]
    except Exception:
        return []


def propose() -> dict:
    dims = _dims()
    if not dims:
        return {"ok": False, "reason": "no dims"}
    try:
        import sqlite3

        con = sqlite3.connect(str(_PROJECT / "cache" / "memstore" / "memstore.db"))
        rows = con.execute(
            "SELECT summary FROM l2_items WHERE status='active' "
            "ORDER BY created_at DESC LIMIT 25").fetchall()
        con.close()
    except Exception:
        rows = []
    recent = "\n".join(f"- {r[0][:100]}" for r in rows)
    prompt = (
        "你是元亨的人格维护助手。下面是当前 OCEAN 五维人格描述（顺序固定："
        "开放求新/尽责自持/生动有度/协作利他/稳定温和）与最近经历。若经历"
        "显示某维度需要微调（仅调整措辞/侧重点，保持原意与幅度克制），给出"
        "最多 2 条建议；不需要就空数组。只输出 JSON："
        '[{"index":0-4,"new":"新的描述句","reason":"依据"}]\n\n'
        "当前五维：\n" + "\n".join(f"{i}. {d}" for i, d in enumerate(dims))
        + "\n\n最近经历：\n" + (recent or "(无)"))
    try:
        body = json.dumps({"messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 700, "temperature": 0.3,
                           "reasoning_effort": "none"}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8081/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
            txt = str(d["choices"][0]["message"].get("content") or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": type(exc).__name__}
    import re

    m = re.search(r"\[.*\]", txt, re.S)
    items = []
    if m:
        try:
            for it in json.loads(m.group(0)) or []:
                idx = int(it.get("index", -1))
                new = str(it.get("new", "")).strip()
                if 0 <= idx < len(dims) and new and new != dims[idx]:
                    items.append({"index": idx, "old": dims[idx],
                                  "new": new[:120],
                                  "reason": str(it.get("reason", ""))[:80],
                                  "id": f"pt_{int(time.time())}_{idx}"})
        except Exception:
            items = []
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    items = items[:2]  # 限幅：每次最多 2 条
    PENDING.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    if items:
        try:
            from backend.target_daemon import notify_push

            notify_push(f"人格调优建议 {len(items)} 条待批（/persona-apply 应用）")
        except Exception:
            pass
    return {"ok": True, "items": items}


def pending() -> list[dict]:
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:
        return []


def apply(ids: list[str] | None = None) -> dict:
    """Apply approved suggestion ids to persona_dims.json (version+history)."""
    items = pending()
    if not items:
        return {"applied": 0}
    keep = [it for it in items if ids and it.get("id") in ids]
    if not keep:
        return {"applied": 0}
    try:
        d = json.loads(DIMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"applied": 0}
    dims = [str(x) for x in (d.get("dims") or [])][:5]
    for it in keep:
        i = int(it["index"])
        if 0 <= i < len(dims):
            dims[i] = str(it["new"])
    d["dims"] = dims
    d["version"] = int(d.get("version", 1)) + 1
    hist = d.get("history") or []
    hist.append({"ts": int(time.time()), "applied": [it["id"] for it in keep]})
    d["history"] = hist[-20:]
    DIMS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    rest = [it for it in items if it.get("id") not in {k["id"] for k in keep}]
    PENDING.write_text(json.dumps(rest, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    return {"applied": len(keep), "version": d["version"]}
