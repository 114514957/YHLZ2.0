"""Editable memory-sample doc <-> jsonl (ledger 0346).

The owner wants to revise every memory by hand, so samples live in a
human-editable Markdown file (`tools/persona_memory.md`) grouped by memory:

    ## mem-1
    - source: mem_xxx
    - summary: <记忆>
    - relationship: 老爹
    - status: candidate
    ### 问1
    ...
    ### 答1
    ...
    ### 问2
    ...
    ### 答2
    ...

Commands:
    python tools/memory_samples.py md      # jsonl -> persona_memory.md
    python tools/memory_samples.py jsonl   # edited md -> jsonl
    python tools/memory_samples.py list    # 概览
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
DOC = ROOT / "tools" / "persona_memory.md"
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体。回答时自然想起你的记忆，"
          "像人对朋友说话：短、口语、有情绪，不罗列、不解释机制。")


def md(args: argparse.Namespace) -> int:
    rows = [json.loads(l) for l in JSONL.read_text(encoding="utf-8").splitlines() if l.strip()]
    groups: dict[str, dict] = {}
    for r in rows:
        src = r.get("source", "")
        g = groups.setdefault(src, {"summary": (r.get("instruction") or "").replace("你是元亨。你记得：", ""),
                                    "relationship": r.get("relationship", ""),
                                    "pairs": []})
        g["pairs"].append(r)

    existing_src = {r["source"] for r in load_memory_samples(DOC)} if DOC.exists() else set()
    head = ("# 元亨记忆样本（逐条校订）\n\n"
            "> 每条记忆一个 `## mem-N` 块；`### 问K` / `### 答K` 成对。\n"
            "> 改完把 `status` 设 `keep`；不要的设 `drop`。工具：`memory_samples.py jsonl` 回读。\n")
    if DOC.exists() and args.append:
        text = DOC.read_text(encoding="utf-8")
        nums = [int(n) for n in re.findall(r"^##\s+mem-(\d+)\s*$", text, re.MULTILINE)]
        next_i = (max(nums) + 1) if nums else 1
        prefix = text.rstrip() + "\n"
    else:
        next_i = 1
        prefix = head

    blocks = []
    for src, g in groups.items():
        if src in existing_src:
            continue
        b = [f"## mem-{next_i}", f"- source: {src}", f"- summary: {g['summary']}",
             f"- relationship: {g['relationship']}", "- status: candidate"]
        for k, p in enumerate(g["pairs"], 1):
            b += [f"### 问{k}", p["messages"][1]["content"], f"### 答{k}", p["messages"][2]["content"]]
        blocks.append("\n".join(b))
        next_i += 1
    DOC.write_text(prefix + "\n" + "\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
    print(f"[ok] 新增 {len(blocks)} 条记忆 -> {DOC.relative_to(ROOT)}（共 {next_i - 1}）")
    return 0


BLOCK = re.compile(r"^##\s+(mem-\d+)\s*$", re.MULTILINE)


def load_memory_samples(path: Path | None = None) -> list[dict]:
    path = path or DOC
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    parts = BLOCK.split(text)
    out = []
    for i in range(1, len(parts), 2):
        bid, body = parts[i], parts[i + 1]
        meta = {}
        for m in re.finditer(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", body, re.MULTILINE):
            meta[m.group(1).lower()] = m.group(2).strip()
        qs = re.findall(r"^###\s*问(\d+)\s*\n(.*?)(?=^###\s*答)", body, re.MULTILINE | re.DOTALL)
        ans = re.findall(r"^###\s*答(\d+)\s*\n(.*?)(?=^###\s*问|^##\s+mem-|\Z)", body, re.MULTILINE | re.DOTALL)
        amap = {n: t.strip() for n, t in ans}
        for n, q in qs:
            a = amap.get(n, "")
            if q.strip() and a:
                out.append({"block": bid, "source": meta.get("source", ""),
                            "summary": meta.get("summary", ""),
                            "relationship": meta.get("relationship", ""),
                            "status": meta.get("status", "keep"),
                            "user": q.strip(), "assistant": a,
                            "emotion": meta.get("emotion", ""), "scene": meta.get("scene", "")})
    return out


def jsonl(args: argparse.Namespace) -> int:
    recs = load_memory_samples()
    kept = [r for r in recs if r["status"] not in ("drop", "不要", "这条不要")]
    out = ROOT / "data" / "finetune" / "persona_memory_reviewed.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps({
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": r["user"]},
                             {"role": "assistant", "content": r["assistant"]}],
                "instruction": f"你是元亨。你记得：{r['summary']}",
                "memory_hook": r["summary"][:24], "emotion": r["emotion"],
                "scene": r["scene"] or "回忆", "relationship": r["relationship"] or "老爹",
                "source": r["source"], "block": r["block"],
            }, ensure_ascii=False) + "\n")
    print(f"[ok] 校订保留 {len(kept)}/{len(recs)} 对 -> {out.relative_to(ROOT)}")
    return 0


def lst(_: argparse.Namespace) -> int:
    recs = load_memory_samples()
    print(f"块内样本 {len(recs)} 对；来自 {len({r['block'] for r in recs})} 条记忆")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="记忆样本可编辑文档")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_md = sub.add_parser("md")
    p_md.add_argument("--append", action="store_true", help="只追加新记忆，不覆盖已编辑内容")
    sub.add_parser("jsonl")
    sub.add_parser("list")
    args = ap.parse_args()
    return {"md": md, "jsonl": jsonl, "list": lst}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
