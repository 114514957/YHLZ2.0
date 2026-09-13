"""Editable memory-sample doc <-> jsonl (ledger 0349; multi-role format).

Samples live in a human-editable Markdown doc (`docs/素材/记忆样本.md`) grouped
by memory, with role-labeled turns (owner edits every memory by hand):

    ## mem-1
    - source: mem:mem_xxx
    - summary: <记忆>
    - relationship: 老爹
    - status: keep
    ### 老爹问1
    ...
    ### 元亨答1
    ...
    ### 利贞问2
    ...
    ### 老爹答2
    ...

Commands:
    python tools/memory_samples.py md [--keep-first N]   # jsonl -> doc
    python tools/memory_samples.py jsonl                 # edited doc -> jsonl
    python tools/memory_samples.py list
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JSONL = ROOT / "data" / "finetune" / "persona_memory.jsonl"
DOC = ROOT / "docs" / "素材" / "记忆样本.md"
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体。回答时自然想起你的记忆，"
          "像人对朋友说话：短、口语、有情绪，不罗列、不解释机制。")

HEADER = ("# 元亨记忆样本（逐条校订）\n\n"
          "> 每条记忆一个 `## mem-N` 块；`### <角色>问K` / `### <角色>答K` 成对，"
          "角色可为 老爹/元亨/利贞/大肥鱼。\n"
          "> 改完把 `status` 设 `keep`；不要的设 `drop`。回读：`memory_samples.py jsonl`。\n")
BLOCK_RE = re.compile(r"^##\s+mem-(\d+)\s*$", re.MULTILINE)
TURN_RE = re.compile(r"^###\s*([^\n#]*?)(问|答)\s*(\d+)\s*$", re.MULTILINE)


def _load_records() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not JSONL.exists():
        return out
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("source"):
            out[r["source"]] = r
    return out


def _render_block(idx: int, r: dict) -> str:
    lines = [f"## mem-{idx}", f"- source: {r['source']}",
             f"- summary: {r.get('summary', '')}",
             f"- relationship: {r.get('relationship', '')}",
             "- status: candidate"]
    for k, p in enumerate(r.get("pairs", []), 1):
        lines.append(f"### {p.get('asker', '老爹')}问{k}")
        lines.append(p.get("question", ""))
        lines.append(f"### {p.get('answerer', '元亨')}答{k}")
        lines.append(p.get("answer", ""))
    return "\n".join(lines)


def md(args: argparse.Namespace) -> int:
    records = _load_records()
    keep_n = args.keep_first or 0
    prefix, kept_sources, next_i = HEADER, set(), 1
    if DOC.exists() and keep_n:
        text = DOC.read_text(encoding="utf-8")
        head = BLOCK_RE.split(text)[0]
        parts = BLOCK_RE.split(text)
        blocks = sorted((int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2))
        kept = [(n, b) for n, b in blocks if n <= keep_n]
        composed = head.rstrip()
        for n, b in kept:
            composed += f"\n\n## mem-{n}\n{b.strip()}"
            m = re.search(r"^[ \t]*-[ \t]*source[ \t]*:[ \t]*(.*)$", b, re.MULTILINE)
            if m:
                kept_sources.add(m.group(1).strip())
        prefix = composed + "\n"
        next_i = (max((n for n, _ in kept), default=0)) + 1
    new_blocks = []
    for src, r in records.items():
        if src in kept_sources:
            continue
        new_blocks.append(_render_block(next_i, r))
        next_i += 1
    DOC.write_text(prefix + "\n" + "\n\n".join(new_blocks) + ("\n" if new_blocks else ""),
                   encoding="utf-8")
    print(f"[ok] 保留 {len(kept_sources)} 块，新增 {len(new_blocks)} 条记忆 -> {DOC.relative_to(ROOT)}")
    return 0


def load_memory_samples(path: Path | None = None) -> list[dict]:
    path = path or DOC
    if not path.exists():
        return []
    parts = BLOCK_RE.split(path.read_text(encoding="utf-8"))
    out = []
    for i in range(1, len(parts), 2):
        bid, body = f"mem-{parts[i]}", parts[i + 1]
        meta = {}
        for m in re.finditer(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", body, re.MULTILINE):
            meta[m.group(1).lower()] = m.group(2).strip()
        turns = {}
        matches = list(TURN_RE.finditer(body))
        for j, m in enumerate(matches):
            role = m.group(1).strip()
            kind = m.group(2)
            num = int(m.group(3))
            start = m.end()
            end = matches[j + 1].start() if j + 1 < len(matches) else len(body)
            turns.setdefault(num, {})[kind] = (role, body[start:end].strip())
        for num in sorted(turns):
            q = turns[num].get("问")
            a = turns[num].get("答")
            if not (q and a):
                continue
            out.append({"block": bid, "source": meta.get("source", ""),
                        "summary": meta.get("summary", ""),
                        "relationship": meta.get("relationship", ""),
                        "status": meta.get("status", "keep"),
                        "asker": q[0] or "老爹", "question": q[1],
                        "answerer": a[0] or "元亨", "answer": a[1]})
    return out


def jsonl(args: argparse.Namespace) -> int:
    recs = load_memory_samples()
    kept = [r for r in recs if r["status"] not in ("drop", "不要", "这条不要")]
    out = ROOT / "data" / "finetune" / "persona_memory_reviewed.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in kept:
            rec = {"source": r["source"], "summary": r["summary"], "block": r["block"],
                   "relationship": r["relationship"] or "老爹",
                   "asker": r["asker"], "question": r["question"],
                   "answerer": r["answerer"], "answer": r["answer"]}
            if r["answerer"] == "元亨":
                rec["messages"] = [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": r["question"]},
                    {"role": "assistant", "content": r["answer"]},
                ]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[ok] 校订保留 {len(kept)}/{len(recs)} 轮 -> {out.relative_to(ROOT)}")
    return 0


def lst(_: argparse.Namespace) -> int:
    recs = load_memory_samples()
    print(f"轮数 {len(recs)}；记忆 {len({r['block'] for r in recs})} 条")
    for who in ("爹", "元亨", "利贞", "大肥鱼"):
        pass
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="记忆样本可编辑文档")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_md = sub.add_parser("md")
    p_md.add_argument("--keep-first", type=int, default=0,
                      help="保留前 N 块（人工已改），其余重建")
    sub.add_parser("jsonl")
    sub.add_parser("list")
    args = ap.parse_args()
    return {"md": md, "jsonl": jsonl, "list": lst}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
