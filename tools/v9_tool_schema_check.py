"""工具轨迹的 schema 校验 + 覆盖率矩阵（ledger 0887）。

只查"名字真"不够——还要查**参数**：参数名必须在注册表 properties 里，必填项不能缺。
输出：每工具的覆盖数、非法参数、缺必填、未知工具；并给 JSON 报告。

用法：python tools/v9_tool_schema_check.py --in data/finetune/tool_use_v8.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "tool_registry" / "snapshot_latest.json"


def load_specs(path: pathlib.Path | None = None) -> dict[str, dict]:
    snap = json.loads((path or SNAP).read_text(encoding="utf-8"))
    return {t["name"]: t for t in snap["tools"]}


def iter_calls(path: pathlib.Path):
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        for m in d.get("messages") or []:
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                name = fn.get("name")
                if not name:
                    continue
                raw = fn.get("arguments")
                try:
                    args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    args = {}
                yield str(name), args if isinstance(args, dict) else {}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True)
    ap.add_argument("--report", default="cache/v9_materials_preparation/tool_schema_report.json")
    ap.add_argument("--registry", default="")
    args = ap.parse_args()
    reg = pathlib.Path(args.registry) if args.registry else None
    if reg and not reg.is_absolute():
        reg = ROOT / reg
    specs = load_specs(reg)
    allowed = set(specs)

    per_tool = Counter()
    bad_params: dict[str, Counter] = defaultdict(Counter)
    missing_required: dict[str, Counter] = defaultdict(Counter)
    unknown: Counter = Counter()
    total = 0

    for s in args.inputs:
        p = pathlib.Path(s)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            print("缺少", p, file=sys.stderr)
            return 2
        for name, a in iter_calls(p):
            total += 1
            if name not in allowed:
                unknown[name] += 1
                continue
            spec = specs[name]
            per_tool[name] += 1
            props = set(spec.get("properties") or [])
            req = set(spec.get("required") or [])
            bad = [k for k in a if k not in props]
            for k in bad:
                bad_params[name][k] += 1
            for k in req:
                if k not in a:
                    missing_required[name][k] += 1

    covered = sorted(per_tool)
    report = {
        "calls": total,
        "tools_total": len(allowed),
        "tools_covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / max(1, len(allowed)), 1),
        "unknown_tools": dict(unknown),
        "per_tool": dict(sorted(per_tool.items())),
        "bad_params": {k: dict(v) for k, v in bad_params.items()},
        "missing_required": {k: dict(v) for k, v in missing_required.items()},
        "missing_tools": sorted(allowed - set(covered)),
    }
    out = ROOT / args.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("calls", "tools_total", "tools_covered", "coverage_pct",
                       "unknown_tools")}, ensure_ascii=False, indent=1))
    print("缺参数/非法参数的工具数:", len(bad_params), len(missing_required))
    print(f"[report] {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
