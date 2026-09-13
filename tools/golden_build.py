"""Golden persona-sample library for Yuanheng (golden-set workflow, ledger 0326+).

Builds a reviewable candidate pool from Yuanheng's *real* 老爹<->元亨 sessions,
lets the owner list/inspect/pick entries, and appends the chosen ones into
`tools/persona_golden.md` as editable, delimitable blocks. Never invents data:
candidates come from persisted sessions only.

Golden block format (robust to multi-line replies):
    ## golden-34
    - source: qq_qq_p2258374446
    - note:
    ### 老爹
    <user turn, verbatim>
    ### 元亨
    <assistant turn, verbatim>

Usage:
    python tools/golden_build.py build          # 收集候选 -> data/finetune/golden_candidates.jsonl
    python tools/golden_build.py list [--all]   # 编号罗列候选（默认隐藏已标记问题项）
    python tools/golden_build.py show 3         # 看某条全文
    python tools/golden_build.py pick 1 3 7     # 选入 persona_golden.md
    python tools/golden_build.py stats
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CAND = ROOT / "data" / "finetune" / "golden_candidates.jsonl"
GOLDEN = ROOT / "tools" / "persona_golden.md"

SCHED_PREFIX = ("（计划表到点）", "(计划表", "（系统", "系统：", "[系统")
META_MARK = ("元亨的内部状态", "**已锁定**", "**最终确认")
MEMO_PREFIX = ("记住", "更正", "记得", "别忘", "更新", "纠正")
BLOCK_RE = re.compile(r"^##\s+golden-(\d+)\s*$", re.MULTILINE)


def _flags(user: str, assistant: str) -> list[str]:
    fl: list[str] = []
    if user.startswith(SCHED_PREFIX) or "例行计划" in user:
        fl.append("调度提示")
    if any(m in assistant for m in META_MARK):
        fl.append("含内部状态")
    if user.startswith(MEMO_PREFIX):
        fl.append("记忆指令")
    if len(assistant) < 20:
        fl.append("回复过短")
    if len(assistant) > 600:
        fl.append("回复过长")
    if "?" in user or "？" in user:
        fl.append("含提问")
    return fl


def build() -> int:
    from tools.finetune_build import build_sft
    rows, _ = build_sft()
    out, seen = [], set()
    for r in rows:
        msgs = r["messages"]
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        asst = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        key = user.strip()[:40]
        if not user or not asst or key in seen:
            continue
        seen.add(key)
        out.append({"source": r.get("source", ""), "user": user.strip(),
                    "assistant": asst.strip(), "flags": _flags(user.strip(), asst.strip())})
    CAND.parent.mkdir(parents=True, exist_ok=True)
    CAND.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out)
                    + ("\n" if out else ""), encoding="utf-8")
    print(json.dumps({"candidates": len(out), "file": str(CAND.relative_to(ROOT))},
                     ensure_ascii=False, indent=1))
    return 0


def _load() -> list[dict]:
    if not CAND.exists():
        build()
    rows = []
    for line in CAND.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_golden(path: Path | None = None) -> list[dict]:
    """Parse picked golden blocks back into {id, source, note, user, assistant}."""
    path = path or GOLDEN
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out: list[dict] = []
    parts = BLOCK_RE.split(text)
    for i in range(1, len(parts), 2):
        gid = parts[i]
        body = parts[i + 1]
        meta: dict[str, str] = {}
        for m in re.finditer(r"^[ \t]*-[ \t]*([A-Za-z_]+)[ \t]*:[ \t]*(.*)$", body, re.MULTILINE):
            meta[m.group(1).lower()] = m.group(2).strip()
        m_user = re.search(r"^###\s*老爹\s*\n(.*?)(?=^###\s*元亨)", body, re.MULTILINE | re.DOTALL)
        m_asst = re.search(r"^###\s*元亨\s*\n(.*?)(?=^##\s+golden-|\Z)", body, re.MULTILINE | re.DOTALL)
        if not (m_user and m_asst):
            continue
        status = meta.get("status", "candidate").strip().lower()
        status = {"fidex": "fixed", "fix": "fixed", "fixed": "fixed",
                  "改": "fixed", "改过": "fixed", "已改": "fixed", "我改了": "fixed",
                  "keep": "keep", "要": "keep", "保留": "keep", "留": "keep",
                  "drop": "drop", "delete": "drop", "不要": "drop",
                  "这条不要": "drop", "丢弃": "drop", "删": "drop",
                  "candidate": "candidate", "待": "candidate", "待定": "candidate",
                  }.get(status, status or "candidate")
        out.append({"id": int(gid),
                    "source": meta.get("source", ""),
                    "note": meta.get("note", ""),
                    "rating": meta.get("rating", ""),
                    "tags": meta.get("tags", ""),
                    "status": status,
                    "user": m_user.group(1).strip(),
                    "assistant": m_asst.group(1).strip()})
    return out


def cmd_list(args: argparse.Namespace) -> int:
    rows = _load()
    for i, r in enumerate(rows, 1):
        fl = ",".join(r.get("flags", []))
        if fl and not args.all:
            continue
        u = r["user"].replace("\n", " ")[:46]
        print(f"{i:>3}  [{fl or '干净'}]  {u}")
    total = len(rows)
    clean = sum(1 for r in rows if not r.get("flags"))
    print(f"--- {total} 条候选（干净 {clean}），--all 看全部 ---")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    rows = _load()
    for n in args.ids:
        if not (1 <= n <= len(rows)):
            print(f"[show] 越界: {n}", file=sys.stderr)
            continue
        r = rows[n - 1]
        print(f"# {n}  source={r.get('source')}  flags={','.join(r.get('flags', []))}")
        print(f"你：{r['user']}")
        print(f"元亨：{r['assistant']}\n")
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    rows = _load()
    have = {g["user"].strip()[:40] for g in load_golden()}
    added = 0
    with GOLDEN.open("a", encoding="utf-8") as f:
        for n in args.ids:
            if not (1 <= n <= len(rows)):
                print(f"[pick] 越界: {n}", file=sys.stderr)
                continue
            r = rows[n - 1]
            if r["user"].strip()[:40] in have:
                print(f"[pick] 已存在，跳过: {n}")
                continue
            f.write(f"\n## golden-{n}\n"
                    f"- source: {r.get('source', '')}\n"
                    f"- rating: \n"
                    f"- tags: \n"
                    f"- status: keep\n"
                    f"- note: \n"
                    f"### 老爹\n{r['user'].strip()}\n"
                    f"### 元亨\n{r['assistant'].strip()}\n")
            have.add(r["user"].strip()[:40])
            added += 1
    try:
        shown = GOLDEN.relative_to(ROOT)
    except ValueError:
        shown = GOLDEN
    print(f"[pick] 已加入 {added} 条 -> {shown}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    rows = _load()
    have = {g["user"].strip()[:40] for g in load_golden()}
    added = 0
    with GOLDEN.open("a", encoding="utf-8") as f:
        for n, r in enumerate(rows, 1):
            if not args.all and r.get("flags"):
                continue
            if r["user"].strip()[:40] in have:
                continue
            f.write(f"\n## golden-{n}\n"
                    f"- source: {r.get('source', '')}\n"
                    f"- rating: \n- tags: \n- status: candidate\n- note: \n"
                    f"### 老爹\n{r['user'].strip()}\n### 元亨\n{r['assistant'].strip()}\n")
            have.add(r["user"].strip()[:40])
            added += 1
    print(f"[seed] 新增 {added} 条候选 -> {GOLDEN}")
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    rows = _load()
    from collections import Counter
    c = Counter(f for r in rows for f in r.get("flags", []))
    print(json.dumps({"candidates": len(rows),
                      "clean": sum(1 for r in rows if not r.get("flags")),
                      "picked": len(load_golden()),
                      "flags": dict(c)}, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="元亨黄金样本候选库")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true")
    p_show = sub.add_parser("show")
    p_show.add_argument("ids", type=int, nargs="+")
    p_pick = sub.add_parser("pick")
    p_pick.add_argument("ids", type=int, nargs="+")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--all", action="store_true")
    sub.add_parser("stats")
    args = ap.parse_args()
    return {"build": lambda a: build(), "list": cmd_list, "show": cmd_show,
            "pick": cmd_pick, "seed": cmd_seed, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
