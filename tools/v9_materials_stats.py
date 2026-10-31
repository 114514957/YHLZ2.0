"""素材总账统计（ledger 0895）。

一次算清：PT 池 / SFT 稿 / 素材源文件 / 生成集 / QQ / 小说 / 工具注册表 / 门禁隔离原因，
输出 markdown + 控制台摘要。

用法：python tools/v9_materials_stats.py [--out docs/报告/素材总账_20261020.md]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAT = ROOT / "docs" / "素材"


def count_lines(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
               if line.strip())


def pt_stats() -> dict:
    man = DATA / "pt" / "manifest.json"
    if not man.exists():
        return {}
    d = json.loads(man.read_text(encoding="utf-8"))
    pools = {}
    for k, v in (d.get("pools") or {}).items():
        pools[k] = v.get("docs") if isinstance(v, dict) else v
    return {"docs": d.get("total_docs"), "tokens": d.get("total_tokens"),
            "chars": d.get("total_chars"), "coverage": d.get("coverage_vs_target"),
            "pools": pools}


def latest_tag() -> str:
    tags = []
    for p in (DATA / "finetune").glob("sft_persona_v9*_train.jsonl"):
        tags.append(p.name.split("_")[2])
    return sorted(tags)[-1] if tags else "v9u"


def sft_stats() -> dict:
    tag = latest_tag()
    out = {"tag": tag}
    for split in ("train", "val", "test"):
        p = DATA / "finetune" / f"sft_persona_{tag}_{split}.jsonl"
        rows = []
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        out[split] = len(rows)
        if split == "train":
            c = Counter(str(r.get("source", "")).split(":")[0] for r in rows)
            out["by_source"] = dict(c.most_common(12))
            out["simulation"] = sum(1 for r in rows if r.get("simulation"))
    return out


def material_stats() -> dict:
    rows = []
    for p in sorted(MAT.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        blocks = re.split(r"(?m)^## ", text)[1:]
        st = Counter()
        for b in blocks:
            m = re.search(r"(?m)^-\s*status:\s*(\w+)", b)
            st[m.group(1) if m else "?"] += 1
        rows.append({"file": p.name, "blocks": len(blocks), "status": dict(st),
                     "kb": round(p.stat().st_size / 1024, 1)})
    return {"files": rows, "total_blocks": sum(r["blocks"] for r in rows)}


def generated_stats() -> dict:
    out = {}
    for name in ("tool_use_v9_synth.jsonl", "memory_qstyle.jsonl",
                 "cot_samples.jsonl", "cot_deep.jsonl"):
        p = DATA / "finetune" / name
        out[name] = count_lines(p)
    return out


def qq_stats() -> dict:
    p = DATA / "finetune" / "corpus_qq_raw_all.jsonl"
    groups = Counter()
    rows = 0
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                groups[json.loads(line).get("group")] += 1
            except Exception:
                pass
    return {"messages": rows, "groups": dict(groups)}


def novel_stats() -> dict:
    p = DATA / "pd" / "v9_novels.jsonl"
    rows = chars = 0
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            rows += 1
            chars += len(json.loads(line).get("text") or "")
    return {"blocks": rows, "chars": chars}


def gate_stats() -> dict:
    p = DATA / "finetune" / f"sft_persona_{latest_tag()}_gated_gate_report.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {"totals": d.get("totals"), "written": {k: v["rows"] for k, v in
                                                   (d.get("written") or {}).items()},
            "verdict": d.get("verdict")}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pt, sft, mat, gen, qq, nov, gate = (pt_stats(), sft_stats(), material_stats(),
                                        generated_stats(), qq_stats(), novel_stats(),
                                        gate_stats())
    lines = ["# 素材总账 · 2026-10-20", ""]
    lines += ["## 1. PT（continued pretraining）", ""]
    if pt:
        lines += [f"- 总篇数 **{pt['docs']:,}** / token **{pt['tokens']:,}** / 字符 "
                  f"**{pt['chars']:,}** / 8 万目标 **{pt['coverage']*100:.2f}%**", "",
                  "| 池 | 篇数 | 目标 | 占比 |", "|---|---|---|---|"]
        target = {"self_core": 4000, "speaking_general": 36000,
                  "tools_concept": 24000, "context": 16000}
        for k, v in (pt.get("pools") or {}).items():
            t = target.get(k)
            pct = f"{100.0*v/t:.1f}%" if t else "-"
            lines.append(f"| {k} | {v:,} | {t:,} | {pct} |" if t else f"| {k} | {v:,} | - | - |")
    lines += ["", "## 2. SFT 稿（" + str(sft.get("tag") or "v9u") + "）", "",
              f"- train **{sft.get('train',0):,}** / val **{sft.get('val',0):,}** / "
              f"test **{sft.get('test',0):,}**",
              f"- 带 `simulation: true` 的行：**{sft.get('simulation',0):,}**", "",
              "| 来源 | 行数 |", "|---|---|"]
    for k, v in (sft.get("by_source") or {}).items():
        lines.append(f"| {k} | {v:,} |")
    lines += ["", "## 3. 素材源文件（docs/素材）", "",
              f"- 合计 **{mat['total_blocks']:,}** 块 / {len(mat['files'])} 个文件", "",
              "| 文件 | 块数 | 状态分布 |", "|---|---|---|"]
    for r in mat["files"]:
        st = ", ".join(f"{k} {v}" for k, v in sorted(r["status"].items()))
        lines.append(f"| {r['file']} | {r['blocks']} | {st} |")
    lines += ["", "## 4. 生成集", "", "| 文件 | 条数 |", "|---|---|"]
    for k, v in gen.items():
        lines.append(f"| {k} | {v:,} |")
    lines += ["", "## 5. 真实对话（QQ）", "",
              f"- 消息 **{qq['messages']:,}** 条 / {len(qq['groups'])} 个群", ""]
    for g, n in sorted(qq["groups"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  - `{g}`：{n:,}")
    lines += ["", "## 6. 小说/公版", "",
              f"- `v9_novels.jsonl`：**{nov['blocks']:,}** 块 / {nov['chars']:,} 字", ""]
    lines += ["## 7. 工具注册表", "", "- **43** 个真实工具；留出 6 个（file_share、ledger_add/delete/update、qq_runbatch、qq_shutdown）", ""]
    lines += ["## 8. 门禁（v9u）", ""]
    if gate:
        lines.append(f"- 结论：{gate.get('verdict')}")
        for k, v in (gate.get("totals") or {}).items():
            lines.append(f"  - {k}: {v:,}")
        lines.append(f"- 正式集行数：{gate.get('written')}")
    lines += ["", "## 9. 缺口（按 8 万目标）", ""]
    if pt:
        pools = pt.get("pools") or {}
        for k, t in (("speaking_general", 36000), ("tools_concept", 24000),
                     ("context", 16000), ("self_core", 4000)):
            have = pools.get(k, 0)
            lines.append(f"- {k}: {have:,} / {t:,}（缺 {t-have:,}）")
    out = ROOT / "docs" / "报告" / "素材总账_20261020.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[report] {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
