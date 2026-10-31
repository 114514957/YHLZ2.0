#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""基座对比测试：同一套 48 题、同一 system prompt、同一确定性判据。

用途：在换基座前回答一个问题——**未微调的 Qwen3.5-4B 底座，是否已经打平/超过现役 Gemma+v7b LoRA**。

设计（保证可比）：
  · 题目：`tools/persona_bank.PERSONA_BANK`（48 题：人格 20 / 关系 12 / 工具遵循 16）
  · system prompt：`backend.target_prompts.render_system_prompt()`（生产同源）
  · 判据：`tools/persona_bank.verify()`（确定性，无 LLM 判官）
  · 采样：两模型同一组参数（temperature/top_p/top_k 取低值以稳定复现）

支持两种后端：
  --backend ollama  --model qwen3.5:4b        （Ollama /api/chat）
  --backend openai  --base-url http://127.0.0.1:8081/v1 --model gemma-4-e4b  （llama-server）

用法：
    python tools/v9_base_compare.py --backend ollama --model qwen3.5:4b --tag qwen35_4b
    python tools/v9_base_compare.py --backend openai --model gemma-4-e4b --tag gemma_v7b
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "cache", "v9_base_compare")


def _post(url: str, payload: dict, timeout: int = 180) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def call_ollama(base: str, model: str, system: str, user: str,
                tools: list | None, think: bool) -> tuple[str, list[str]]:
    msg = {"role": "user", "content": user}
    payload = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + [msg],
        "stream": False,
        "options": {"temperature": 0.3, "top_p": 0.9, "top_k": 20},
    }
    if tools:
        payload["tools"] = tools
    # Qwen3.5: 关掉思考模式（默认开），否则答案里带 <think>
    payload["think"] = bool(think)
    out = _post(base.rstrip("/") + "/api/chat", payload)
    m = out.get("message") or {}
    content = str(m.get("content") or "")
    calls = [tc.get("function", {}).get("name", "")
             for tc in (m.get("tool_calls") or [])]
    if not calls:
        for tc in (out.get("tool_calls") or []):
            calls.append(tc.get("function", {}).get("name", ""))
    return content, [c for c in calls if c]


def call_openai(base: str, model: str, system: str, user: str,
                tools: list | None, api_key: str) -> tuple[str, list[str]]:
    payload = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": user}],
        "temperature": 0.3, "top_p": 0.9, "stream": False,
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + (api_key or "sk-local")})
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.loads(r.read().decode("utf-8"))
    ch = (out.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = str(msg.get("content") or "")
    calls = [tc.get("function", {}).get("name", "")
             for tc in (msg.get("tool_calls") or [])]
    return content, [c for c in calls if c]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["ollama", "openai"], required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--think", action="store_true", default=False,
                    help="Ollama: 开启思考模式（默认关，避免 <think> 污染判分）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    from tools.persona_bank import PERSONA_BANK, verify
    from backend.target_prompts import render_system_prompt
    try:
        from backend.target_scheduler_tools import openai_tools_view
        tools = openai_tools_view()
    except Exception:
        tools = []

    system = render_system_prompt()
    items = PERSONA_BANK[: args.limit] if args.limit else PERSONA_BANK

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    t0 = time.time()
    for i, e in enumerate(items, 1):
        q = e["q"]
        try:
            if args.backend == "ollama":
                ans, calls = call_ollama(args.base_url, args.model, system, q,
                                         tools, args.think)
            else:
                ans, calls = call_openai(args.base_url, args.model, system, q,
                                         tools, "sk-local")
            ok, why = verify(e, ans, calls)
        except Exception as exc:  # noqa: BLE001
            ans, calls, ok, why = "", [], False, "调用失败:%s" % type(exc).__name__
        rows.append({"id": e["id"], "cat": e["cat"], "q": q, "ok": ok, "why": why,
                     "answer": ans, "tools": calls,
                     "len": len(ans), "ms": None})
        mark = "✅" if ok else "❌"
        print("  [%02d/%d] %s %s %-4s %s" % (i, len(items), mark, e["id"],
                                             e["cat"], (why or "")[:60]))

    total = len(rows)
    passed = sum(1 for r in rows if r["ok"])
    by_cat: dict[str, dict] = {}
    for r in rows:
        d = by_cat.setdefault(r["cat"], {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += 1 if r["ok"] else 0

    report = {
        "tag": args.tag, "backend": args.backend, "model": args.model,
        "base_url": args.base_url, "think": args.think,
        "system_prompt_chars": len(system), "tools": len(tools),
        "elapsed_s": round(time.time() - t0, 1),
        "total": total, "passed": passed, "rate": round(passed / total, 4) if total else 0,
        "by_cat": by_cat, "rows": rows,
    }
    p = os.path.join(OUT_DIR, "%s.json" % args.tag)
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print()
    print("=" * 66)
    print("模型 %s ｜ %s ｜ 用时 %.1fs" % (args.model, args.backend, report["elapsed_s"]))
    print("总通过 %d/%d = %.1f%%" % (passed, total, 100 * passed / total if total else 0))
    for cat, d in by_cat.items():
        print("   %-6s %2d/%2d  %.0f%%" % (cat, d["ok"], d["n"], 100 * d["ok"] / d["n"]))
    print("结果已存：%s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
