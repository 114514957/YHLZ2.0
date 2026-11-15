# -*- coding: utf-8 -*-
"""台账分家（台账 1258·工作站第二片之二）。

老爹定论（1230）：「元亨的台账要明确标记，不能混」，且「日记外都可以」。
于是三个视图：
  · 元亨台账（橙）= 任务表 + 计划表 + 成长日志（**不含日记**）
  · 项目台账（蓝）= docs/上下文台账.md（只读最近若干条，带分页）
  · 日记（单独入口）= docs/元亨的日记.md
另外：项目台账里由元亨写的条目（含「元亨」且 actor 标记）可单独过滤。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PROJECT = DOCS / "上下文台账.md"
HER_FILES = {
    "任务表": DOCS / "元亨的任务表.md",
    "计划表": DOCS / "元亨的计划表.md",
    "成长日志": DOCS / "元亨的成长日志.md",
}
DIARY = DOCS / "元亨的日记.md"

__all__ = ["her_ledger", "project_ledger", "diary", "stats"]

_HEAD = re.compile(r"^#{1,3}\s+(.+)$")


def _tail_lines(p: Path, n: int) -> list[str]:
    if not p.exists():
        return []
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-n:]
    except Exception:  # noqa: BLE001
        return []


def _blocks(lines: list[str], limit: int) -> list[dict]:
    """把一段 markdown 按 `## ` 标题切块，取最后 limit 块。"""
    out, cur = [], {"title": "", "lines": []}
    for ln in lines:
        if ln.startswith("## "):
            if cur["title"] or cur["lines"]:
                out.append(cur)
            cur = {"title": ln[3:].strip(), "lines": []}
        else:
            cur["lines"].append(ln)
    if cur["title"] or cur["lines"]:
        out.append(cur)
    res = []
    for b in out[-limit:]:
        text = "\n".join(b["lines"]).strip()
        res.append({"title": b["title"] or "（无标题）", "text": text[:1200],
                    "chars": len(text)})
    if not any(r["title"] != "（无标题）" for r in res) and lines:
        # 该文件没有 `## ` 标题：整段取尾部若干行当一块（计划表/成长日志就是这种）
        tail = [ln for ln in lines if ln.strip()][-40:]
        text = "\n".join(tail)
        res = [{"title": "最近 %d 行" % len(tail), "text": text[:1600],
                "chars": len(text)}]
    return res


def her_ledger(limit: int = 6) -> dict:
    """元亨台账：任务/计划/成长（不含日记）。"""
    parts = {}
    for name, p in HER_FILES.items():
        parts[name] = {
            "exists": p.exists(),
            "chars": p.stat().st_size if p.exists() else 0,
            "blocks": _blocks(_tail_lines(p, 400), limit),
        }
    return {"kind": "her", "title": "元亨台账", "color": "orange", "parts": parts}


def diary(limit: int = 8) -> dict:
    return {"kind": "diary", "title": "元亨的日记", "color": "purple",
            "exists": DIARY.exists(),
            "chars": DIARY.stat().st_size if DIARY.exists() else 0,
            "blocks": _blocks(_tail_lines(DIARY, 500), limit)}


def project_ledger(limit: int = 8, offset: int = 0, only_her: bool = False) -> dict:
    """项目台账：最近若干条（分页）。only_her=True 只看元亨标记的/涉及元亨的。"""
    lines = _tail_lines(PROJECT, 4000)
    blocks = _blocks(lines, 400)
    if only_her:
        blocks = [b for b in blocks
                  if "元亨" in b["title"] or "actor=元亨" in b["text"]
                  or "【元亨】" in b["text"]]
    total = len(blocks)
    sel = blocks[::-1][offset:offset + limit]      # 倒序（新的在前）
    return {"kind": "project", "title": "利贞·项目台账", "color": "blue",
            "total": total, "offset": offset, "limit": limit,
            "items": [{"title": b["title"], "text": b["text"][:800]} for b in sel],
            "her_tagged": sum(1 for b in blocks if "元亨" in b["title"] or "元亨" in b["text"])}


def stats() -> dict:
    return {
        "project_lines": sum(1 for _ in io.open(PROJECT, encoding="utf-8", errors="replace"))
        if PROJECT.exists() else 0,
        "her": {n: (p.stat().st_size if p.exists() else 0) for n, p in HER_FILES.items()},
        "diary": DIARY.stat().st_size if DIARY.exists() else 0,
    }


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    h = her_ledger(3)
    print("元亨台账：", {k: (v["blocks"][0]["title"][:24] if v["blocks"] else None)
                     for k, v in h["parts"].items()})
    d = diary(2)
    print("日记：", d["chars"], "字｜最新:", d["blocks"][0]["title"][:30] if d["blocks"] else None)
    p = project_ledger(2)
    print("项目台账：总 %d 条｜元亨相关 %d 条" % (p["total"], p["her_tagged"]))
    for it in p["items"]:
        print("   -", it["title"][:50])
    print("统计：", json.dumps(stats(), ensure_ascii=False))
