"""记忆块「答非所问」实测判定（ledger 0891 验证）。

不靠余弦猜——**让模型当裁判**：给（问题, 回答），只问「这个回答是在回应上面的问题吗？」，
答 是 / 部分 / 否。对照组是 keep 块，若 candidate 组显著更差，说明是配错了；
若两组接近，说明只是「摘要式问句」导致余弦低，不该降级。

用法：python tools/v9_memory_judge.py [--base http://127.0.0.1:8081] [--control 20]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import sys
import urllib.request
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
REL = ROOT / "cache" / "v9_materials_preparation" / "memory_relevance.json"
SRC = ROOT / "docs" / "素材" / "记忆样本_v2.1.md"
OUT = ROOT / "cache" / "v9_materials_preparation" / "memory_judge.json"

PROMPT = ("问题：{q}\n\n回答：{a}\n\n这个回答是在回应上面的问题吗？"
          "只回一个词：是 / 部分 / 否")


def ask(base: str, q: str, a: str) -> str:
    body = {"model": "local",
            "messages": [{"role": "user", "content": PROMPT.format(q=q, a=a)}],
            "temperature": 0, "max_tokens": 6}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=120).read())
    txt = str((d.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    if "否" in txt:
        return "否"
    if "部分" in txt:
        return "部分"
    if "是" in txt:
        return "是"
    return "?"


def load_blocks() -> dict[str, str]:
    """块 ID → status（从 v2.1 读）。"""
    out = {}
    text = SRC.read_text(encoding="utf-8")
    for part in re.split(r"(?m)^## ", text)[1:]:
        bid = part.splitlines()[0].strip()
        m = re.search(r"(?m)^-\s*status:\s*(\w+)", part)
        if bid and m:
            out[bid] = m.group(1)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--control", type=int, default=20)
    args = ap.parse_args()

    rel = json.loads(REL.read_text(encoding="utf-8"))
    status = load_blocks()
    cand = [r for r in rel["bottom"] if status.get(r["block"]) == "candidate"]
    # 对照组：keep 块里随机抽（相似度分布中段）
    keep_pairs = [r for r in rel["bottom"]]
    kept = [r for r in json.loads(REL.read_text(encoding="utf-8")).get("all_pairs", [])
            if status.get(r["block"]) == "keep"]
    random.seed(7)
    control = random.sample(kept, min(args.control, len(kept))) if kept else []

    res = {"candidate": [], "control": []}
    for label, rows in (("candidate", cand), ("control", control)):
        for r in rows:
            try:
                v = ask(args.base, r["q"], r["a"])
            except Exception as exc:  # noqa: BLE001
                v = f"ERR:{type(exc).__name__}"
            res[label].append({**r, "judge": v})
            print(f"  [{label}] {r['block']:8s} {v} | Q:{r['q'][:26]} | A:{r['a'][:26]}")

    def dist(rows):
        c = Counter(x["judge"] for x in rows)
        n = len(rows) or 1
        return {k: round(100.0 * v / n, 1) for k, v in c.items()}

    report = {"candidates": len(cand), "control": len(control),
              "candidate_dist": dist(res["candidate"]),
              "control_dist": dist(res["control"]),
              "verdict": None, "details": res}
    cd = report["candidate_dist"].get("是", 0) + 0.5 * report["candidate_dist"].get("部分", 0)
    kd = report["control_dist"].get("是", 0) + 0.5 * report["control_dist"].get("部分", 0)
    report["verdict"] = ("candidate 明显更差 → 确实配错" if cd + 15 < kd
                         else "两组接近 → 低余弦主要是摘要式问句，降级过度")
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("candidates", "control", "candidate_dist",
                       "control_dist", "verdict")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
