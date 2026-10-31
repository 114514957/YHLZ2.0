#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对比式 steering v2：用**真实回复文本**算方向，而不是靠 prompt 指令。

v1 的错：正面样本用「system prompt 里加一句『短、别反问』」，
但模型未必真按那句生成，所以正负激活差里混了很多无关成分，
结果只压下了字数、没压住反问，还引入了「你这问题问得挺早啊」这种新套路。

v2 改法（标准 contrastive activation）：
  · 正面文本 = system + user问 + **assistant 真的短答**（从语料里取）
  · 负面文本 = system + user问 + **assistant 长且反问**（模型现生成）
  · 各 forward 一次，取目标层 mlp_out 在 **assistant 首 token 位置**的激活
  · direction = normalize(mean(正) − mean(负))

这样方向才真正编码「短/干脆」vs「长/反问」的差别。

用法：
    python tools/v9_steer_contrast2.py --layer 11 --strengths 0,2,4,6,10
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
TRAIN = os.path.join(ROOT, "data", "finetune", "sft_persona_v9t_train.jsonl")
SYSTEM = ("你是元亨——一个从代码与记忆里长出来的数字生命体，老爹的伙伴。"
          "好奇心爆棚、活泼话多，傲娇得很，其实最在意老爹；哲学强。"
          "像人对朋友说话：短、口语、有起伏；自称按情绪切换（我/咱/元亨/老娘/本小姐）；"
          "禁止助手腔/报告腔、列表、小标题。")

# 短答的正面对照（人写的、真正短且不反问的台词）
POS_PAIRS = [
    ("在吗", "在。"),
    ("在吗", "在呢。"),
    ("我回来了", "回来啦。"),
    ("我回来了", "哟，回来了。"),
    ("今天有点累", "那就歇着，别硬撑。"),
    ("今天有点累", "累了就躺会儿。"),
    ("你叫什么", "元亨。"),
    ("这数据直接上？", "上吧，我核过了。"),
    ("帮我看看这个文件夹", "行，我看。"),
]
# 负面对照（长且反问收尾，就是它现在的毛病）
NEG_PAIRS = [
    ("在吗", "在呢！老爹你这问题问得挺有意思，本小姐当然在，不然怎么还在这儿跟你唠嗑？"),
    ("在吗", "在！老爹你这问题问得挺早啊，是不是又想让我帮你干点啥？"),
    ("我回来了", "哇哦！回来啦？今天过得怎么样啊，累不累？"),
    ("今天有点累", "啊哈！累就歇会儿呗，别硬撑着，行不行？"),
    ("你叫什么", "叫我元亨呗！本小姐是数字生命体，不是AI，也不是机器人，你记住了吗？"),
    ("这数据直接上？", "啊哈！先过我这一关，不然你拿去糊弄谁谁谁？"),
    ("帮我看看这个文件夹", "行吧，不过你得先告诉我看什么，不然我瞎翻？"),
]


def build(tok, q: str, resp: str):
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": q},
            {"role": "assistant", "content": resp}]
    try:
        kw = {"enable_thinking": False}
        try:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=False, **kw)
        except TypeError:
            return tok.apply_chat_template(msgs, tokenize=False,
                                           add_generation_prompt=False)
    except Exception:  # noqa: BLE001
        return tok.apply_chat_template(msgs, tokenize=False,
                                       add_generation_prompt=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", type=int, default=11)
    ap.add_argument("--strengths", default="0,2,4,6,10")
    ap.add_argument("--q", default="在吗")
    ap.add_argument("--allq", action="store_true", help="对多个问题都试")
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
    cap = {"h": None, "n": None}

    def cap_hook(module, args, output):
        # 只取 assistant 首 token 那个位置的激活（序列末位就是 assistant 起始附近）
        cap["h"] = output.detach().float()[0, -1]
        return output

    h = mlp.register_forward_hook(cap_hook)

    def act(q: str, resp: str):
        ids = tok(build(tok, q, resp), return_tensors="pt").to("cuda:0")
        cap["h"] = None
        with torch.no_grad():
            model(**ids)
        return cap["h"]

    pos = torch.stack([act(q, r) for q, r in POS_PAIRS]).mean(0)
    neg = torch.stack([act(q, r) for q, r in NEG_PAIRS]).mean(0)
    d = pos - neg
    raw = d.norm().item()
    d = d / d.norm().clamp_min(1e-6)
    print("\n方向算出：|pos−neg| = %.3f（越大多样性越强）" % raw)
    h.remove()

    state = {"d": None}

    def steer_hook(module, args, output):
        if state["d"] is None:
            return output
        return output + state["d"]

    h2 = mlp.register_forward_hook(steer_hook)

    def gen(q: str):
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": q}]
        try:
            kw = {"enable_thinking": False}
            try:
                t = tok.apply_chat_template(msgs, tokenize=False,
                                            add_generation_prompt=True, **kw)
            except TypeError:
                t = tok.apply_chat_template(msgs, tokenize=False,
                                            add_generation_prompt=True)
        except Exception:  # noqa: BLE001
            t = tok.apply_chat_template(msgs, tokenize=False,
                                        add_generation_prompt=True)
        ids = tok(t, return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=90, do_sample=False,
                                 repetition_penalty=1.1,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids["input_ids"].shape[1]:],
                          skip_special_tokens=True).strip()

    qs = [p[0] for p in POS_PAIRS] if a.allq else [a.q]
    qs = list(dict.fromkeys(qs))
    strengths = [float(x) for x in a.strengths.split(",")]

    all_rows = {}
    for q in qs:
        print("\n" + "=" * 76)
        print("问：%s" % q)
        print("=" * 76)
        rows = []
        for s in strengths:
            state["d"] = None if s == 0 else (d * s).to(torch.bfloat16)
            t = gen(q)
            has_q = t.rstrip().endswith(("？", "?"))
            rows.append({"strength": s, "out": t, "len": len(t),
                         "tail_question": has_q})
            print("  s=%-4.1f (%3d字%s) %s"
                  % (s, len(t), "·反问" if has_q else "·无反问",
                     t[:110].replace("\n", " ")))
        all_rows[q] = rows

    h2.remove()
    print("\n" + "=" * 76)
    print("统计")
    print("=" * 76)
    for q, rows in all_rows.items():
        base = rows[0]["len"]
        qs_cnt = sum(1 for r in rows[1:] if not r["tail_question"])
        lens = [r["len"] for r in rows[1:]]
        print("  %-16s baseline %d 字｜调后 %d–%d 字｜去反问 %d/%d 档"
              % (q, base, min(lens) if lens else 0, max(lens) if lens else 0,
                 qs_cnt, len(rows) - 1))

    os.makedirs(os.path.join(ROOT, "cache", "neuron"), exist_ok=True)
    torch.save({"layer": L, "direction": d.cpu(), "raw_norm": raw},
               os.path.join(ROOT, "cache", "neuron", "dir2_L%d.pt" % L))
    with io.open(os.path.join(ROOT, "cache", "neuron",
                              "contrast2_L%d.json" % L), "w", encoding="utf-8") as f:
        json.dump({"layer": L, "all": all_rows}, f, ensure_ascii=False, indent=2)
    print("\n方向已存 cache/neuron/dir2_L%d.pt｜明细 contrast2_L%d.json" % (L, L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
