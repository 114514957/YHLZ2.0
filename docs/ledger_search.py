#!/usr/bin/env python3
"""YHLZ 台账检索工具（无索引、纯标准库）。

用法：
  python docs/ledger_search.py <关键词...>            多关键词 AND 子串检索
  python docs/ledger_search.py --file <path> <词...>  指定台账文件（默认上下文台账）
  python docs/ledger_search.py --list                 列出全部记录编号与标题
  python docs/ledger_search.py --open <N>             打印指定记录全文
  python docs/ledger_search.py --top <N>              限制结果条数（默认 12）

示例：
  python docs/ledger_search.py 元亨
  python docs/ledger_search.py FZ-007
  python docs/ledger_search.py WSL 403
"""

import argparse
import re
import sys
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "上下文台账.md"
HEADER_RE = re.compile(r"^## 记录 (\d+)[:：](.*)$")
WIDTH = 30
MAX_SNIPPETS = 3


def parse_records(path: Path):
    records = []
    cur = None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = HEADER_RE.match(line)
        if m:
            if cur is not None:
                records.append(cur)
            cur = {
                "no": int(m.group(1)),
                "title": m.group(2).strip(),
                "start": i,
                "end": i,
                "lines": [],
            }
        elif cur is not None:
            cur["end"] = i
            cur["lines"].append(line)
    if cur is not None:
        records.append(cur)
    for r in records:
        r["body"] = "\n".join(r["lines"])
        r["search"] = (f"{r['no']:04d}\n" + r["title"] + "\n" + r["body"]).lower()
    return records


def score_record(rec, kws):
    search = rec["search"]
    if not all(kw in search for kw in kws):
        return None
    s = 1
    for kw in kws:
        if kw in rec["title"].lower():
            s += 3
    return s


def snippets(rec, kws):
    out = []
    seen = set()
    for idx, line in enumerate(rec["lines"], 1):
        low = line.lower()
        hits = [kw for kw in kws if kw in low]
        if not hits:
            continue
        pos = low.find(hits[0])
        a = max(0, pos - WIDTH)
        b = min(len(line), pos + len(hits[0]) + WIDTH)
        snip = f"行{rec['start'] + idx - 1}: {line[a:b]}"
        if snip not in seen:
            seen.add(snip)
            out.append(snip)
        if len(out) >= MAX_SNIPPETS:
            break
    return out


def parse_fallback(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        {
            "no": None,
            "title": path.stem,
            "start": 1,
            "end": len(lines),
            "lines": lines,
            "body": "\n".join(lines),
            "search": "\n".join(lines).lower(),
        }
    ]


def cmd_search(args):
    path = Path(args.file)
    if not path.exists():
        print(f"台账文件不存在: {path}", file=sys.stderr)
        return 1
    records = parse_records(path) or parse_fallback(path)
    kws = [k.lower() for k in args.keywords]
    hits = []
    for r in records:
        s = score_record(r, kws)
        if s is not None:
            hits.append((s, r))
    hits.sort(key=lambda x: (-x[0], x[1]["no"]))
    if not hits:
        print(f"未命中: {' '.join(args.keywords)}")
        print("提示：换更短关键词，或用 --list 查看全部记录，或 --open <N> 阅读单条记录。")
        return 0
    print(f"命中 {len(hits)} 条记录（台账: {path.name}）")
    for s, r in hits[: args.top]:
        head_no = f"记录 {r['no']:04d}" if r["no"] is not None else "全文"
        print(f"==> {head_no}（行 {r['start']}-{r['end']}，得分 {s}）{r['title']}")
        for snip in snippets(r, kws):
            print(f"    {snip}")
    return 0


def cmd_list(args):
    path = Path(args.file)
    print(f"台账: {path.name}")
    for r in parse_records(path) or parse_fallback(path):
        no = f"{r['no']:04d}" if r["no"] is not None else "----"
        print(f"{no} | 行 {r['start']}-{r['end']} | {r['title']}")
    return 0


def cmd_open(args):
    path = Path(args.file)
    rec = next((r for r in parse_records(path) if r["no"] == args.open), None)
    if rec is None:
        print(f"未找到记录 {args.open:04d}", file=sys.stderr)
        return 1
    print(f"记录 {rec['no']:04d}（行 {rec['start']}-{rec['end']}）：{rec['title']}")
    for idx, line in enumerate(rec["lines"], rec["start"]):
        print(f"{idx:4d} | {line}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="YHLZ 台账短关键词检索")
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="台账文件路径（默认上下台账）")
    parser.add_argument("--list", action="store_true", help="列出全部记录")
    parser.add_argument("--open", type=int, metavar="N", help="打印记录 N 的全文")
    parser.add_argument("--top", type=int, default=12, help="最多显示条数（默认 12）")
    parser.add_argument("keywords", nargs="*", help="关键词（AND）")
    args = parser.parse_args()
    if args.list:
        return cmd_list(args)
    if args.open is not None:
        return cmd_open(args)
    if not args.keywords:
        parser.print_help()
        return 0
    return cmd_search(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
