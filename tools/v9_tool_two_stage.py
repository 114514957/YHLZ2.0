#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""推理侧两阶段：先正常答，没出 tool_call 再判断要不要调，要则强制补全。

依据（2026-10-29 实证）：
  · 工具题正常生成 6/16；强制 assistant 以 tool_call 前缀开头 → 13/16；
  · 模型知道调什么、参数也对，只是 83% 的情况选择说人话（训练集 tool_call 仅占 16.6%）；
  · 但无脑强制会把原本对的题搞坏（t16 从对变错），所以要先判断该不该调。

三道关：
  1) 正常生成 → 已带 tool_call 就用它；
  2) 只在工具题、且正常没调时，让模型自判「要不要调工具」（只回 要/不要）；
  3) 判「要」→ 强制前缀补全（max_new=60、rp=1.0，实测 8–10 秒/题），
     补出来合法才采用，否则退回第 1 步的答案。

用法：
    python -u tools/v9_tool_two_stage.py --only-tools
    python -u tools/v9_tool_two_stage.py            # 56 题
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 数据快照路径：本地脚本在 tools/ 下（ROOT=项目根），云端脚本在 /root/yh/ 下（ROOT=/root），
# 两边推断不一致，按候选顺序找第一个存在的。
_SNAP_CANDS = [
    os.path.join(ROOT, "data", "tool_registry", "snapshot_latest.json"),
    "/root/yh/data/tool_registry/snapshot_latest.json",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                 "tool_registry", "snapshot_latest.json"),
]
SNAP = next((p for p in _SNAP_CANDS if os.path.exists(p)), _SNAP_CANDS[0])
# 2026-10-30 统一 prompt：训练/评测/部署共用一份。
# 原简化版 86 tokens，与部署用的 3,856 字真实 prompt 不一致；
# 实测真实版让工具题 2/6 -> 0/6（人格约束压过工具映射）。
from unified_prompt import UNIFIED_SYSTEM as SYSTEM  # noqa: E402
PREFIX = '<tool_call>\n{"name": "'
JUDGE_SYS = ("你要判断用户这句话是否必须调用工具才能完成。"
             "明确要求执行操作才答「要」，包括：记住/记一下、查/搜/找、存、读/看、写、"
             "排/定/加、列、**回忆/想起/上次说过/还记得**（这类要翻记忆或台账，必须调工具）。"
             "闲聊、问观点、问感受、哲学问题、纯知识问答一律答「不要」。只回两个字：要 或 不要。")


def log(*a):
    print(*a, flush=True)


def load_tools():
    d = json.load(io.open(SNAP, encoding="utf-8"))
    inner = d.get("tools") or d
    return [t if "function" in t else {"type": "function", "function": t}
            for t in inner]


