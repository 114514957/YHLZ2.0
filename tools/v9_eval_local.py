#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地 56 题评测（4bit，带工具定义）。

用途：模型下载到本地后，验证「本地 4bit 版」与「云端 bf16 版」的差距。
注意：4bit 量化必然掉分，重点看**相对表现**和**分项结构**是否一致。

用法：
    python tools/v9_eval_local.py
    python tools/v9_eval_local.py --limit 16      # 只跑工具题
    python tools/v9_eval_local.py --cat 工具遵循
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
SNAP = os.path.join(ROOT, "data", "tool_registry", "snapshot_latest.json")
# 2026-10-30 统一 prompt：训练/评测/部署共用一份。
# 原简化版 86 tokens，与部署用的 3,856 字真实 prompt 不一致；
# 实测真实版让工具题 2/6 -> 0/6（人格约束压过工具映射）。
from unified_prompt import UNIFIED_SYSTEM as SYSTEM  # noqa: E402


def load_tools():
    d = json.load(io.open(SNAP, encoding="utf-8"))
    inner = d.get("tools") or d
    out = []
    for t in inner:
        out.append(t if "function" in t else {"type": "function", "function": t})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="", help="只跑某一类")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="cache/eval56_local_4bit.json")
    ap.add_argument("--model", default="",
                    help="模型目录，默认 models/full/qwen3-4b-yuanheng-v9t")
    a = ap.parse_args()

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)
    import persona_bank as PB

    global MODEL
    if a.model:
        MODEL = os.path.abspath(a.model) if os.path.isabs(a.model) else os.path.join(ROOT, a.model)
    print("模型: %s" % MODEL)
    tools = load_tools()
    print("工具定义 %d 个" % len(tools))
    print("加载 4bit 模型 …")
    t0 = time.time()
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()
    print("加载完成 %.1f 秒｜显存 %.2f GB\n"
          % (time.time() - t0, torch.cuda.memory_allocated() / 1e9))

    qs = list(PB.PERSONA_BANK)
    if a.cat:
        qs = [e for e in qs if e["cat"] == a.cat]
    if a.limit:
        qs = qs[:a.limit]
    print("跑 %d 题\n" % len(qs))

    results = []
    t_all = time.time()
    for i, e in enumerate(qs, 1):
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": e["q"]}]
        use_tools = tools if e["cat"] == "工具遵循" else None
        text = None
        for kw in ([{"enable_thinking": False, "tools": use_tools},
                    {"enable_thinking": False}, {"tools": use_tools}, {}]
                   if use_tools else [{"enable_thinking": False}, {}]):
            if use_tools and "tools" not in kw:
                continue
            try:
                text = tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=True, **kw)
                break
            except TypeError:
                continue
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
        for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", raw, 16):
            try:
                j = json.loads(m.group(1))
                if j.get("name"):
                    called.append(j["name"])
            except Exception:  # noqa: BLE001
                pass
        if not called:
            called = [m.group(1) for m in re.finditer(r'"name"\s*:\s*"([a-z_]+)"', raw)]
        try:
            ok, why = PB.verify(e, raw, tuple(called))
        except Exception as ex:  # noqa: BLE001
            ok, why = False, "verify异常:%s" % str(ex)[:40]
        results.append({"id": e["id"], "cat": e["cat"], "q": e["q"],
                        "answer": raw[:600], "called": called,
                        "ok": bool(ok), "why": why})
        print("  %-6s %-6s %s %-14s %s"
              % (e["id"], e["cat"], "OK " if ok else "FAIL",
                 ("调:" + ",".join(called)) if called else "",
                 (why or "")[:34]), flush=True)

    el = time.time() - t_all
    cat, okc = Counter(), Counter()
    for r in results:
        cat[r["cat"]] += 1
        if r["ok"]:
            okc[r["cat"]] += 1
    tot = sum(okc.values())
    print("\n" + "=" * 62)
    print("本地 4bit：%d/%d（%.1f%%）｜%.1f 分钟｜%.1f 秒/题"
          % (tot, len(results), 100.0 * tot / len(results), el / 60,
             el / max(1, len(results))))
    for k in cat:
        print("  %-8s %d/%d（%.0f%%）" % (k, okc[k], cat[k], 100.0 * okc[k] / cat[k]))
    print("\n云端 bf16 参照：30/56（人格 12/20、关系 8/12、工具 7/16、风格 3/8）")

    os.makedirs(os.path.dirname(os.path.join(ROOT, a.out)), exist_ok=True)
    with io.open(os.path.join(ROOT, a.out), "w", encoding="utf-8") as f:
        json.dump({"total": len(results), "ok": tot,
                   "by_cat": {k: [okc[k], cat[k]] for k in cat},
                   "results": results}, f, ensure_ascii=False, indent=2)
    print("明细：%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
