"""R3 包C：关键工具题重复基线 runner（不改判分，不覆盖历史）。

用法：python tools/r3_tool_subset.py [--reps 3] [--tag zh21-base]
- 对 persona_bank 中「有期望工具」的题（16 类去空）重复跑，每题每轮新隔离会话；
- 落盘原始逐题结果 + scorer_v2 四类分类；报告逐项波动。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools.persona_bank import PERSONA_BANK  # noqa: E402
from tools.persona_regression import run_live  # noqa: E402
from tools.scorer_v2 import classify_tool_item  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tag", default="zh21-base")
    ap.add_argument("--url", default="http://127.0.0.1:8081/v1/chat/completions")
    args = ap.parse_args()

    bank = [e for e in PERSONA_BANK if e.get("expect_any_tool")]
    print(f"工具题 {len(bank)} 道 × {args.reps} 轮 = {len(bank) * args.reps} 回合")
    outdir = pathlib.Path(f"artifacts/nonvoice_next_stage/20261003-r3-C-{args.tag}")
    outdir.mkdir(parents=True, exist_ok=True)

    all_rounds = []
    for rep in range(1, args.reps + 1):
        results, env = await run_live(bank, base_url=args.url,
                                      expect_lora="yuanheng-v8-lora.gguf")
        rows = [classify_tool_item(e, r.get("tools") or [], r.get("answer", ""))
                for e, r in zip(bank, results)]
        (outdir / f"round{rep}.json").write_text(
            json.dumps({"env": {k: env.get(k) for k in ("base_url", "lora")},
                        "results": results, "classes": rows},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        sel = sum(1 for r in rows if r["tool_selected"])
        print(f"[round{rep}] 选择工具 {sel}/{len(rows)}")
        for r in rows:
            print(f"    {r['id']}: {r['class']}")
        all_rounds.append(rows)

    # 逐题转移（跨轮是否稳定）
    print("\n== 逐题跨轮 ==")
    for i, e in enumerate(bank):
        seq = [all_rounds[k][i]["class"] for k in range(args.reps)]
        stable = len(set(seq)) == 1
        print(f"  {e['id']}: {'稳定' if stable else '**波动**'} {seq}")
    return 0


raise SystemExit(asyncio.run(main()))
