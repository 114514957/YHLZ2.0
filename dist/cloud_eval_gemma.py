#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""云端 56 题评测（适配 gemma-4-e4b / Qwen3 任意基座）。

与 v9 的 cloud_eval 差别：
  · 基座从环境变量 YH_MODEL 读，缺省按候选找；
  · 4bit 加载 + 统一 prompt（training==deploy 的那份）；
  · gemma4 是多模态结构，AutoModelForCausalLM 能直接加载文本塔（已验证）。

用法：
    YH_MODEL=/root/autodl-tmp/models/gemma-4-e4b-it \
    YH_TAG=gemma_v7b python cloud_eval_gemma.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, "/root/yh")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_CANDS = [
    os.environ.get("YH_MODEL", ""),
    "/root/autodl-tmp/models/gemma-4-e4b-it",
    "/root/autodl-tmp/models/full/qwen3-4b-yuanheng-v9t4",
]
MODEL = next((p for p in MODEL_CANDS if p and os.path.isdir(p)), "")
TAG = os.environ.get("YH_TAG", "run")
ONLY_TOOLS = os.environ.get("YH_ONLY_TOOLS", "0") == "1"
# 可选：挂一个 LoRA adapter 再评测（训练产物）；不设就评基座
ADAPTER = os.environ.get("YH_ADAPTER", "").strip()

SNAP_CANDS = [
    "/root/yh/data/tool_registry/snapshot_latest.json",
    "data/tool_registry/snapshot_latest.json",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "data", "tool_registry", "snapshot_latest.json"),
]
SNAP = next((p for p in SNAP_CANDS if os.path.exists(p)), SNAP_CANDS[0])

from unified_prompt import UNIFIED_SYSTEM as SYSTEM  # noqa: E402
import persona_bank as PB  # noqa: E402


def log(*a):
    print(*a, flush=True)


def load_tools():
    d = json.load(io.open(SNAP, encoding="utf-8"))
    inner = d.get("tools") or d
    return [t if "function" in t else {"type": "function", "function": t}
            for t in inner]


def main() -> int:
    if not MODEL:
        log("✗ 找不到模型，候选：%s" % MODEL_CANDS)
        return 2

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    tools = load_tools()
    log("模型 %s" % MODEL)
    log("工具 %d｜prompt %d 字｜tag %s" % (len(tools), len(SYSTEM), TAG))

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()
    if ADAPTER:
        if not os.path.isdir(ADAPTER):
            log("✗ 指定了 YH_ADAPTER 但目录不存在：%s" % ADAPTER)
            return 2
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, ADAPTER)
        model.eval()
        log("已挂 adapter: %s" % ADAPTER)
    log("加载 %.1f 秒｜显存 %.2f GB"
        % (time.time() - t0, torch.cuda.memory_allocated() / 1e9))

    qs = [e for e in PB.PERSONA_BANK
          if (not ONLY_TOOLS) or e["cat"] == "工具遵循"]
    log("跑 %d 题" % len(qs))

    res = []
    t_all = time.time()
    for e in qs:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": e["q"]}]
        use_tools = tools if e["cat"] == "工具遵循" else None
        text = None
        kws = ([{"enable_thinking": False, "tools": use_tools},
                {"enable_thinking": False}, {}]
               if use_tools else [{"enable_thinking": False}, {}])
        for kw in kws:
            try:
                text = tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True, **kw)
                break
            except Exception:  # noqa: BLE001
                continue
        if text is None:
            text = tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)
        ids = tok(text, return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=300, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        raw = tok.decode(out[0][ids["input_ids"].shape[1]:],
                         skip_special_tokens=True).strip()
        called = []
        # ① Qwen3 格式：<tool_call>{"name": ..., "arguments": ...}</tool_call>
        for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", raw, 16):
            try:
                j = json.loads(m.group(1))
                if j.get("name"):
                    called.append(j["name"])
            except Exception:  # noqa: BLE001
                pass
        # ② gemma 格式：call:name{arg:val, ...}（常常不带外层 <|tool_call>）
        #    2026-11-01 修：原脚本只认①，gemma 输出的 call:xxx{...} 一个都匹配不到，
        #    导致 v1 的工具分被压成 2/16（真实 15/16）、v3 压成 2/16（真实 11/16）。
        for m in re.finditer(
                r"(?:<\|tool_call>\s*)?call:\s*([a-z_][a-z0-9_]*)\s*\{", raw):
            if m.group(1) not in called:
                called.append(m.group(1))
        if not called:
            called = [m.group(1) for m in
                      re.finditer(r'"name"\s*:\s*"([a-z_]+)"', raw)]
        try:
            ok, why = PB.verify(e, raw, tuple(called))
        except Exception as ex:  # noqa: BLE001
            ok, why = False, str(ex)[:40]
        res.append({"id": e["id"], "cat": e["cat"], "q": e["q"],
                    "answer": raw[:600], "called": called,
                    "ok": bool(ok), "why": why})
        log("  %-6s %-6s %s %-18s %s"
            % (e["id"], e["cat"], "OK " if ok else "FAIL",
               ("调:" + ",".join(called)) if called else "", (why or "")[:34]))

    el = time.time() - t_all
    cat, okc = Counter(), Counter()
    for r in res:
        cat[r["cat"]] += 1
        if r["ok"]:
            okc[r["cat"]] += 1
    tot = sum(okc.values())
    log("\n" + "=" * 60)
    log("%s：%d/%d（%.1f%%）｜%.1f 分钟"
        % (TAG, tot, len(res), 100.0 * tot / len(res), el / 60))
    for k in cat:
        log("  %-8s %d/%d（%.0f%%）" % (k, okc[k], cat[k], 100.0 * okc[k] / cat[k]))

    out_p = "/root/autodl-tmp/eval56_%s.json" % TAG
    with io.open(out_p, "w", encoding="utf-8") as f:
        json.dump({"tag": TAG, "model": MODEL, "total": len(res), "ok": tot,
                   "by_cat": {k: [okc[k], cat[k]] for k in cat},
                   "results": res}, f, ensure_ascii=False, indent=2)
    log("明细 %s" % out_p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
