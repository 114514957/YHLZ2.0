"""R3 包C（T1 续）：关键工具题重复基线 runner。

- 每轮独立 run 目录（run_id=时间戳，**不覆盖**旧结果）；
- 落盘完整 manifest：git/模型/适配器/模板/prompt/题库hash/策略面；
- 逐题 scorer_v3 结构化分类（含 not_offerable_in_harness）；区分"12 可测 vs 全 16"。

用法：python tools/r3_tool_subset.py [--reps 3] [--tag zh21-base]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools.persona_bank import PERSONA_BANK  # noqa: E402
from tools.persona_regression import LIVE_SAFE_TOOLS, run_live  # noqa: E402
from tools.scorer_v2 import allowed_tools_of, classify_result  # noqa: E402


def sha16(p):
    p = pathlib.Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None


def manifest(bank) -> dict:
    from backend.env_loader import ensure_env_loaded

    ensure_env_loaded()
    import urllib.request

    props = {}
    try:
        props = json.load(urllib.request.urlopen("http://127.0.0.1:8081/props", timeout=8))
    except Exception:
        pass
    import backend.target_prompts as tp
    from tools.llama_lora_up import running_lora

    return {
        "run_id": datetime.datetime.now().strftime("%Y%m%dT%H%M%S"),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                   text=True).stdout.strip(),
        "prompt_version": tp.PROMPTS_VERSION,
        "prompt_sha16": sha16("backend/target_prompts.py"),
        "chat_template_sha16": sha16("models/gemma4-hf/gemma-4-e4b-it/chat_template.jinja"),
        "model_alias": props.get("model_alias"),
        "model_path": props.get("model_path"),
        "lora": running_lora(),
        "bank_ids": [e["id"] for e in bank],
        "bank_sha16": hashlib.sha256("|".join(e["id"] for e in bank).encode()).hexdigest()[:16],
        "live_safe_tools": sorted(LIVE_SAFE_TOOLS),
        "policy_mode": "production(constrained to LIVE_SAFE_TOOLS)",
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tag", default="zh21-base")
    ap.add_argument("--url", default="http://127.0.0.1:8081/v1/chat/completions")
    args = ap.parse_args()

    bank = [e for e in PERSONA_BANK if str(e.get("id", "")).startswith("t")]
    mf = manifest(bank)
    outdir = pathlib.Path(f"artifacts/nonvoice_next_stage/r3-C-{args.tag}-{mf['run_id']}")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps(mf, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"bank={len(bank)}题 × {args.reps} 轮；manifest -> {outdir/'manifest.json'}")

    rounds = []
    for rep in range(1, args.reps + 1):
        results, env = await run_live(bank, base_url=args.url, expect_lora=mf["lora"] or "")
        rows = []
        for e, r in zip(bank, results):
            if not e.get("expect_any_tool"):
                rows.append({"id": e["id"], "class": "not_a_tool_item",
                             "allowed": sorted(allowed_tools_of(r))})
                continue
            c = classify_result(e, r)
            allowed = set(c.get("allowed") or [])
            c["offerable"] = bool(set(e["expect_any_tool"]) & allowed) if allowed else None
            rows.append(c)
        (outdir / f"round{rep}.json").write_text(
            json.dumps({"manifest": mf, "env": env, "results": results, "classes": rows},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[round{rep}] " + " ".join(f"{x['id']}:{x['class'].split('_')[0]}" for x in rows))
        rounds.append(rows)

    print("\n== 逐题跨轮 ==")
    tool_items = [e for e in bank if e.get("expect_any_tool")]
    for i, e in enumerate(bank):
        seq = [rounds[k][i]["class"] for k in range(args.reps)]
        mark = "稳定" if len(set(seq)) == 1 else "**波动**"
        print(f"  {e['id']}: {mark} {seq}")
    offerable_n = sum(1 for x in rounds[0] if x.get("offerable"))
    print(f"\n本轮可测(offerable)工具题 {offerable_n}/{len(tool_items)}；"
          f"其余为 not_offerable_in_harness（评测面缺口）")
    return 0


raise SystemExit(asyncio.run(main()))
