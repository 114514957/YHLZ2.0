#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比式 steering：算「短答干脆」−「长篇反问」的激活差方向，推它调风格。

为什么不用单神经元：实测随机 20 个神经元推 +1.0，95% 都能改输出 →
说明单神经元不特异，是"加扰动"。但扰动的**方向**有规律（都变短、去反问）。

所以改用经典的 contrastive steering：
    direction = normalize( mean(h | 我们想要的样子) − mean(h | 不想要的样子) )
在目标层的 mlp_out（或残差流）上推 strength * direction，strength 就是「调参」的旋钮。

对照样本用**模型自己生成的**：
  · 正面：把 prompt 加上"短、别反问"的指令后生成，取激活
  · 负面：baseline（长、反问收尾）的激活
这样方向就是"从它现在的毛病往我们要的样子偏"。

用法：
    python tools/v9_steer_contrast.py --layer 11 --strengths 0,1,2,3,5
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")

# 一组探针问题（都是我们会问的），用来算方向 + 验证
PROBES = ["在吗", "我回来了", "今天有点累", "你叫什么", "这数据直接上？",
          "帮我看看这个文件夹"]


def build_text(tok, q: str, extra: str = ""):
    sys_msg = SYSTEM + (("\n\n" + extra) if extra else "")
    msgs = [{"role": "system", "content": sys_msg},
            {"role": "user", "content": q}]
    try:
        kw = {"enable_thinking": False}
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True, **kw)
        except TypeError:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=True)
    except Exception:  # noqa: BLE001
        return tok.apply_chat_template(msgs, tokenize=False,
                                       add_generation_prompt=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", type=int, default=11)
    ap.add_argument("--strengths", default="0,1,2,3,5,8")
    ap.add_argument("--q", default="在吗")
    ap.add_argument("--save", default="cache/neuron/dir_L11.pt")
    a = ap.parse_args()

    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    print("加载 4bit 模型 …")
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="cuda:0",
        trust_remote_code=True)
    model.eval()

    L = a.layer
    mlp = model.model.layers[L].mlp
    cap = {"h": None}

    def cap_hook(module, args, output):
        if cap["h"] is None:
            cap["h"] = output.detach().float().mean(dim=1)[0]   # 序列均值 → (hidden,)
        return output

    h = mlp.register_forward_hook(cap_hook)

    def hidden_for(text: str):
        ids = tok(text, return_tensors="pt").to("cuda:0")
        cap["h"] = None
        with torch.no_grad():
            model(**ids)
        return cap["h"]

    # 负面：现在这个样子（不加额外指令）
    # 正面：明确要求短、别反问
    POS_EXTRA = ("【本轮的说话要求】回答控制在 30 字以内，不要用反问句结尾，"
                 "不要解释，直接说重点。")
    negs, poss = [], []
    for q in PROBES:
        negs.append(hidden_for(build_text(tok, q)))
        poss.append(hidden_for(build_text(tok, q, POS_EXTRA)))
    neg = torch.stack(negs).mean(0)
    pos = torch.stack(poss).mean(0)
    d = (pos - neg)
    d = d / d.norm().clamp_min(1e-6)
    print("\n方向已算出：|pos−neg| = %.3f｜单位化后 norm=%.3f"
          % ((pos - neg).norm().item(), d.norm().item()))

    h.remove()

    # 用这个方向做 steering
    state = {"d": None}

    def steer_hook(module, args, output):
        if state["d"] is None:
            return output
        return output + state["d"]

    h2 = mlp.register_forward_hook(steer_hook)

    ids = tok(build_text(tok, a.q), return_tensors="pt").to("cuda:0")

    def gen():
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=90, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()

    print("\n" + "=" * 74)
    print("调参：问「%s」，只改 strength" % a.q)
    print("=" * 74)
    rows = []
    for s in [float(x) for x in a.strengths.split(",")]:
        state["d"] = None if s == 0 else (d * s).to(torch.bfloat16)
        t = gen()
        rows.append({"strength": s, "out": t, "len": len(t)})
        print("  s=%-4.1f (%3d 字) %s" % (s, len(t), t[:120].replace("\n", " ")))

    h2.remove()
    print("\n" + "=" * 74)
    base = rows[0]["len"] if rows else 0
    for r in rows[1:]:
        dlt = 100.0 * (r["len"] - base) / max(1, base)
        print("  s=%-4.1f：字数 %+5.1f%%%s"
              % (r["strength"], dlt, "  ← 明显变短" if dlt < -25 else ""))

    os.makedirs(os.path.join(ROOT, "cache", "neuron"), exist_ok=True)
    torch.save({"layer": L, "direction": d.cpu()},
               os.path.join(ROOT, a.save))
    print("\n方向已存：%s（下次可直接加载，不用重算）" % a.save)
    with io.open(os.path.join(ROOT, "cache", "neuron",
                              "contrast_L%d.json" % L), "w", encoding="utf-8") as f:
        json.dump({"layer": L, "q": a.q, "rows": rows}, f, ensure_ascii=False,
                  indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
