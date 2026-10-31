"""素材来源登记册工具（P0-2 配套）—— 校验 / 导出覆盖率 / 渲染。

**唯一真源**是 `docs/报告/素材来源登记册_v1_20261013.json`（JSONC，允许 `//` 注释）——
由 2026-10-13 19:32 那版登记册建立（15 个来源、含许可与 robots 证据、current_gaps）。
本工具不新建第二份登记册：只做三件事。

    --check      schema/枚举/唯一性/内部路径存在性（含"登记册里没写全"的提示）
    --coverage   导出稿 source/group ↔ 登记册 id 的覆盖率；落
                 cache/v9_materials_preparation/20261013/source_coverage.json
    --render     真源 → Markdown（默认打到 stdout，--write 才覆盖 .md）
    --selftest   纯离线自测

约定：导出稿里出现的每个 source/group 键都必须能落到某个 SRC-*；落不到就是
**登记册缺口**（不是静默归并），由 --coverage 报出来。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY_JSON = ROOT / "docs" / "报告" / "素材来源登记册_v1_20261013.json"
REGISTRY_MD = ROOT / "docs" / "报告" / "素材来源登记册_v1_20261013.md"
CACHE_DIR = ROOT / "cache" / "v9_materials_preparation" / "20261013"

# 导出稿 source/group 键（前缀）→ 登记册 id。
# 只映射**有据可依**的：自有素材集→SRC-001、QQ 群语料→SRC-002、真实对话→SRC-003。
# 2026-10-18（ledger 0829）：工具轨迹补登 SRC-016、利贞数据集补登 SRC-017，
# 原先 1252 行 tooluse 的"登记册缺口"就此收口。
SOURCE_MAP = {
    "scene": "SRC-001",
    "lizhen": "SRC-017",
    "memory": "SRC-001",
    "honesty": "SRC-001",
    "uncertain": "SRC-001",
    "refusal": "SRC-001",
    "golden": "SRC-001",
    "real": "SRC-003",
    "tooluse": "SRC-016",
}
QQ_GROUP_SOURCE = "SRC-002"
EXPORTS = (
    ("sft_persona_v8r4.jsonl", "source"),
    ("tool_use_v8.jsonl", "source"),
    ("corpus_qq.jsonl", "group"),
)
REQUIRED = ("id", "name", "kind", "location", "license", "robots_or_terms",
            "pre_collect_assessment", "post_collect_verification",
            "usable_for", "rights_scope_status", "notes")


def load_registry() -> dict:
    raw = REGISTRY_JSON.read_text(encoding="utf-8")
    stripped = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)  # JSONC 注释
    return json.loads(stripped)


def check(reg: dict | None = None) -> tuple[bool, list[str], list[str]]:
    """Returns (ok, problems, hints) — hints are non-fatal observations."""
    reg = reg or load_registry()
    problems: list[str] = []
    hints: list[str] = []
    legend = reg.get("legend") or {}
    sources = reg.get("sources") or []
    if not sources:
        problems.append("sources 为空")
    seen: set[str] = set()
    for src in sources:
        sid = str(src.get("id") or "<missing>")
        if sid in seen:
            problems.append(f"id 重复：{sid}")
        seen.add(sid)
        for field in REQUIRED:
            if src.get(field) in ("", None, [], {}):
                problems.append(f"{sid}: 缺字段 {field}")
        for field in ("kind", "rights_scope_status"):
            allowed = legend.get(field) or []
            if allowed and src.get(field) not in allowed:
                problems.append(f"{sid}: {field}={src.get(field)!r} 不在 legend 内")
        allowed_a = legend.get("assessment_status") or []
        pre = str(src.get("pre_collect_assessment") or "")
        if allowed_a and pre not in allowed_a:
            problems.append(f"{sid}: pre_collect_assessment={pre!r} 不在 legend 内")
        post = str(src.get("post_collect_verification") or "")
        if allowed_a and not any(post.startswith(a) for a in allowed_a):
            problems.append(f"{sid}: post_collect_verification={post!r} 前缀不在 legend 内")
        for part in _split_paths(str(src.get("location") or "")):
            if part.startswith("docs/") or part.startswith("data/"):
                if not (ROOT / part).exists():
                    hints.append(f"{sid}: 路径不存在（或为待建） {part}")
    gaps = reg.get("current_gaps") or []
    if not gaps:
        hints.append("current_gaps 为空——按国标口径至少应列未落实项")
    return (not problems), problems, hints


def _split_paths(location: str) -> list[str]:
    """Location 单元格 → 具体路径；跳过 glob/URL/家目录/带（说明）的片段。"""
    out: list[str] = []
    cleaned = location.split("（", 1)[0]
    for chunk in re.split(r"[|｜;；,，]", cleaned):
        part = chunk.strip().strip("`").replace("\\", "/")
        if not part or "*" in part or part.startswith("~") or "://" in part:
            continue
        if part.endswith(".jsonl") or part.endswith(".md") or part.endswith(".db"):
            out.append(part)
    return out


def coverage(reg: dict | None = None, write: bool = True) -> dict:
    reg = reg or load_registry()
    registered = {s["id"] for s in reg.get("sources") or []}
    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "registry": str(REGISTRY_JSON.relative_to(ROOT)),
        "exports": {}, "unmapped": [], "registered": sorted(registered),
    }
    for filename, key in EXPORTS:
        path = ROOT / "data" / "finetune" / filename
        entry = {"path": str(path.relative_to(ROOT)) if path.exists() else None,
                 "exists": path.exists(), "total": 0,
                 "by_source_id": {}, "by_key": {}, "unmapped_by_key": {}}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry["total"] += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    entry["by_key"]["<badjson>"] = entry["by_key"].get("<badjson>", 0) + 1
                    continue
                raw = str(rec.get(key) or "<none>")
                entry["by_key"][raw] = entry["by_key"].get(raw, 0) + 1
                sid = QQ_GROUP_SOURCE if raw.isdigit() else \
                    SOURCE_MAP.get(raw.split(":", 1)[0].split("-", 1)[0].lower())
                if sid is None:
                    entry["by_source_id"]["UNMAPPED"] = \
                        entry["by_source_id"].get("UNMAPPED", 0) + 1
                    entry["unmapped_by_key"][raw] = \
                        entry["unmapped_by_key"].get(raw, 0) + 1
                else:
                    entry["by_source_id"][sid] = entry["by_source_id"].get(sid, 0) + 1
                    if sid not in registered:
                        entry["unmapped_by_key"][raw] = \
                            entry["unmapped_by_key"].get(raw, 0) + 1
            # 每个未映射的 *键* 只登记一条，计数为该键在文件内的条数
            for raw, count in entry["unmapped_by_key"].items():
                report["unmapped"].append(
                    {"file": filename, "key": raw, "count": count,
                     "reason": "登记册无对应来源条目"})
            entry.pop("unmapped_by_key", None)
        report["exports"][filename] = entry
    # 去重合并 unmapped（按 key 汇总）
    merged: dict[tuple, dict] = {}
    for item in report["unmapped"]:
        k = (item["file"], item["key"], item["reason"])
        merged[k] = {**item, "count": merged.get(k, {}).get("count", 0) + item["count"]}
    report["unmapped"] = sorted(merged.values(), key=lambda x: -x["count"])
    report["mapped_total"] = sum(
        sum(v for k, v in e["by_source_id"].items() if k != "UNMAPPED")
        for e in report["exports"].values())
    report["unmapped_total"] = sum(i["count"] for i in report["unmapped"])
    report["coverage_pct"] = round(
        100.0 * report["mapped_total"] /
        max(1, report["mapped_total"] + report["unmapped_total"]), 2)
    if write:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = CACHE_DIR / "source_coverage.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        report["written_to"] = str(out.relative_to(ROOT))
    return report


def render(reg: dict | None = None, write: bool = False) -> str:
    reg = reg or load_registry()
    lines = [
        "# 素材来源登记册 v1（2026-10-13）",
        "",
        f"> 机器可读真源：`{REGISTRY_JSON.relative_to(ROOT)}`；本文件由 "
        "`tools/v9_source_registry.py --render --write` 生成。",
        f"> 标准参照：{reg.get('standard_ref')}",
        "> 口径：只记录**已核实的事实**，不把『打算核』写成『已核』。",
        "",
        "| id | 名称 | 形态 | 许可 | 权利范围 | 采集前评估 | 采集后核验 | 可用于 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for src in reg.get("sources") or []:
        lines.append("| {id} | {name} | {kind} | {lic} | {rights} | {pre} | {post} | {use} |".format(
            id=src.get("id"), name=src.get("name"), kind=src.get("kind"),
            lic=str(src.get("license")).replace("|", "/"),
            rights=src.get("rights_scope_status"),
            pre=src.get("pre_collect_assessment"),
            post=str(src.get("post_collect_verification")).replace("|", "/"),
            use="/".join(src.get("usable_for") or [])))
    lines += ["", "## 逐条明细", ""]
    for src in reg.get("sources") or []:
        lines += [f"### {src.get('id')} — {src.get('name')}", "",
                  f"- 形态：{src.get('kind')}；位置：`{src.get('location')}`",
                  f"- 许可：{src.get('license')}（权利范围：{src.get('rights_scope_status')}）",
                  f"- robots/条款：{src.get('robots_or_terms')}",
                  f"- 评估：采集前={src.get('pre_collect_assessment')} / "
                  f"采集后={src.get('post_collect_verification')}",
                  f"- 可用于：{'、'.join(src.get('usable_for') or [])}",
                  f"- 备注：{src.get('notes')}", ""]
    gaps = reg.get("current_gaps") or []
    if gaps:
        lines += ["## 现存缺口（登记册自带）", ""] + [f"- {g}" for g in gaps] + [""]
    text = "\n".join(lines) + "\n"
    if write:
        REGISTRY_MD.write_text(text, encoding="utf-8")
    return text


def selftest() -> int:
    ok = True
    reg = load_registry()
    passed, problems, hints = check(reg)
    print(f"[selftest] check: {'PASS' if passed else 'FAIL'} problems={problems[:3]} "
          f"hints={hints[:2]}")
    ok &= passed
    cov = coverage(reg, write=False)
    print(f"[selftest] coverage: {cov['coverage_pct']}% "
          f"mapped={cov['mapped_total']} unmapped={cov['unmapped_total']}")
    ok &= cov["mapped_total"] > 0
    md = render(reg, write=False)
    ok &= md.startswith("# 素材来源登记册 v1")
    ok &= all(s["id"] in md for s in reg["sources"])
    print(f"[selftest] render: {'PASS' if ok else 'FAIL'} ({len(md)} chars)")
    return 0 if ok else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="素材来源登记册工具（P0-2 配套）")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="--render 时覆盖 .md（默认只打到 stdout）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.check:
        passed, problems, hints = check()
        print(f"[check] {'PASS' if passed else 'FAIL'} · 问题 {len(problems)} · 提示 {len(hints)}")
        for p in problems[:20]:
            print("  ✗", p)
        for h in hints[:20]:
            print("  ·", h)
        return 0 if passed else 1
    if args.coverage:
        rep = coverage()
        for name, entry in rep["exports"].items():
            print(f"[coverage] {name}: total={entry['total']} "
                  f"by_source_id={entry['by_source_id']}")
        print(f"[coverage] mapped={rep['mapped_total']} "
              f"unmapped={rep['unmapped_total']} ({rep['coverage_pct']}%)")
        for item in rep["unmapped"][:10]:
            print(f"  ! {item['file']} key={item['key']} ×{item['count']} — {item['reason']}")
        print(f"[coverage] → {rep.get('written_to')}")
        return 0
    if args.render:
        text = render(write=args.write)
        if args.write:
            print(f"[render] 已写入 {REGISTRY_MD.relative_to(ROOT)} ({len(text)} chars)")
        else:
            print(text)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
