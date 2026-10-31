#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 Qwen3.5-4B 能否在当前 transformers 下加载（4bit），并出一句话。

为什么单独测：Qwen3.5-4B 是**多模态混合注意力**架构
（`Qwen3_5ForConditionalGeneration`，32 层、24 层 linear_attention + 8 层 full、
vocab 248320、带 24 层 ViT），和我们的 Qwen3-4B（纯文本全 attention、36 层）完全不同。
config 里写 `transformers_version: 4.57.0.dev0`，本地是 5.20.2，要验证兼容性。
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

D = os.path.join(ROOT, "models", "qwen35-4b-hf")


def main() -> int:
    import torch
    import transformers
    print("transformers %s｜torch %s" % (transformers.__version__, torch.__version__))

    # 1. 文件完整性
    print("\n① 文件")
    import json
    idx = json.load(open(os.path.join(D, "model.safetensors.index.json"),
                        encoding="utf-8"))
    wm = idx["weight_map"]
    files = sorted(set(wm.values()))
    print("   索引：%d 个张量 → %d 个分片" % (len(wm), len(files)))
    for f in files:
        p = os.path.join(D, f)
        print("   %-46s %8.2f GB" % (f, os.path.getsize(p) / 1073741824)
              if os.path.exists(p) else "   %s 缺失" % f)

    # 2. 结构校验
    print("\n② safetensors 结构")
    from safetensors import safe_open
    for f in files:
        p = os.path.join(D, f)
        try:
            with safe_open(p, framework="pt") as fh:
                keys = list(fh.keys())
            print("   ✅ %-44s %d 个张量" % (os.path.basename(f), len(keys)))
        except Exception as e:  # noqa: BLE001
            print("   ❌ %-44s %s" % (os.path.basename(f), str(e)[:80]))

    # 3. 试加载 tokenizer
    print("\n③ tokenizer")
    from transformers import AutoTokenizer
    try:
        tok = AutoTokenizer.from_pretrained(D, trust_remote_code=True)
        print("   ✅ vocab %d" % len(tok))
    except Exception as e:  # noqa: BLE001
        print("   ❌ %s" % str(e)[:200])
        return 1

    # 4. 试加载模型（4bit）
    print("\n④ 模型加载（4bit）")
    from transformers import (AutoModelForCausalLM, BitsAndBytesConfig)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
    t0 = time.time()
    model = None
    for cls_name in ("AutoModelForCausalLM", "AutoModelForImageTextToText",
                     "AutoModel"):
        try:
            if cls_name == "AutoModelForCausalLM":
                cls = AutoModelForCausalLM
            elif cls_name == "AutoModelForImageTextToText":
                from transformers import AutoModelForImageTextToText as cls  # noqa: N813
            else:
                from transformers import AutoModel as cls  # noqa: N813
            model = cls.from_pretrained(D, quantization_config=bnb,
                                        device_map="cuda:0",
                                        trust_remote_code=True)
            print("   ✅ 用 %s 加载成功（%.1f 秒｜显存 %.2f GB）"
                  % (cls_name, time.time() - t0,
                     torch.cuda.memory_allocated() / 1e9))
            break
        except Exception as e:  # noqa: BLE001
            print("   ✗ %s 失败：%s" % (cls_name, str(e)[:120]))
    if model is None:
        print("\n❌ 三种 Auto 类都加载不了，当前 transformers 版本不支持 qwen3_5")
        return 2

    # 5. 出一句话
    print("\n⑤ 出话测试")
    model.eval()
    msgs = [{"role": "user", "content": "用一句话介绍你自己"}]
    try:
        kw = {"enable_thinking": False}
        try:
            txt = tok.apply_chat_template(msgs, tokenize=False,
                                          add_generation_prompt=True, **kw)
        except TypeError:
            txt = tok.apply_chat_template(msgs, tokenize=False,
                                          add_generation_prompt=True)
    except Exception:  # noqa: BLE001
        txt = tok.apply_chat_template(msgs, tokenize=False,
                                      add_generation_prompt=True)
    ids = tok(txt, return_tensors="pt").to("cuda:0")
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=80, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    ans = tok.decode(out[0][ids["input_ids"].shape[1]:],
                     skip_special_tokens=True).strip()
    print("   问：用一句话介绍你自己")
    print("   答：%s" % ans[:200].replace("\n", " "))

    # 6. 结构摘要（供 steering 参考）
    print("\n⑥ 结构（steering 要用）")
    try:
        tm = getattr(model, "model", None) or model
        layers = getattr(tm, "layers", None)
        print("   层数：%s" % (len(layers) if layers is not None else "?"))
        if layers is not None:
            for i in (0, 3, 11, 12, 22, 31):
                if i < len(layers):
                    mlp = getattr(layers[i], "mlp", None)
                    dp = getattr(mlp, "down_proj", None) if mlp else None
                    print("   L%-2d %s｜down_proj=%s"
                          % (i, type(layers[i]).__name__,
                             tuple(dp.weight.shape) if dp is not None
                             and hasattr(dp, "weight") else "?"))
    except Exception as e:  # noqa: BLE001
        print("   结构读取失败：%s" % str(e)[:100])
    return 0


if __name__ == "__main__":
    sys.exit(main())
