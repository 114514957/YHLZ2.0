"""用元亨的导出器产物回灌 QQ 语料（ledger 0872）。

老爹 2026-10-20：「你来通过元亨的工具进行导出」。
现状：QCE 服务（127.0.0.1:40653）未运行，但 `~/.qq-chat-exporter/exports/` 已有 **24 份
`group_*.json`**（2026-09-06 ~ 09-19）。本脚本复用 `tools/qq_pull_raw.py` 的
`raw_records()` 解析口径，把所有导出**合并去重**写成新的原始语料，再交给 PT 装配。

用法：python tools/v9_qq_reingest.py [--glob-dir ...] [--out ...]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from qq_pull_raw import QCE_BASE, raw_records  # noqa: E402

EXPORTS = pathlib.Path.home() / ".qq-chat-exporter" / "exports"
OUT = ROOT / "data" / "finetune" / "corpus_qq_raw_all.jsonl"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob-dir", default=str(EXPORTS))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    src = pathlib.Path(args.glob_dir)
    files = sorted(src.glob("group_*.json"), key=lambda p: p.stat().st_mtime)
    print(f"导出文件 {len(files)} 个（{src}）")
    if not files:
        print("没有可用的 group_*.json；请先启动 QCE（%s）再跑 tools/qq_pull_raw.py" % QCE_BASE,
              file=sys.stderr)
        return 2

    seen: set[tuple[str, str]] = set()
    rows = []
    per_group: Counter = Counter()
    per_file: list[dict] = []
    for fp in files:
        n0 = len(rows)
        try:
            for rec in raw_records(fp):
                key = (rec["group"], rec["msg_id"] or f"{fp.stem}:{rec['seq']}")
                if key in seen:
                    continue
                seen.add(key)
                if rec.get("system") or rec.get("recalled"):
                    continue
                if not str(rec.get("text") or "").strip():
                    continue
                rows.append(rec)
                per_group[rec["group"]] += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {fp.name}: {type(exc).__name__}")
            continue
        per_file.append({"file": fp.name, "added": len(rows) - n0,
                         "size_kb": fp.stat().st_size // 1024})
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest = {"files": len(files), "messages": len(rows),
                "groups": dict(per_group.most_common()),
                "out": str(out.relative_to(ROOT)),
                "per_file": per_file}
    (out.parent / "qq_raw_all_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"files": len(files), "messages": len(rows),
                      "top_groups": dict(per_group.most_common(8))},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
