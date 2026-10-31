"""按老爹的选择生成"核心池"签字文件（ledger 0877）。

老爹 2026-10-20 选择：只签**核心 1143 行**（memory / honesty / uncertain / refusal /
golden / real），scene 虚构小剧场 1978 行暂不签。

本脚本只做三件事：
  1) 从三份导出稿里挑出"核心来源 + 属于既有批次"的行；
  2) 生成 `cache/v9_materials_preparation/sign_batches_core.json`
     （reviewer=dad、signed_at=今天、block_ids/content_hashes=这些行）；
  3) 打印来源分布，供对账。**不修改原始 exports/素材**。

用法：python tools/v9_sign_core.py [--reviewer dad] [--date 2026-10-20]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGN = ROOT / "cache" / "v9_materials_preparation" / "sign_batches.json"
OUT = ROOT / "cache" / "v9_materials_preparation" / "sign_batches_core.json"
DATA = ROOT / "data" / "finetune"
CORE = ("memory", "honesty", "uncertain", "refusal", "golden", "real")


def bof(rec: dict) -> str:
    raw = str(rec.get("source_id") or rec.get("source") or "")
    if "#" in raw:
        raw = raw.split("#", 1)[1]
    return raw.split("｜")[0].split("|")[0].strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", default="dad")
    ap.add_argument("--date", default="2026-10-20")
    args = ap.parse_args()
    if not SIGN.exists():
        print("缺少", SIGN, file=sys.stderr)
        return 2
    batch = json.loads(SIGN.read_text(encoding="utf-8"))["batches"][0]
    blocks, hashes = set(batch["block_ids"]), set(batch["content_hashes"])

    picked_blocks: set[str] = set()
    picked_hashes: set[str] = set()
    cnt = Counter()
    for split in ("train", "val", "test"):
        p = DATA / f"sft_persona_v8r4t_{split}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            src = str(r.get("source") or "")
            if src.startswith("lizhen"):
                continue
            if str(r.get("consent_status")) == "pending":
                continue
            key = src.split(":")[0]
            if key not in CORE:
                continue
            if bof(r) not in blocks and str(r.get("content_hash")) not in hashes:
                continue
            picked_blocks.add(bof(r))
            if r.get("content_hash"):
                picked_hashes.add(str(r["content_hash"]))
            cnt[key] += 1

    data = {"generated_at": f"{args.date}T00:00:00",
            "note": "老爹 2026-10-20 选择：只签核心池；scene 未签",
            "batches": [{"batch_id": "B01-core-1143", "reviewer": args.reviewer,
                         "signed_at": args.date, "rows": sum(cnt.values()),
                         "block_ids": sorted(picked_blocks),
                         "content_hashes": sorted(picked_hashes)}]}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"rows": sum(cnt.values()), "blocks": len(picked_blocks),
                      "by_source": dict(cnt), "out": str(OUT.relative_to(ROOT))},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
