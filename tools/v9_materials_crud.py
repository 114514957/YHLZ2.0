#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 素材 CRUD v1.0（2026-10-12）——增删查改 + 统计 + 搬运

管理 docs/素材 下的 Markdown 素材块（## <ID>｜<标题> + 元数据 + ### 轮次）。
所有写操作自动备份（<文件>.bak-YYYYmmdd-HHMMSS）；rm 默认干跑，--yes 才真删。

用法:
  # 查
  python tools/v9_materials_crud.py list  [--dir D] [--file F] [--status S] [--category C] [--grep W] [--json]
  python tools/v9_materials_crud.py show  --id 故事-103 [--file F]
  python tools/v9_materials_crud.py stats [--dir D]
  # 增 / 改 / 删 / 移
  python tools/v9_materials_crud.py add     --file TARGET.md --from NEWBLOCK.md [--force]
  python tools/v9_materials_crud.py set     --file F --id X --field status --value keep
  python tools/v9_materials_crud.py replace --file F --id X --from NEWBLOCK.md
  python tools/v9_materials_crud.py rm      --file F --id X [--yes]
  python tools/v9_materials_crud.py move    --from SRC.md --to DST.md --id X
  python tools/v9_materials_crud.py --selftest

退出码：0=成功；1=失败；2=用法错误；3=自测失败。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v9_story_gate as gate  # noqa: E402

VERSION = "1.0"
BLOCK_START = re.compile(r"(?m)^## ")


def blocks_with_spans(text: str) -> list[tuple[int, int, str]]:
    starts = [m.start() for m in BLOCK_START.finditer(text)]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        out.append((s, e, text[s:e]))
    return out


def block_id(blk: str) -> str:
    first = blk.splitlines()[0][3:].strip()
    return first.split("｜")[0].strip() if "｜" in first else first.split("|")[0].strip()


def find_block(text: str, bid: str):
    for (s, e, blk) in blocks_with_spans(text):
        if block_id(blk) == bid:
            return s, e, blk
    return None


