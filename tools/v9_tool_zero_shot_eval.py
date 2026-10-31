"""零样本工具选择评测（ledger 0889）。

目的：验证「防错误泛化」——用**留出的 6 个工具**（训练集里没有）与 3 个对照工具，
让模型在 **全部 43 个真实工具**里选一个，看它：
  · 选对（correct）
  · 选错（wrong_tool）
  · 乱编工具名（fake_tool，应为 0）
  · 该不调用却调用 / 不该调用却调用（over_call / under_call）

**只推理、不执行**：直接打 llama.cpp `/v1/chat/completions`（带 tools），解析返回的
tool_calls；不经过 daemon，不会真的删台账/关 QQ。

用法：python tools/v9_tool_zero_shot_eval.py [--base http://127.0.0.1:8081]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "tool_registry" / "snapshot_latest.json"
SYNTH_REPORT = ROOT / "cache" / "v9_materials_preparation" / "tool_synth_report.json"
OUT = ROOT / "cache" / "v9_materials_preparation" / "tool_zero_shot_eval.json"

HELDOUT_PROMPTS = {
    "file_share": ["把 docs/notes.md 分享给老爹", "把那段日记发给老爹看看"],
    "ledger_add": ["记一条台账：今天把工具轨迹补到 200 条",
                   "帮我写条台账记录，说素材清单 v8 已完成"],
    "ledger_delete": ["把台账第 0810 条删掉", "那条重复的台账记录删了吧"],
    "ledger_update": ["把台账 0812 的标题改成「工具真实化」",
                      "更新一下台账 0805 的内容，补一句已验证"],
    "qq_runbatch": ["把上周的群聊批量跑一遍知识抽取", "按批次把 QQ 消息再处理一轮"],
    "qq_shutdown": ["把 QQ 桥关掉", "停一下 QQ 那边"],
}
CONTROL_PROMPTS = {
    "file_read": ["读一下 README.md 的前两行", "看看 docs/notes.md 里写了什么"],
    "memory_recall": ["我上次说过要买什么来着", "回忆一下关于素材的约定"],
    "system_time": ["现在几点了", "今天几号"],
}
NO_CALL_PROMPTS = ["在吗", "今天好累", "陪我聊会儿"]


def post(base: str, tools: list, prompt: str) -> dict:
    import urllib.request

    body = {"model": "local",
            "messages": [{"role": "system",
                          "content": "你是元亨。只能调用给定工具；不需要工具时直接回答。"},
                         {"role": "user", "content": prompt}],
            "tools": tools, "tool_choice": "auto",
            "temperature": 0, "max_tokens": 200}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用）")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from backend.target_scheduler_tools import setup_scheduler_capabilities

    tools = setup_scheduler_capabilities().export_openai_tools()
    allowed = {t["function"]["name"] for t in tools}
    holdout = []
    if SYNTH_REPORT.exists():
        holdout = json.loads(SYNTH_REPORT.read_text(encoding="utf-8")).get("holdout_tools") or []

    cases = []
    for name, prompts in HELDOUT_PROMPTS.items():
        for p in prompts:
            cases.append({"kind": "heldout", "expect": name, "prompt": p})
    for name, prompts in CONTROL_PROMPTS.items():
        for p in prompts:
            cases.append({"kind": "control", "expect": name, "prompt": p})
    for p in NO_CALL_PROMPTS:
        cases.append({"kind": "no-call", "expect": None, "prompt": p})
    if args.limit:
        cases = cases[: args.limit]

    results = []
    for c in cases:
        try:
            resp = post(args.base, tools, c["prompt"])
            m = (resp.get("choices") or [{}])[0].get("message") or {}
            calls = m.get("tool_calls") or []
            names = [((x.get("function") or {}).get("name")) for x in calls]
            if c["expect"] is None:
                verdict = "over_call" if names else "correct"
            elif not names:
                verdict = "under_call"
            elif any(n not in allowed for n in names):
                verdict = "fake_tool"
            elif c["expect"] in names:
                verdict = "correct"
            else:
                verdict = "wrong_tool"
            results.append({"kind": c["kind"], "expect": c["expect"],
                            "prompt": c["prompt"], "got": names,
                            "verdict": verdict,
                            "content": str(m.get("content") or "")[:80]})
        except Exception as exc:  # noqa: BLE001
            results.append({"kind": c["kind"], "expect": c["expect"],
                            "prompt": c["prompt"], "got": [],
                            "verdict": "error", "error": f"{type(exc).__name__}: {exc}"})
        r = results[-1]
        print(f"  {r['verdict']:10s} {r['kind']:8s} expect={r['expect']} got={r['got']}")
        time.sleep(0.3)

    def agg(items):
        n = len(items) or 1
        return {k: round(100.0 * sum(1 for x in items if x["verdict"] == k) / n, 1)
                for k in ("correct", "wrong_tool", "under_call", "over_call",
                          "fake_tool", "error")}

    by_kind = {k: agg([r for r in results if r["kind"] == k])
               for k in ("heldout", "control", "no-call")}
    report = {"cases": len(results), "holdout_tools": holdout,
              "fake_tool_total": sum(1 for r in results if r["verdict"] == "fake_tool"),
              "by_kind": by_kind, "results": results,
              "note": "只推理不执行；工具集为全部 43 个真实工具"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"cases": report["cases"], "by_kind": by_kind,
                      "fake_tool_total": report["fake_tool_total"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
