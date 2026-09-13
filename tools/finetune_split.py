"""Split persona SFT data into train/val (ledger 0318 §B2 step 5).

Reads `data/finetune/sft_persona.jsonl` (from `finetune_build.py`) and writes a
deterministic, seeded split to `sft_persona_train.jsonl` / `sft_persona_val.jsonl`
so `finetune_train.py` can hold out a validation slice. Config-driven via
`config/finetune.json`; CLI flags override.

Usage:
    python tools/finetune_split.py                 # 用 config 默认
    python tools/finetune_split.py --ratio 0.2 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msgs = rec.get("messages")
        if isinstance(msgs, list) and msgs:
            out.append(rec)
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    path.write_text(body + ("\n" if rows else ""), encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "finetune.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    ap = argparse.ArgumentParser(description="切分人格 SFT 数据为 train/val")
    ap.add_argument("--config", default=str(cfg_path))
    ap.add_argument("--in", dest="data_in", default=None)
    ap.add_argument("--train", default=None)
    ap.add_argument("--val", default=None)
    ap.add_argument("--ratio", type=float, default=None, help="验证集比例，默认取 config")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    data_in = ROOT / (args.data_in or cfg.get("data_in", "data/finetune/sft_persona.jsonl"))
    train_path = ROOT / (args.train or cfg.get("train_file", "data/finetune/sft_persona_train.jsonl"))
    val_path = ROOT / (args.val or cfg.get("val_file", "data/finetune/sft_persona_val.jsonl"))
    ratio = args.ratio if args.ratio is not None else float(cfg.get("val_ratio", 0.15))
    seed = args.seed if args.seed is not None else int(cfg.get("seed", 20260913))

    rows = _read_jsonl(data_in)
    if not rows:
        print(f"[split] 无数据：{data_in}", file=sys.stderr)
        return 1

    rng = random.Random(seed)
    rng.shuffle(rows)
    n_val = max(1, round(len(rows) * ratio)) if len(rows) > 1 else 0
    n_val = min(n_val, len(rows) - 1) if len(rows) > 1 else 0
    val, train = rows[:n_val], rows[n_val:]

    _write_jsonl(train_path, train)
    _write_jsonl(val_path, val)
    stats = {
        "in": str(data_in.relative_to(ROOT)),
        "total": len(rows),
        "train": len(train),
        "val": len(val),
        "val_ratio": round(len(val) / len(rows), 4),
        "seed": seed,
        "train_file": str(train_path.relative_to(ROOT)),
        "val_file": str(val_path.relative_to(ROOT)),
    }
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
