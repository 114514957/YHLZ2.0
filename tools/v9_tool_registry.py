"""工具注册表快照 / 校验 / 漂移检测（ledger 0886）。

老爹 2026-10-20：「工具必须真实，必须可拓展」。

真实能力源：`backend.target_scheduler_tools.setup_scheduler_capabilities().export_openai_tools()`
（当前 43 项）。本工具做三件事：
  --snapshot   把当前注册表导出成 JSON 快照（含 sha16、工具名、必填参数），
               作为训练数据的"合法工具白名单"证据
  --check      校验一份轨迹文件里的工具名是否**全部**在快照白名单里（假名即 FAIL）
  --drift      快照 vs 当前注册表：新增/删除/参数变化（可拓展性回归——
               后端加工具后，这里会点名"训练数据还没跟上"）

用法：
  python tools/v9_tool_registry.py --snapshot
  python tools/v9_tool_registry.py --check data/finetune/tool_use_v8.jsonl
  python tools/v9_tool_registry.py --drift
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tool_registry"


def live_specs() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from backend.target_scheduler_tools import setup_scheduler_capabilities

    return setup_scheduler_capabilities().export_openai_tools()


def snapshot_path() -> pathlib.Path:
    files = sorted(OUT_DIR.glob("snapshot_*.json"))
    return files[-1] if files else OUT_DIR / "snapshot_latest.json"


def do_snapshot() -> int:
    specs = live_specs()
    items = []
    for t in specs:
        fn = t.get("function") or {}
        params = fn.get("parameters") or {}
        items.append({"name": fn.get("name"),
                      "description": str(fn.get("description") or "")[:200],
                      "required": list(params.get("required") or []),
                      "properties": sorted((params.get("properties") or {}).keys())})
    items.sort(key=lambda x: x["name"])
    blob = json.dumps(items, ensure_ascii=False, sort_keys=True)
    sha = hashlib.sha256(blob.encode()).hexdigest()[:16]
    import time

    stamp = time.strftime("%Y%m%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"snapshot_{stamp}_{sha}.json"
    data = {"snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sha16": sha,
            "count": len(items), "tools": items}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "snapshot_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"count": len(items), "sha16": sha,
                      "out": str(out.relative_to(ROOT))}, ensure_ascii=False))
    return 0


def tool_names_in(path: pathlib.Path) -> dict[str, int]:
    import collections

    out: collections.Counter = collections.Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        for m in d.get("messages") or []:
            for c in (m.get("tool_calls") or []):
                fn = (c.get("function") or {}).get("name")
                if fn:
                    out[fn] += 1
            if m.get("role") == "tool" and m.get("name"):
                out[m["name"]] += 1
        for name in d.get("tools") or []:
            if isinstance(name, str):
                out[name] += 0
    return dict(out)


def do_check(path: pathlib.Path) -> int:
    snap = json.loads(snapshot_path().read_text(encoding="utf-8"))
    allowed = {t["name"] for t in snap["tools"]}
    used = tool_names_in(path)
    bad = {k: v for k, v in used.items() if k not in allowed}
    ok = not bad
    print(json.dumps({"file": str(path.relative_to(ROOT)) if path.is_absolute() else str(path),
                      "snapshot_sha16": snap["sha16"], "snapshot_count": len(allowed),
                      "used_tools": len(used), "calls": sum(used.values()),
                      "fake_tools": bad, "verdict": "PASS" if ok else "FAIL"},
                     ensure_ascii=False, indent=1))
    return 0 if ok else 1


def do_drift() -> int:
    snap = json.loads(snapshot_path().read_text(encoding="utf-8"))
    old = {t["name"]: t for t in snap["tools"]}
    new = {}
    for t in live_specs():
        fn = t.get("function") or {}
        params = fn.get("parameters") or {}
        new[fn.get("name")] = {"name": fn.get("name"),
                               "required": list(params.get("required") or []),
                               "properties": sorted((params.get("properties") or {}).keys())}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(n for n in set(old) & set(new)
                     if (old[n]["required"], old[n]["properties"]) !=
                     (new[n]["required"], new[n]["properties"]))
    print(json.dumps({"snapshot_sha16": snap["sha16"],
                      "old_count": len(old), "live_count": len(new),
                      "added": added, "removed": removed, "changed": changed,
                      "drift": bool(added or removed or changed)},
                     ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--drift", action="store_true")
    args = ap.parse_args()
    if args.snapshot:
        return do_snapshot()
    if args.check:
        p = pathlib.Path(args.check)
        return do_check(p if p.is_absolute() else ROOT / p)
    if args.drift:
        return do_drift()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
