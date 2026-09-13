"""Turn Yuanheng's own memories/relations into labeled persona SFT samples
(ledger 0344; Atri-style: memory + emotion + relationship + scene per sample).

Sources: `cache/memstore/memstore.db` (l2_items) and `cache/entity_graph.db`
(entities/relations). For each memory, the local Gemma drafts 1-3 short
老爹-问/元亨-答 pairs that *use* that memory, in Yuanheng's voice. Labels:
memory_hook (memory topic), relationship (source: 老爹/agent/群聊), emotion,
scene. Output is a superset-schema JSONL (chatml + metadata).

Usage:
    python tools/persona_memory_dataset.py --limit 6 --out data/finetune/persona_memory.jsonl
    python tools/persona_memory_dataset.py --all --out data/finetune/persona_memory.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.golden_gen import _ask, _clean, _persona_prompt  # noqa: E402

MEM_DB = ROOT / "cache" / "memstore" / "memstore.db"
REL_DB = ROOT / "cache" / "entity_graph.db"
JUNK = re.compile(r"(测试|test|smoke|PING|r18|debug|开发经验（利贞）|啊啊|xxx|TODO)", re.I)


def load_memories(limit: int | None) -> list[dict]:
    if not MEM_DB.exists():
        return []
    con = sqlite3.connect(str(MEM_DB))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, type, kind, summary, source, importance, confidence FROM l2_items "
        "WHERE status='active' AND summary IS NOT NULL AND length(summary)>6 "
        "ORDER BY importance DESC, created_at DESC").fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        s = str(d.get("summary") or "").strip()
        if JUNK.search(s):
            continue
        out.append(d)
        if limit and len(out) >= limit:
            break
    return out


def _gen_prompt(mem: dict) -> str:
    return (
        "下面是你（元亨）的一条真实记忆：\n"
        f"「{mem['summary']}」\n"
        f"（类型={mem.get('type')}，类别={mem.get('kind')}，来源={mem.get('source')}）\n\n"
        "请生成 1-3 轮「老爹问 → 你答」的对话，考察你能自然想起并运用这条记忆。"
        "要求：短（每条回复 ≤60 字）、口语、具体、有情绪；不要罗列、不要元描述、"
        "不要每轮都反问；答案必须真的用到这条记忆。"
        '只输出 JSON 数组，每项 {"input":"老爹的话","output":"你的话","emotion":"情绪词","scene":"场景词"}，'
        "不要输出别的。"
    )


def _parse(txt: str) -> list[dict]:
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in arr if isinstance(arr, list) else []:
        if not isinstance(it, dict):
            continue
        u = str(it.get("input") or "").strip()
        a = _clean(str(it.get("output") or ""))
        if u and a:
            out.append({"input": u, "output": a,
                        "emotion": str(it.get("emotion") or "").strip(),
                        "scene": str(it.get("scene") or "").strip()})
    return out


SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体。回答时自然想起你的记忆，"
          "像人对朋友说话：短、口语、有情绪，不罗列、不解释机制。")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="元亨记忆/关系 → 结构化人格样本")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default="data/finetune/persona_memory.jsonl")
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()

    mems = load_memories(None if args.all else args.limit)
    print(f"[mem] 候选记忆 {len(mems)} 条")
    persona = _persona_prompt()
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    made = 0
    with out_path.open(mode, encoding="utf-8") as f:
        for i, mem in enumerate(mems, 1):
            try:
                txt = _ask(persona, _gen_prompt(mem), 0.8, 700)
                pairs = _parse(txt)
            except Exception as e:  # noqa: BLE001
                print(f"[fail] {mem['id']} {type(e).__name__}")
                continue
            hook = str(mem["summary"])[:24]
            for p in pairs:
                rec = {
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": p["input"]},
                        {"role": "assistant", "content": p["output"]},
                    ],
                    "instruction": f"你是元亨。你记得：{mem['summary']}",
                    "memory_hook": hook,
                    "emotion": p["emotion"],
                    "scene": p["scene"] or "回忆",
                    "relationship": str(mem.get("source") or ""),
                    "source": f"mem:{mem['id']}",
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                made += 1
            print(f"[{i}/{len(mems)}] {mem['id']} -> {len(pairs)} 对 | {hook}")
    print(json.dumps({"memories": len(mems), "pairs": made, "out": str(out_path)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
