"""Batch-5 (ledger 0440): topic extraction from the raw QQ corpus.

Target: memory / thinking / cognition knowledge that the first QQ pass did
not surface. Pipeline: keyword-hit lines -> merged +-2 context windows ->
DeepSeek extraction -> quote-verified quality gate -> kb_add (dedupes).

State: cache/qqwatch/topic_state.json (window cursor; reruns continue).

Usage:
  python tools/qq_extract_topic.py --dry --windows 6
  python tools/qq_extract_topic.py --windows 60
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.qqextract import build_llm_turn, parse_llm_json  # noqa: E402
from backend.yuanheng_kb import kb_add, _norm  # noqa: E402

CORPUS = _ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"
STATE = _ROOT / "cache" / "qqwatch" / "topic_state.json"

KW = ("记忆", "思维", "思考", "推理", "反思", "认知", "复盘", "因果",
      "思维链", "元认知", "联想", "遗忘", "心智", "意识", "人格", "自主",
      "世界模型", "情绪", "直觉")
VALID_IMP = ("特高", "高", "中")

PROMPT = """你在做「记忆/思维/认知」专题知识抽取。输入是 QQ 技术群聊窗口（含上下文）。
抽取与这些主题相关的**可复用知识**：记忆系统与记忆结构、记忆召回/遗忘/衰减、思维与推理方式、认知架构、自主思考、人格与意识、因果推理、联想、元认知、世界模型。
丢弃：闲聊、情绪、广告、资源求问、无技术量的空谈。
输出纯 JSON（不要 markdown fence）：
{"items": [{"point": "一句话要点(≤80字)", "quote": "原文短引用(≤80字)", "cat": "tech|method", "importance": "特高|高|中"}]}
宁可少而精；没有就输出 {"items": []}。不要重复输出同一条。"""


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"processed_windows": 0}


def _save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def load_windows() -> list[dict]:
    """Merged +-2 windows around keyword-hit lines."""
    rows: list[dict] = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    anchors = [i for i, d in enumerate(rows)
               if any(k in str(d.get("text") or "") for k in KW)]
    spans: list[list[int]] = []
    for i in anchors:
        a, b = max(0, i - 2), min(len(rows) - 1, i + 2)
        if spans and a <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    out = []
    for a, b in spans:
        lines = []
        for d in rows[a:b + 1]:
            nick = str(d.get("nick") or d.get("user") or "?")
            tm = str(d.get("time") or "")
            txt = str(d.get("text") or "").replace("\n", " ")[:180]
            lines.append(f"[{nick} {tm}] {txt}")
        out.append({"span": [a, b], "text": "\n".join(lines)[:1600]})
    return out


def _verify_quote(quote: str, window: str) -> bool:
    q = _norm(quote)
    if len(q) < 4:
        return False
    w = _norm(window)
    if q in w:
        return True
    # tolerate punctuated/paraphrased quoting: 2-gram coverage >= 0.7
    grams = {q[i:i + 2] for i in range(len(q) - 1)}
    if not grams:
        return False
    hit = sum(1 for g in grams if g in w)
    return hit / len(grams) >= 0.7


async def run(args) -> dict:
    windows = load_windows()
    st = _load_state()
    start = int(st.get("processed_windows") or 0)
    todo = windows[start:start + max(1, args.windows)]
    if not todo:
        return {"status": "no-windows", "total": len(windows), "cursor": start}
    llm = build_llm_turn(max_tokens=1600)
    stored = dup = dropped = 0
    processed = 0
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        user = "\n\n---\n\n".join(w["text"] for w in chunk)
        try:
            resp = await llm([{"role": "system", "content": PROMPT},
                              {"role": "user", "content": user}], [])
            parsed = parse_llm_json(str(resp.get("content") or ""))
            items = parsed.get("items") or []
        except Exception as exc:  # noqa: BLE001
            print(f"[chunk {i}] llm/parse fail {type(exc).__name__}")
            items = []
        seen = set()
        for it in items[:12]:
            point = str(it.get("point", "")).strip()
            quote = str(it.get("quote", "")).strip()
            imp = str(it.get("importance", "中")).strip()
            cat = str(it.get("cat", "tech")).strip()
            if len(point) < 8 or not quote:
                dropped += 1
                continue
            key = _norm(point)[:60]
            if key in seen:
                dup += 1
                continue
            seen.add(key)
            if not any(_verify_quote(quote, w["text"]) for w in chunk):
                dropped += 1
                continue
            imp = imp if imp in VALID_IMP else "中"
            cat = cat if cat in ("tech", "method", "word", "skill") else "tech"
            first = chunk[0]["span"][0]
            src = f"qq-topic:{first}"
            if args.dry:
                print(f"[dry] 【{imp}】{point[:70]}")
                stored += 1
                continue
            res = kb_add(summary=f"【{imp}】{point[:120]}", category=cat,
                         source=src, detail=f"{quote}（窗口行 {first}）")
            if res.startswith("已入库"):
                stored += 1
            else:
                dup += 1
        processed += len(chunk)
        print(f"[{min(i + args.batch, len(todo))}/{len(todo)} windows] "
              f"stored={stored} dup={dup} dropped={dropped}")
    if not args.dry:
        _save_state({"processed_windows": start + processed,
                     "saved_at": time.strftime("%Y-%m-%d %H:%M")})
    return {"status": "ok", "total_windows": len(windows),
            "processed": processed, "stored": stored, "dup": dup,
            "dropped": dropped, "cursor": start + processed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=60)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    res = asyncio.run(run(a))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