def backup(path: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    bp = Path(str(path) + f".bak-{ts}")
    n = 2
    while bp.exists():
        bp = Path(str(path) + f".bak-{ts}-{n}")
        n += 1
    shutil.copy2(path, bp)
    return bp


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def write(p: Path, text: str) -> None:
    io.open(p, "w", encoding="utf-8", newline="\n").write(text)


def scan_files(d: str | None, f: str | None) -> list[Path]:
    if f:
        return [Path(f)]
    base = Path(d or "docs/素材")
    return sorted(x for x in base.rglob("*.md") if ".bak-" not in x.name and not x.name.endswith(".gate.txt"))


def summary_of(blk: str) -> dict:
    meta = gate.parse_meta(blk)
    ts = gate.parse_turns(blk)
    nums = sorted({int(t[2]) for t in ts if t[2].isdigit()})
    lens = [len(t[3]) for t in ts]
    return {
        "id": block_id(blk),
        "status": meta.get("status", "-"),
        "category": meta.get("category", "-"),
        "fiction": meta.get("fiction", "-"),
        "rounds": max(nums) if nums else 0,
        "turns": len(ts), "max_turn": max(lens) if lens else 0,
    }


# ---------------- 命令实现 ----------------

def cmd_list(args) -> int:
    rows = []
    for fp in scan_files(args.dir, args.file):
        for (_s, _e, blk) in blocks_with_spans(read(fp)):
            if not gate.parse_turns(blk) and not gate.parse_meta(blk):
                continue  # 非素材块（文档标题等）
            s = summary_of(blk)
            if args.status and s["status"] != args.status:
                continue
            if args.category and s["category"] != args.category:
                continue
            if args.grep and args.grep not in blk:
                continue
            s["file"] = fp.name
            rows.append(s)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(f"{'文件':<42} {'ID':<14} {'状态':<9} {'类目':<6} {'轮':>3} {'最长':>5}")
        for r in rows:
            print(f"{r['file']:<42} {r['id']:<14} {r['status']:<9} {r['category']:<6} {r['rounds']:>3} {r['max_turn']:>5}")
        print(f"共 {len(rows)} 块")
    return 0


def cmd_show(args) -> int:
    for fp in ([Path(args.file)] if args.file else scan_files(args.dir, None)):
        found = find_block(read(fp), args.id)
        if found:
            print(f"# 来自 {fp}")
            print(found[2])
            return 0
    print(f"未找到: {args.id}")
    return 1


def cmd_stats(args) -> int:
    files = scan_files(args.dir, None)
    grand = {"blocks": 0}
    print(f"{'文件':<46} {'块数':>4} {'keep':>5} {'cand':>5} {'drop':>5} {'轮均':>5} {'最长':>5}")
    for fp in files:
        bs = [summary_of(b) for (_a, _b, b) in blocks_with_spans(read(fp))
              if gate.parse_turns(b) or gate.parse_meta(b)]
        if not bs:
            continue
        rounds = [b["rounds"] for b in bs if b["rounds"]]
        line = {
            "f": fp.name, "n": len(bs),
            "keep": sum(1 for b in bs if b["status"] == "keep"),
            "cand": sum(1 for b in bs if b["status"] == "candidate"),
            "drop": sum(1 for b in bs if b["status"] == "drop"),
            "avg": (sum(rounds) // len(rounds)) if rounds else 0,
            "mx": max((b["max_turn"] for b in bs), default=0),
        }
        grand["blocks"] += line["n"]
        print(f"{line['f']:<46} {line['n']:>4} {line['keep']:>5} {line['cand']:>5} {line['drop']:>5} {line['avg']:>5} {line['mx']:>5}")
    print(f"合计块数: {grand['blocks']}")
    return 0


def cmd_add(args) -> int:
    target, src = Path(args.file), Path(args.from_)
    src_blocks = blocks_with_spans(read(src))
    if not src_blocks:
        print("来源文件没有素材块")
        return 1
    blk = src_blocks[0][2].rstrip() + "\n"
    bid = block_id(blk)
    text = read(target) if target.exists() else ""
    if find_block(text, bid) and not args.force:
        print(f"目标已存在同 ID 块: {bid}（--force 可强加）")
        return 1
    backup(target) if target.exists() else None
    new = (text.rstrip() + "\n\n" + blk + "\n") if text.strip() else ("# " + target.stem + "\n\n" + blk)
    write(target, new)
    print(f"已添加 {bid} -> {target}")
    return 0


def cmd_set(args) -> int:
    target = Path(args.file)
    text = read(target)
    found = find_block(text, args.id)
    if not found:
        print(f"未找到: {args.id}")
        return 1
    s, e, blk = found
    pat = re.compile(rf"(?m)^[ \t]*-[ \t]*{re.escape(args.field)}[ \t]*:.*$")
    line = f"- {args.field}: {args.value}"
    if pat.search(blk):
        nb = pat.sub(line, blk, count=1)
    else:
        lines = blk.splitlines(True)
        nb = lines[0] + line + "\n" + "".join(lines[1:])
    backup(target)
    write(target, text[:s] + nb + text[e:])
    print(f"已改 {args.id} 的 {args.field} = {args.value}")
    return 0


def cmd_replace(args) -> int:
    target, src = Path(args.file), Path(args.from_)
    text = read(target)
    found = find_block(text, args.id)
    if not found:
        print(f"未找到: {args.id}")
        return 1
    src_blocks = blocks_with_spans(read(src))
    if not src_blocks:
        print("来源文件没有素材块")
        return 1
    nb = src_blocks[0][2].rstrip() + "\n"
    if block_id(nb) != args.id:
        print(f"ID 不一致: 目标 {args.id} vs 新块 {block_id(nb)}")
        return 1
    s, e, _blk = found
    backup(target)
    write(target, text[:s] + nb + text[e:])
    print(f"已替换 {args.id}")
    return 0


def cmd_rm(args) -> int:
    target = Path(args.file)
    text = read(target)
    found = find_block(text, args.id)
    if not found:
        print(f"未找到: {args.id}")
        return 1
    s, e, blk = found
    print(f"[{'执行' if args.yes else '干跑'}] 将删除 {args.id}（{len(blk)} 字符）from {target}")
    if not args.yes:
        print("（加 --yes 才真正删除；删除前会自动备份）")
        return 0
    backup(target)
    new = text[:s] + text[e:]
    new = re.sub(r"\n{3,}", "\n\n", new)
    write(target, new)
    print(f"已删除 {args.id}（备份保留）")
    return 0


def cmd_move(args) -> int:
    src, dst = Path(args.from_), Path(args.to)
    text = read(src)
    found = find_block(text, args.id)
    if not found:
        print(f"源未找到: {args.id}")
        return 1
    s, e, blk = found
    dtext = read(dst) if dst.exists() else ""
    if find_block(dtext, args.id):
        print(f"目标已存在同 ID: {args.id}")
        return 1
    backup(src)
    backup(dst) if dst.exists() else None
    write(src, re.sub(r"\n{3,}", "\n\n", text[:s] + text[e:]))
    write(dst, (dtext.rstrip() + "\n\n" + blk.rstrip() + "\n") if dtext.strip() else ("# " + dst.stem + "\n\n" + blk))
    print(f"已移动 {args.id}: {src.name} -> {dst.name}")
    return 0


# ---------------- 自测 ----------------

def selftest() -> int:
    import contextlib
    fails: list[str] = []

    def chk(name: str, cond: bool) -> bool:
        if not cond:
            fails.append(name)
        return cond

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        a, b = t / "a.md", t / "b.md"
        write(a, "# A\n\n## 故事-001｜甲\n- category: 世界观\n- status: candidate\n- fiction: true\n### 老爹问1\n吃了吗。\n### 元亨答1\n吃了。\n")
        write(b, "# B\n\n## 故事-002｜乙\n- category: 人格\n- status: candidate\n- fiction: true\n### 老爹问1\n睡了吗。\n### 元亨答1\n没睡。\n")

        def run(fn, **k):
            with contextlib.redirect_stdout(io.StringIO()):
                return fn(argparse.Namespace(**k))

        chk("add", run(cmd_add, file=str(b), from_=str(a), force=False) == 0 and "故事-001" in read(b))
        chk("add-dup", run(cmd_add, file=str(b), from_=str(a), force=False) == 1)
        chk("set", run(cmd_set, file=str(b), id="故事-002", field="status", value="keep") == 0)
        fb = find_block(read(b), "故事-002")
        chk("set-value", bool(fb) and "- status: keep" in fb[2])
        chk("replace", run(cmd_replace, file=str(b), id="故事-001", from_=str(a)) == 0)
        chk("rm-dry", run(cmd_rm, file=str(b), id="故事-001", yes=False) == 0 and "故事-001" in read(b))
        chk("rm-real", run(cmd_rm, file=str(b), id="故事-001", yes=True) == 0 and "故事-001" not in read(b))
        write(a, "# A\n\n## 故事-003｜丙\n- status: candidate\n### 老爹问1\n嗨。\n### 元亨答1\n嗨！\n")
        chk("move", run(cmd_move, **{"from_": str(a), "to": str(b), "id": "故事-003"}) == 0)
        chk("move-eff", "故事-003" in read(b) and "故事-003" not in read(a))
        chk("backups", len(list(t.glob("*.bak-*"))) >= 3)
    print(f"CRUD 自测 v{VERSION}: {'全部通过' if not fails else '失败: ' + ', '.join(fails)}")
    return 0 if not fails else 3


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=f"V9 素材 CRUD v{VERSION}")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("list"); p.add_argument("--dir"); p.add_argument("--file"); p.add_argument("--status"); p.add_argument("--category"); p.add_argument("--grep"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("show"); p.add_argument("--id", required=True); p.add_argument("--file"); p.add_argument("--dir")
    p = sub.add_parser("stats"); p.add_argument("--dir")
    p = sub.add_parser("add"); p.add_argument("--file", required=True); p.add_argument("--from", dest="from_", required=True); p.add_argument("--force", action="store_true")
    p = sub.add_parser("set"); p.add_argument("--file", required=True); p.add_argument("--id", required=True); p.add_argument("--field", required=True); p.add_argument("--value", required=True)
    p = sub.add_parser("replace"); p.add_argument("--file", required=True); p.add_argument("--id", required=True); p.add_argument("--from", dest="from_", required=True)
    p = sub.add_parser("rm"); p.add_argument("--file", required=True); p.add_argument("--id", required=True); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("move"); p.add_argument("--from", dest="from_", required=True); p.add_argument("--to", required=True); p.add_argument("--id", required=True)

    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.cmd:
        ap.print_help()
        return 2
    fn = {"list": cmd_list, "show": cmd_show, "stats": cmd_stats, "add": cmd_add,
          "set": cmd_set, "replace": cmd_replace, "rm": cmd_rm, "move": cmd_move}[args.cmd]
    try:
        return fn(args)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
