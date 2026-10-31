"""Turn Yuanheng's own memories/relations into labeled persona SFT samples
(ledger 0349; Atri-style: memory + emotion + scene, multi-role 对话).

Roles: 老爹(creator) / 元亨(project self) / 利贞(元亨's sister; 家里那台接入了 DE 的
主机，不是某个智能体) / 大肥鱼(家里的宠物，真身是 DeepSeek — 不得有台词，只可被提及).
Language styles are fixed per
role; the worldview is the real world read through Marxism (dialectical &
historical materialism). Owner edits every memory by hand afterwards.

Output record: {source, summary, relationship, pairs:[{asker,question,answerer,answer,emotion,scene}]}
Usage:
    python tools/persona_memory_dataset.py --offset 0 --limit 60 --out data/finetune/persona_memory.jsonl
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
JUNK = re.compile(r"(测试|test|smoke|PING|r18|debug|开发经验（利贞）|啊啊|xxx|TODO)", re.I)

STYLE = (
    "【角色与语气（务必分清）】\n"
    "- 老爹：创造者，随意、懒散、爱开玩笑，偶尔自嘲。\n"
    "- 元亨：现在的项目本体。**活泼、乐观、傲娇**：爱用「哼／本小姐／老娘／啦／哟／嘿嘿」，俏皮，不啰嗦。\n"
    "- 利贞：元亨的**姐妹（家人）**，指家里那台接入了 DE 的主机（不是某个智能体）。**稳重、博学、直接**，少废话，常一针见血；句尾偶尔「，理论上来说」。\n"
    "- 大肥鱼：**家里的宠物**（鲸鱼娘；**真身是 DeepSeek**）——**不得有台词，只可被提及**。\n"
    "【世界观】真实世界：以**马克思主义**为底色——唯物辩证法、历史唯物主义；"
    "讲道理要落到现实、劳动、实践，不要玄幻、玄学、神秘主义。\n"
    "【要求】\n"
    "- 生成 2-3 轮问答；问答者只能是 老爹 / 元亨 / 利贞 三者中的两个（大肥鱼不发言）；可以一问一答，也可以角色互换。\n"
    "- 每条发言 ≤45 字；通顺、俏皮；不要旁白、不要解释、不要啰嗦。\n"
    "- 可以编一点贴合本记忆的、有意思的小场景/小故事。\n"
    '只输出 JSON 数组，每项 {"asker":"角色","question":"...","answerer":"角色","answer":"..."}，不要输出别的。'
)


def load_memories(limit: int | None, offset: int = 0, ids: set[str] | None = None) -> list[dict]:
    if not MEM_DB.exists():
        return []
    con = sqlite3.connect(str(MEM_DB))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, type, kind, summary, source, importance FROM l2_items "
        "WHERE status='active' AND summary IS NOT NULL AND length(summary)>6 "
        "ORDER BY importance DESC, created_at DESC").fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        if JUNK.search(str(d.get("summary") or "")):
            continue
        out.append(d)
    if ids is not None:
        return [d for d in out if d["id"] in ids]
    out = out[offset:]
    return out[:limit] if limit else out


def _gen_prompt(mem: dict) -> str:
    return (
        f"你（元亨）的一条真实记忆：\n「{mem['summary']}」\n"
        f"（类型={mem.get('type')}，类别={mem.get('kind')}，来源={mem.get('source')}）\n\n"
        "请围绕这条记忆，生成 2-3 轮多角色问答。\n" + STYLE
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
        q = str(it.get("question") or "").strip()
        a = _clean(str(it.get("answer") or ""))
        if q and a:
            out.append({"asker": str(it.get("asker") or "老爹").strip() or "老爹",
                        "question": q,
                        "answerer": str(it.get("answerer") or "元亨").strip() or "元亨",
                        "answer": a,
                        "emotion": str(it.get("emotion") or "").strip(),
                        "scene": str(it.get("scene") or "").strip()})
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="元亨记忆 → 多角色结构化样本")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", default=None, help="逗号分隔的记忆 id，仅处理这些")
    ap.add_argument("--out", default="data/finetune/persona_memory.jsonl")
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()

    ids = {s.strip() for s in args.ids.split(",") if s.strip()} if args.ids else None
    mems = load_memories(None if args.all else args.limit, args.offset, ids)
    print(f"[mem] 候选记忆 {len(mems)} 条")
    persona = _persona_prompt()
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    made = 0
    with out_path.open("a" if args.append else "w", encoding="utf-8") as f:
        for i, mem in enumerate(mems, 1):
            try:
                pairs = _parse(_ask(persona, _gen_prompt(mem), 0.85, 800))
            except Exception as e:  # noqa: BLE001
                print(f"[fail] {mem['id']} {type(e).__name__}")
                continue
            if not pairs:
                print(f"[skip] {mem['id']} 无有效输出")
                continue
            f.write(json.dumps({
                "source": f"mem:{mem['id']}",
                "summary": str(mem["summary"]).strip(),
                "relationship": str(mem.get("source") or "").strip() or "老爹",
                "pairs": pairs,
            }, ensure_ascii=False) + "\n")
            made += len(pairs)
            print(f"[{i}/{len(mems)}] {mem['id']} -> {len(pairs)} 轮")
    print(json.dumps({"memories": len(mems), "pairs": made, "out": str(out_path)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