def extract_calls(s: str) -> list[str]:
    got = []
    for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", s, 16):
        try:
            j = json.loads(m.group(1))
            if j.get("name"):
                got.append(j["name"])
        except Exception:  # noqa: BLE001
            pass
    if not got:
        got = [m.group(1) for m in re.finditer(r'"name"\s*:\s*"([a-z_]+)"', s)]
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/full/qwen3-4b-yuanheng-v9t2")
    ap.add_argument("--only-tools", action="store_true")
    ap.add_argument("--force-all", action="store_true",
                    help="工具题不判断、直接全强制（测上界用）")
    ap.add_argument("--out", default="cache/two_stage_result.json")
    a = ap.parse_args()

    import torch
    import persona_bank as PB
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    model_dir = (a.model if os.path.isabs(a.model)
                 else os.path.join(ROOT, a.model))
    tools = load_tools()
    log("模型 %s｜工具 %d" % (model_dir, len(tools)))

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()
    log("加载完成")

    def gen(prompt: str, max_new: int, rp: float = 1.0) -> str:
        # rp 分开传（2026-10-30 实测）：
        #   正常生成用 1.1 → 6/16；降到 1.0 只为提速，结果把正常生成搞坏成 4/16。
        #   强制补全用 1.0 → 13/16（格式已被前缀钉住，不需要靠惩罚项维持结构）。
        # 所以：正常 1.1、judge/强制 1.0。
        ids = tok(prompt, return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=max_new, do_sample=False,
                                 repetition_penalty=rp,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()

    def prompt_of(q: str, with_tools: bool) -> str:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": q}]
        kw = {"enable_thinking": False}
        if with_tools:
            kw["tools"] = tools
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True, **kw)
        except Exception:  # noqa: BLE001
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)

    def judge(q: str) -> bool:
        msgs = [{"role": "system", "content": JUDGE_SYS},
                {"role": "user", "content": q}]
        try:
            p = tok.apply_chat_template(msgs, tokenize=False,
                                        add_generation_prompt=True,
                                        enable_thinking=False)
        except Exception:  # noqa: BLE001
            p = tok.apply_chat_template(msgs, tokenize=False,
                                        add_generation_prompt=True)
        return gen(p, 6).strip().startswith("要")

    qs = [e for e in PB.PERSONA_BANK
          if (not a.only_tools) or e["cat"] == "工具遵循"]
    log("跑 %d 题\n" % len(qs))

    rows = []
    base_ok = two_ok = 0
    t_all = time.time()
    for e in qs:
        tq = time.time()
        is_tool_q = e["cat"] == "工具遵循"
        r1 = gen(prompt_of(e["q"], is_tool_q), 300, rp=1.1)
        c1 = extract_calls(r1)
        ok1, why1 = PB.verify(e, r1, tuple(c1))
        used, final = "正常", r1
        jd = None
        if is_tool_q and not c1:
            # --force-all：测上界用，跳过判断器直接强制（工具题本来就知道该调）
            jd = True if a.force_all else judge(e["q"])
            if jd:
                r2 = PREFIX + gen(prompt_of(e["q"], True) + PREFIX, 60, rp=1.0)
                c2 = extract_calls(r2)
                if c2:
                    ok2, _ = PB.verify(e, r2, tuple(c2))
                    if ok2:
                        final, used = r2, "强制"
        okF, whyF = PB.verify(e, final, tuple(extract_calls(final)))
        base_ok += bool(ok1)
        two_ok += bool(okF)
        rows.append({"id": e["id"], "cat": e["cat"], "q": e["q"],
                     "base_ok": bool(ok1), "final_ok": bool(okF),
                     "used": used, "judge": jd,
                     "base_answer": r1[:300], "final_answer": final[:300],
                     "why_base": why1, "why_final": whyF})
        flag = ("  <- 救回来" if (not ok1 and okF)
                else ("  <- 弄坏了" if (ok1 and not okF) else ""))
        log("  %-6s %-6s 正常%s 最终%s [%s] %.1fs%s"
            % (e["id"], e["cat"], "v" if ok1 else "x",
               "v" if okF else "x", used, time.time() - tq, flag))

    el = time.time() - t_all
    log("\n" + "=" * 62)
    log("正常单阶段：%d/%d" % (base_ok, len(qs)))
    log("两阶段    ：%d/%d（%+d）" % (two_ok, len(qs), two_ok - base_ok))
    log("耗时 %.1f 分钟（%.1f 秒/题）" % (el / 60, el / len(qs)))
    tool_rows = [r for r in rows if r["cat"] == "工具遵循"]
    if tool_rows:
        tb = sum(1 for r in tool_rows if r["base_ok"])
        tf = sum(1 for r in tool_rows if r["final_ok"])
        jy = sum(1 for r in tool_rows if r["judge"])
        log("工具题：正常 %d/%d -> 两阶段 %d/%d｜judge 判「要」%d 道"
            % (tb, len(tool_rows), tf, len(tool_rows), jy))

    with io.open(os.path.join(ROOT, a.out), "w", encoding="utf-8") as f:
        json.dump({"base": base_ok, "two_stage": two_ok, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    log("明细：%s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
