"""双签审阅单：把待签批次（sign_batches.json）做成可读清单（ledger 0875）。

用途：老爹要看「要签的是什么」——本脚本抽 N 条覆盖各来源/各池，给出来源、块 ID、指纹前 8 位、
      前 120 字预览，附批次统计与签字方法。**不改数据、不代表签署**。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGN = ROOT / "cache" / "v9_materials_preparation" / "sign_batches.json"
DATA = ROOT / "data" / "finetune"


def block_of(rec: dict) -> str:
    raw = str(rec.get("source_id") or rec.get("source") or "")
    if "#" in raw:
        raw = raw.split("#", 1)[1]
    return raw.split("｜")[0].split("|")[0].strip()


def preview(rec: dict, n: int = 120) -> str:
    for m in rec.get("messages") or []:
        if m.get("role") == "user" and m.get("content"):
            t = " ".join(str(m["content"]).split())
            return t[:n]
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--out", default="docs/报告/双签审阅单_20261020.md")
    args = ap.parse_args()
    if not SIGN.exists():
        print("缺少", SIGN, file=sys.stderr)
        return 2
    sign = json.loads(SIGN.read_text(encoding="utf-8"))
    batch = (sign.get("batches") or [{}])[0]
    blocks = set(batch.get("block_ids") or [])
    hashes = set(batch.get("content_hashes") or [])

    files = [DATA / f"sft_persona_v8r4t_{s}.jsonl" for s in ("train", "val", "test")]
    rows = []
    for p in files:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if str(r.get("source", "")).startswith("lizhen"):
                continue
            if str(r.get("consent_status")) == "pending":
                continue
            if block_of(r) in blocks or str(r.get("content_hash")) in hashes:
                rows.append(r)

    by_source: dict[str, list] = defaultdict(list)
    for r in rows:
        by_source[str(r.get("source")) or "?"].append(r)
    total = len(rows)
    picks = []
    per = max(1, args.samples // max(1, len(by_source)))
    for src, items in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        step = max(1, len(items) // per)
        picks.extend(items[::step][:per])
    picks = picks[: args.samples]

    lines = ["# 双签审阅单 · 2026-10-20", "",
             "> 待签批次来自 `cache/v9_materials_preparation/sign_batches.json`。",
             "> 本单只做**抽样展示**（不代表已签）；签字 = 在 JSON 里填 reviewer / signed_at。", "",
             "## 批次", "",
             f"- batch_id：`{batch.get('batch_id')}`",
             f"- 覆盖块：**{len(blocks)}**",
             f"- 覆盖行：**{batch.get('rows') or total}**",
             f"- 实际命中（本机重算）：**{total}** 行",
             f"- 来源分布：" + "，".join(f"`{k}` {len(v)}" for k, v in
                                          sorted(by_source.items(), key=lambda kv: -len(kv[1]))[:8]),
             "", "## 抽样（每来源均匀抽取，共 %d 条）" % len(picks), "",
             "| # | 来源 | 块 ID | 指纹 | 用户话预览 |", "|---|---|---|---|---|"]
    for i, r in enumerate(picks, 1):
        lines.append(f"| {i} | `{str(r.get('source'))[:28]}` | `{block_of(r)}` | "
                     f"`{str(r.get('content_hash'))[:8]}` | {preview(r)} |")
    lines += ["", "## 签字方法（二选一）", "",
              "1. 直接编辑 `sign_batches.json`：把 `reviewer` 填 `dad`、`signed_at` 填 `2026-10-20`，然后：",
              "   ```bash",
              "   python tools/v9_out_gate.py --in data/finetune/sft_persona_v8r4t_train.jsonl \\",
              "     --in data/finetune/sft_persona_v8r4t_val.jsonl \\",
              "     --in data/finetune/sft_persona_v8r4t_test.jsonl \\",
              "     --out-prefix data/finetune/sft_persona_v9 \\",
              "     --sign-file cache/v9_materials_preparation/sign_batches.json",
              "   ```",
              "2. 或告诉我「签 B01」，我把 reviewer/signed_at 填好重跑四门（等于你授权我代填，留痕仍记 dad）。",
              "", "## 通过后会发生什么", "",
              "- 四门结果从 `BLOCKED` 变 `PASS`，正式集生成 `data/finetune/sft_persona_v9_{train,val,test}.jsonl`；",
              "- 利贞 300 条仍未进（已分池）；pending 626 条仍在隔离池；",
              "- `gaps` 里「双签未完成」一条消除。"]
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"total_rows": total, "sources": len(by_source),
                      "samples": len(picks), "out": str(out.relative_to(ROOT))},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
