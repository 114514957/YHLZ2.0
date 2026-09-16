"""SFT for Yuanheng (Gemma-4-E4B, multimodal kept). Linux/GPU.

Reads chat-format jsonl (messages: system/user/assistant), trains a LoRA on the
language model (vision/audio towers frozen). QLoRA 4bit by default; `--no-4bit`
for bf16 (no bitsandbytes).

Usage:
    python sft_train.py --tag v3 --multimodal --train sft_persona_v3_train.jsonl \
        --val sft_persona_v3_val.jsonl --base models/gemma4-hf/gemma-4-e4b-it \
        --out models/lora/yuanheng-sft [--no-4bit]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def read_jsonl(p):
    rows = []
    if not Path(p).exists():
        return rows
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--multimodal", action="store_true")
    ap.add_argument("--no-4bit", dest="no_4bit", action="store_true")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq,
                              Trainer, TrainingArguments)
    if args.multimodal:
        from transformers import Gemma4ForConditionalGeneration as LM
    else:
        try:
            from transformers import Gemma4ForCausalLM as LM
        except Exception:
            from transformers import AutoModelForCausalLM as LM

    tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = None if args.no_4bit else BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16)
    model = LM.from_pretrained(args.base, quantization_config=bnb, device_map={"": 0},
                               dtype=torch.bfloat16, low_cpu_mem_usage=True,
                               trust_remote_code=True)
    model.config.use_cache = False
    if not args.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    _projs = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    if args.multimodal:
        # Gemma4 towers also expose q_proj.. but wrapped in Gemma4ClippableLinear
        # (PEFT only supports nn.Linear) -> restrict LoRA to the language model.
        target = r"model\.language_model\..*\.(" + "|".join(_projs) + ")"
    else:
        target = _projs
    lora = LoraConfig(r=args.r, lora_alpha=args.alpha, lora_dropout=0.05,
                      target_modules=target, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def enc(messages):
        full = tok.apply_chat_template(messages, tokenize=False)
        ids = tok(full, add_special_tokens=True, truncation=True, max_length=args.seq)["input_ids"]
        labels = list(ids)
        if len(messages) >= 2:
            prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
            p = tok(prompt, add_special_tokens=True, truncation=True, max_length=args.seq)["input_ids"]
            n = min(len(p), len(ids)); labels = [-100]*n + ids[n:]
        return {"input_ids": ids, "attention_mask": [1]*len(ids), "labels": labels}

    def map_fn(rec):
        return enc(rec["messages"])
    train = Dataset.from_list(read_jsonl(args.train))
    val = Dataset.from_list(read_jsonl(args.val)) if args.val and read_jsonl(args.val) else None
    drop = ["messages","source"]
    train = train.map(map_fn, remove_columns=[c for c in train.column_names if c in drop])
    if val is not None:
        val = val.map(map_fn, remove_columns=[c for c in val.column_names if c in drop])

    import inspect
    total_steps = max(1, (len(train) // max(1, args.batch * args.grad_accum)) * int(args.epochs))
    _kw = dict(
        output_dir=args.out, per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum, num_train_epochs=args.epochs,
        learning_rate=args.lr, warmup_ratio=0.03, warmup_steps=max(1, int(0.03 * total_steps)),
        logging_steps=5, save_steps=100, save_total_limit=2, bf16=True,
        gradient_checkpointing=(not args.no_4bit), report_to="none", seed=20260913,
        eval_strategy=("steps" if val else "no"), eval_steps=(100 if val else None),
        remove_unused_columns=False)
    _sig = set(inspect.signature(TrainingArguments.__init__).parameters)
    _kw = {k: v for k, v in _kw.items() if k in _sig}
    args_t = TrainingArguments(**_kw)
    collator = DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=-100)
    trainer = Trainer(model=model, args=args_t, train_dataset=train, eval_dataset=val,
                      data_collator=collator)
    trainer.train()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out); tok.save_pretrained(args.out)
    print("[sft] adapter ->", args.out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
