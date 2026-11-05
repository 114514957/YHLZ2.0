#!/usr/bin/env python3
"""YHLZ 台账 CRUD 程序（增删查改）—— 任何 agent 都能调用。

它是 `docs/上下文台账.md`（项目唯一事实源）的**唯一写入程序**：原子写、跨进程
加锁、自动备份、敏感内容拦截、写后同步检索索引。既可在命令行调用（任何有 shell
的 agent），也可被 Python 直接 import `backend.ledger_store`，MCP 工具亦复用同一
核心。

用法::

    python tools/ledger_cli.py search <关键词...>       查（记录级检索）
    python tools/ledger_cli.py list [--limit N]         查（列最近记录）
    python tools/ledger_cli.py get <N>                  查（读单条全文）
    python tools/ledger_cli.py add --title T [--body B] 增（追加新记录）
    python tools/ledger_cli.py update <N> [--title T] [--append B] [--body B]  改
    python tools/ledger_cli.py delete <N> --yes         删（破坏性，需 --yes）
    python tools/ledger_cli.py stats                    台账统计
    python tools/ledger_cli.py index [--all] [--quiet]  重建/增量刷新检索索引

全局开关：`--json`（机器可读）、`--ledger PATH`（默认 docs/上下文台账.md）。

正文字符串可用 `--body`/`--append` 直接给（`\n` 分隔），`--file F` 从文件读，
或省略从 stdin 读。空行用 `\n\n`。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend import ledger_store as ls  # noqa: E402


def _emit(data, as_json: bool, human: str) -> int:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print(human)
    return 0


def _read_text(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    inline = getattr(args, "body", None) or getattr(args, "append", None)
    if inline is not None:
        return inline.replace("\\n", "\n")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def cmd_add(args) -> int:
    body = _read_text(args)
    res = ls.add_record(args.title, body, no=args.no, path=args.ledger,
                        stamp_time=not args.no_stamp)
    if args.json:
        return _emit(res, True, "")
    rec = res["record"]
    return _emit(res, False,
                 f"已追加 记录 {res['no']:04d}：{res['title']}\n"
                 f"  {ls.LEDGER.name} 现有 {ls.stats(args.ledger)['records']} 条记录"
                 f"（{rec['start']}-{rec['end']} 行）")


def cmd_get(args) -> int:
    rec = ls.get_record(args.no, path=args.ledger)
    if rec is None:
        print(f"未找到记录 {args.no:04d}", file=sys.stderr)
        return 1
    return _emit(rec, args.json,
                 f"记录 {rec['no']:04d}（行 {rec['start']}-{rec['end']}）\n{rec['text']}")


def cmd_search(args) -> int:
    q = " ".join(args.keywords)
    hits = ls.search(q, limit=args.limit, path=args.ledger)
    if args.json:
        return _emit(hits, True, "")
    if not hits:
        print(f"未命中：{q}")
        print("提示：换更短关键词，或 `list` 看最近记录，或 `get <N>` 读单条。")
        return 0
    lines = [f"命中 {len(hits)} 条记录（关键词：{q}）"]
    for h in hits:
        lines.append(f"==> 记录 {h['no']:04d}（行 {h['start']}-{h['end']}，分 {h['score']}）{h['title']}")
        for snip in h["snippets"]:
            lines.append(f"    {snip}")
    return _emit(hits, False, "\n".join(lines))


def cmd_list(args) -> int:
    rows = ls.list_records(limit=args.limit, offset=args.offset,
                           keyword=args.keyword, path=args.ledger)
    if args.json:
        return _emit(rows, True, "")
    if not rows:
        print("（没有记录）")
        return 0
    s = ls.stats(args.ledger)
    lines = [f"台账共 {s['records']} 条记录（最新 {s['latest_no']:04d}），本页 {len(rows)} 条："]
    for r in rows:
        lines.append(f"{r['no']:04d} | 行 {r['start']}-{r['end']} | {r['title']}")
        if r["preview"]:
            lines.append(f"      {r['preview']}")
    return _emit(rows, False, "\n".join(lines))


def cmd_update(args) -> int:
    append = args.append
    replace = args.body
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        if append is not None and replace is None:
            append = text
        elif replace is not None and append is None:
            replace = text
        elif append is None and replace is None:
            replace = text
        else:
            print("--append 与 --body 不能同时配合 --file", file=sys.stderr)
            return 2
    if append is not None:
        append = append.replace("\\n", "\n")
    if replace is not None:
        replace = replace.replace("\\n", "\n")
    if append is None and replace is None and args.title is None:
        print("需要 --title / --append / --body 至少一项", file=sys.stderr)
        return 2
    res = ls.update_record(args.no, title=args.title, append_lines=append,
                           replace_body=replace, path=args.ledger)
    if args.json:
        return _emit(res, True, "")
    return _emit(res, False, f"已更新 记录 {res['no']:04d}"
                 f"（{ls.stats(args.ledger)['records']} 条记录）")


def cmd_delete(args) -> int:
    res = ls.delete_record(args.no, path=args.ledger, confirm=args.yes)
    if args.json:
        return _emit(res, True, "")
    return _emit(res, False, f"已删除 记录 {res['no']:04d}"
                 f"（{ls.stats(args.ledger)['records']} 条记录）")


def cmd_check(args) -> int:
    """台账编号自检：缺号 / 重号 / 顺序（台账 1098）。

    历史缺号（132/158/…）是旧账，不阻断；重号才是结构问题。
    退出码：0 = 无重号（缺号只报告）；1 = 存在重号。
    """
    import re
    from collections import Counter

    text = Path(args.ledger).read_text(encoding="utf-8")
    nums = [int(m) for m in re.findall(r"^## 记录 (\d+)", text, re.M)]
    counts = Counter(nums)
    dup = sorted(n for n, c in counts.items() if c > 1)
    gaps = ([n for n in range(min(nums), max(nums) + 1) if n not in counts]
            if nums else [])
    data = {
        "records": len(nums),
        "min": min(nums) if nums else 0,
        "max": max(nums) if nums else 0,
        "gaps": gaps,
        "gap_count": len(gaps),
        "duplicates": dup,
        "ordered": nums == sorted(nums),
    }
    human = (f"records={data['records']} min={data['min']} max={data['max']} "
             f"gaps={data['gap_count']} duplicates={len(dup)} ordered={data['ordered']}")
    if gaps:
        human += "\n  missing: " + ",".join(str(n) for n in gaps[:20]) + (
            " ..." if len(gaps) > 20 else "")
    if dup:
        human += "\n  duplicated: " + ",".join(str(n) for n in dup[:20])
    _emit(data, args.json, human)
    return 1 if dup else 0


def cmd_stats(args) -> int:
    s = ls.stats(args.ledger)
    return _emit(s, args.json,
                 "\n".join(f"{k}: {v}" for k, v in s.items()))


def cmd_index(args) -> int:
    from tools.ledger_mem_import import (index_ledger_all_rows,
                                         index_ledger_new_rows)

    if args.all:
        n = index_ledger_all_rows(args.ledger)
        msg = f"全量重建台账索引：{n} 行"
    else:
        n, total = index_ledger_new_rows(args.ledger, since_line=ls._last_indexed_line())
        msg = f"增量索引：新增 {n} 行（台账共 {total} 行）"
    if not args.quiet:
        print(msg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="YHLZ 台账 CRUD 程序",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    p.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    p.add_argument("--ledger", type=Path, default=ls.LEDGER, help="台账文件路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="增：追加新记录")
    a.add_argument("--title", required=True, help="记录标题")
    a.add_argument("--body", default=None, help="正文（\\n 分隔）")
    a.add_argument("--file", default=None, help="从文件读取正文")
    a.add_argument("--no", type=int, default=None, help="指定记录号（默认自动）")
    a.add_argument("--no-stamp", action="store_true", help="不自动加「时间：」行")
    a.set_defaults(func=cmd_add)

    g = sub.add_parser("get", help="查：读单条记录全文")
    g.add_argument("no", type=int)
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("search", help="查：记录级关键词检索")
    s.add_argument("keywords", nargs="+")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_search)

    l = sub.add_parser("list", help="查：列最近记录")
    l.add_argument("--limit", type=int, default=20)
    l.add_argument("--offset", type=int, default=0)
    l.add_argument("--keyword", default="")
    l.set_defaults(func=cmd_list)

    u = sub.add_parser("update", help="改：改标题/追加/替换正文")
    u.add_argument("no", type=int)
    u.add_argument("--title", default=None)
    u.add_argument("--append", default=None, help="追加正文（\\n 分隔）")
    u.add_argument("--body", default=None, help="替换整段正文（\\n 分隔）")
    u.add_argument("--file", default=None, help="从文件读正文")
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", help="删：删除记录（破坏性）")
    d.add_argument("no", type=int)
    d.add_argument("--yes", action="store_true", help="确认删除")
    d.set_defaults(func=cmd_delete)

    st = sub.add_parser("stats", help="台账统计")
    st.set_defaults(func=cmd_stats)

    ck = sub.add_parser("check", help="查：编号自检（缺号/重号/顺序）")
    ck.set_defaults(func=cmd_check)

    ix = sub.add_parser("index", help="刷新检索索引")
    ix.add_argument("--all", action="store_true", help="全量重建")
    ix.add_argument("--quiet", action="store_true")
    ix.set_defaults(func=cmd_index)
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ls.LedgerError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
