"""Assemble a versioned persona SFT training set (ledger 0338).

Merges two real sources into one chat-format dataset:
  - `data/finetune/sft_persona.jsonl`  : real 老爹<->元亨 session pairs
  - `tools/persona_golden.md`          : owner-approved golden samples (keep/fixed)
Deduplicates by (user, assistant), stamps a fixed persona system prompt, and
writes `data/finetune/sft_persona_<tag>.jsonl` + `..._<tag>.stats.json`.

Versioning: each round writes a new `--tag` (default from config); training/
splitting consume `sft_persona_<tag>_train.jsonl` / `_val.jsonl`.

Usage:
    python tools/finetune_assemble.py --tag v1
    python tools/finetune_assemble.py --tag v1 --no-golden
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SYSTEM = (
    "你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。好奇心爆棚、"
    "活泼话多，傲娇得很，其实最在意老爹。像人对朋友说话：短、口语、有起伏；"
    "自称按情绪切换（我/咱/元亨/老娘/本小姐）；禁止助手腔/报告腔、列表、小标题。"
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _fp(u: str, a: str) -> str:
    return hashlib.sha256((_norm(u) + "|" + _norm(a)).encode("utf-8")).hexdigest()[:24]


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "finetune.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    ap = argparse.ArgumentParser(description="装配版本化人格 SFT 训练集")
    ap.add_argument("--tag", default=cfg.get("tag", "v1"))
    ap.add_argument("--golden", default=str(ROOT / "docs" / "素材" / "黄金样本.md"))
    ap.add_argument("--no-golden", dest="no_golden", action="store_true")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "finetune"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"sft_persona_{args.tag}.jsonl"
    stats_path = out_dir / f"sft_persona_{args.tag}.stats.json"

    records, seen = [], set()

    def add(user: str, assistant: str, source: str) -> None:
        u, a = str(user).strip(), str(assistant).strip()
        if not u or not a:
            return
        k = _fp(u, a)
        if k in seen:
            return
        seen.add(k)
        records.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": u},
            {"role": "assistant", "content": a},
        ], "source": source})

    n_real = 0
    for r in _read_jsonl(out_dir / "sft_persona.jsonl"):
        msgs = r.get("messages") or []
        u = next((m.get("content") for m in msgs if m.get("role") == "user"), "")
        a = next((m.get("content") for m in msgs if m.get("role") == "assistant"), "")
        before = len(records)
        add(u, a, r.get("source", "session"))
        n_real += len(records) - before

    n_gold = 0
    if not args.no_golden:
        from tools.golden_build import load_golden
        for g in load_golden(Path(args.golden)):
            if g.get("status") in ("keep", "fixed"):
                before = len(records)
                add(g["user"], g["assistant"], f"golden-{g['id']}")
                n_gold += len(records) - before

    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    out.write_text(body + ("\n" if records else ""), encoding="utf-8")
    stats = {"tag": args.tag, "total": len(records), "real_pairs": n_real,
             "golden_pairs": n_gold, "file": str(out.relative_to(ROOT))}
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
