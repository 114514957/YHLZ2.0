"""记忆样本问答相关性体检（ledger 0891 前置）。

目的：找出「答非所问」的记忆块（例如问"元创造力"答"我为什么叫元亨"）。
做法：本地 bge-small-zh 编码 问/答，算余弦；输出最不相关的 N 块（含原文）供清理。
只读：不改素材。

用法：python tools/v9_memory_relevance.py [--bottom 30] [--model models/emb/bge-small-zh]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "素材" / "记忆样本_v2.md"


def parse_blocks(text: str):
    blocks = re.split(r"(?m)^## ", text)[1:]
    for b in blocks:
        bid = b.splitlines()[0].strip()
        turns = []
        q = None
        for line in b.splitlines():
            m = re.match(r"^###\s+(.+?)问(\d+)\s*$", line)
            if m:
                q = None
                continue
            m2 = re.match(r"^###\s+元亨答(\d+)\s*$", line)
            if m2:
                q = "__ANS__"
                continue
            if q == "__ANS__" and line.strip():
                turns.append(("A", line.strip()))
                q = None
            elif q is None and line.strip() and not line.startswith("-") and not line.startswith("###"):
                turns.append(("Q", line.strip()))
                q = "seen"
        yield bid, turns


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--bottom", type=int, default=30)
    ap.add_argument("--model", default="models/emb/bge-small-zh")
    ap.add_argument("--out", default="cache/v9_materials_preparation/memory_relevance.json")
    args = ap.parse_args()

    import torch
    from transformers import AutoModel, AutoTokenizer

    model_dir = ROOT / args.model
    tok = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModel.from_pretrained(str(model_dir)).eval()

    qs, meta = [], []
    for bid, turns in parse_blocks(SRC.read_text(encoding="utf-8")):
        q = a = None
        for kind, txt in turns:
            if kind == "Q":
                q = txt
            elif kind == "A" and q:
                qs.append((q, txt))
                meta.append(bid)
                q, a = None, None

    print(f"[pairs] {len(qs)}")
    if not qs:
        return 2

    def enc(texts):
        with torch.no_grad():
            b = tok(texts, padding=True, truncation=True, max_length=256,
                    return_tensors="pt")
            out = model(**b).last_hidden_state[:, 0]
            return torch.nn.functional.normalize(out, dim=-1)

    sims = []
    B = 32
    for i in range(0, len(qs), B):
        chunk = qs[i:i + B]
        qe = enc([x[0] for x in chunk])
        ae = enc([x[1] for x in chunk])
        s = (qe * ae).sum(-1).tolist()
        sims.extend(s)

    rows = [{"block": meta[i], "q": qs[i][0][:90], "a": qs[i][1][:90],
             "sim": round(sims[i], 4)} for i in range(len(qs))]
    rows.sort(key=lambda r: r["sim"])
    report = {"pairs": len(rows), "all_pairs": rows,
              "sim_p10": rows[int(len(rows) * 0.1)]["sim"] if rows else None,
              "sim_median": rows[len(rows) // 2]["sim"] if rows else None,
              "bottom": rows[: args.bottom]}
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"pairs": report["pairs"], "sim_p10": report["sim_p10"],
                      "sim_median": report["sim_median"]}, ensure_ascii=False))
    for r in rows[:10]:
        print(f"  {r['sim']:.3f} {r['block']:8s} Q:{r['q'][:34]} | A:{r['a'][:34]}")
    print(f"[report] {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
