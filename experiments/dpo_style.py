# -*- coding: utf-8 -*-
"""风格 DPO：在 v9t10 的 LoRA 上继续练，压低「哇开头 / 反问收尾 / 客服腔」。

参考模型 = 同一个底座、不挂 adapter（TRL 的 ref_model=None + PEFT 自动处理），
所以显存只需要「底座 16G + adapter」，A800 够。

用法：
  python dpo_style.py --base /root/autodl-tmp/models/gemma-4-e4b-it \
      --adapter /root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10 \
      --data /root/yh/dpo_style_v1 --out /root/autodl-tmp/models/lora/yuanheng-v9t10-dpo
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import torch
from datasets import load_dataset
from peft import LoraConfig, PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DPOConfig, DPOTrainer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", default="", help="从哪个 LoRA 继续（空=从底座开始）")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-len", type=int, default=768)
    ap.add_argument("--max-prompt", type=int, default=384)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ds = load_dataset("json", data_files={
        "train": os.path.join(a.data, "train.jsonl"),
        "validation": os.path.join(a.data, "val.jsonl")})

    # TRL 1.17 要求对话格式：prompt/chosen/rejected 都是消息列表
    def _conv(ex):
        return {
            "prompt": ex["prompt"] if isinstance(ex["prompt"], list)
            else [{"role": "user", "content": ex["prompt"]}],
            "chosen": ex["chosen"] if isinstance(ex["chosen"], list)
            else [{"role": "assistant", "content": ex["chosen"]}],
            "rejected": ex["rejected"] if isinstance(ex["rejected"], list)
            else [{"role": "assistant", "content": ex["rejected"]}],
        }

    ds = ds.map(_conv, remove_columns=[c for c in ds["train"].column_names])
    print("数据：train %d｜val %d｜示例 %s"
          % (len(ds["train"]), len(ds["validation"]),
             json.dumps(ds["train"][0], ensure_ascii=False)[:160]))

    model = AutoModelForCausalLM.from_pretrained(
        a.base, dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
        low_cpu_mem_usage=True)

    if a.adapter and os.path.exists(a.adapter):
        print("从已有 adapter 继续：%s" % a.adapter)
        model = PeftModel.from_pretrained(model, a.adapter, is_trainable=True)
        peft_cfg = model.peft_config["default"]
    else:
        print("从底座新建 LoRA")
        lora = LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
            task_type="CAUSAL_LM",
            target_modules=r".*language_model\..*\.(q_proj|k_proj|v_proj|o_proj"
                           r"|gate_proj|up_proj|down_proj)")
        peft_cfg = lora

    model.config.use_cache = False
    n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print("可训参数 %.2fM" % (n_train / 1e6))

    # 不同 TRL 版本参数名不一样（1.17 去掉了 max_prompt_length）→ 按签名过滤
    import inspect
    _cfg_kwargs = dict(
        output_dir=a.out,
        beta=a.beta,
        learning_rate=a.lr,
        num_train_epochs=a.epochs,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=4,
        gradient_checkpointing=True,
        logging_steps=10,
        save_steps=200,
        save_total_limit=2,
        eval_strategy="steps",
        eval_steps=200,
        bf16=True,
        max_length=a.max_len,
        max_prompt_length=a.max_prompt,
        remove_unused_columns=False,
        report_to="none",
        seed=20261109,
        loss_type="sigmoid",
    )
    _ok = set(inspect.signature(DPOConfig.__init__).parameters)
    args = DPOConfig(**{k: v for k, v in _cfg_kwargs.items() if k in _ok})
    print("DPOConfig 生效参数：%s"
          % [k for k in _cfg_kwargs if k in _ok], flush=True)

    _tr_kwargs = dict(
        model=model,
        ref_model=None,
        args=args,
        train_dataset=ds["train"],
        eval_dataset=ds["validation"],
        processing_class=tok,
        tokenizer=tok,
        peft_config=peft_cfg if not a.adapter else None,
    )
    _tok_ok = set(inspect.signature(DPOTrainer.__init__).parameters)
    trainer = DPOTrainer(**{k: v for k, v in _tr_kwargs.items() if k in _tok_ok})
    trainer.train()
    trainer.save_model(a.out)
    tok.save_pretrained(a.out)
    with io.open(os.path.join(a.out, "_dpo_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"base": a.base, "adapter_from": a.adapter, "beta": a.beta,
                   "lr": a.lr, "epochs": a.epochs, "data": a.data,
                   "train": len(ds["train"]), "val": len(ds["validation"])},
                  f, ensure_ascii=False, indent=1)
    print("写出 %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
