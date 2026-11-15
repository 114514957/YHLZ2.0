# -*- coding: utf-8 -*-
"""2a 逐题对拍数据层：两版评测 json → 修好/新挂/持续失败，带题目原文。"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"

__all__ = ["compare", "tags", "question_of"]


def _load(tag: str) -> dict:
    p = CACHE / ("eval_%s.json" % tag)
    if not p.exists():
        raise FileNotFoundError("没有这版评测：%s" % tag)
    return json.loads(io.open(p, encoding="utf-8").read())


def tags(limit: int = 12) -> list[dict]:
    out = []
    for p in sorted(CACHE.glob("eval_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(io.open(p, encoding="utf-8").read())
            if not isinstance(d.get("detail"), dict):
                continue          # eval_state.json 之类不是评测结果
            per = d.get("detail", {}).get("persona", [])
            grp = d.get("detail", {}).get("group", [])
            out.append({"tag": p.stem.replace("eval_", ""),
                        "persona": sum(1 for r in per if r.get("ok")),
                        "persona_n": len(per),
                        "group": sum(1 for r in grp if r.get("ok")),
                        "group_n": len(grp),
                        "mtime": p.stat().st_mtime})
        except Exception:  # noqa: BLE001
            continue
    return out


_QB = None
_QG = None


def question_of(iid: str) -> str:
    """取题目原文（persona 用 q，group 用最后一条用户消息）。"""
    global _QB, _QG
    try:
        if _QB is None:
            import persona_bank as PB
            _QB = {e["id"]: (e.get("q") or e.get("scene") or "") for e in PB.PERSONA_BANK}
        if _QG is None:
            import group_bank as GB
            _QG = {e["id"]: (e.get("scene") or "") for e in GB.GROUP_BANK}
    except Exception:  # noqa: BLE001
        return ""
    return str(_QB.get(iid) or _QG.get(iid) or "")


def compare(tag_a: str, tag_b: str) -> dict:
    """A=旧、B=新。返回 fixed（A挂B过）/broke（A过B挂）/both_fail（都挂）。"""
    a, b = _load(tag_a), _load(tag_b)
    out = {"a": tag_a, "b": tag_b, "suites": {}}
    for suite in ("persona", "group"):
        ra = {r["id"]: bool(r.get("ok")) for r in a.get("detail", {}).get(suite, [])}
        rb = {r["id"]: bool(r.get("ok")) for r in b.get("detail", {}).get(suite, [])}
        ids = [i for i in ra if i in rb]
        fixed = [i for i in ids if not ra[i] and rb[i]]
        broke = [i for i in ids if ra[i] and not rb[i]]
        both_fail = [i for i in ids if not ra[i] and not rb[i]]
        same = [i for i in ids if ra[i] and rb[i]]
        out["suites"][suite] = {
            "a_ok": sum(1 for i in ids if ra[i]), "b_ok": sum(1 for i in ids if rb[i]),
            "n": len(ids),
            "delta": sum(1 for i in ids if rb[i]) - sum(1 for i in ids if ra[i]),
            "fixed": [{"id": i, "q": question_of(i)} for i in fixed],
            "broke": [{"id": i, "q": question_of(i)} for i in broke],
            "both_fail": [{"id": i, "q": question_of(i)} for i in both_fail],
            "same_ok": len(same),
        }
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ts = tags(8)
    print("可用版本：", [t["tag"] for t in ts])
    if len(ts) >= 2:
        r = compare(ts[1]["tag"], ts[0]["tag"])
        for s, d in r["suites"].items():
            print("\n[%s] %s → %s：%d → %d（%+d）"
                  % (s, r["a"], r["b"], d["a_ok"], d["b_ok"], d["delta"]))
            print("  修好:", [x["id"] for x in d["fixed"]])
            print("  新挂:", [x["id"] for x in d["broke"]])
            for x in d["broke"][:3]:
                print("    - %s %s" % (x["id"], x["q"][:40]))
