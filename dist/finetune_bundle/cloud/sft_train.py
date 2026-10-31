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


def build_example(tok, rec, seq):
    """chat(+可选 tools) -> {input_ids, attention_mask, labels}。

    只训练 **assistant 回合**（含 tool_call 回合），mask 掉 system/user/tool 结果；
    tool_call 回合在 `<|tool_response>` 前截断，避免模型学会自造工具结果。
    """
    messages = rec.get("messages") or []
    tools = rec.get("tools")
    if not messages:
        return None
    full = tok.apply_chat_template(messages, tools=tools, tokenize=False,
                                   add_generation_prompt=False)
    ids = tok(full, add_special_tokens=False)["input_ids"][:seq]
    if not ids:
        return None
    bounds = []
    for i in range(len(messages)):
        pre = tok.apply_chat_template(messages[:i + 1], tools=tools, tokenize=False,
                                      add_generation_prompt=False)
        bounds.append(len(tok(pre, add_special_tokens=False)["input_ids"]))
    try:
        tresp = tok.convert_tokens_to_ids("<|tool_response>")
    except Exception:  # noqa: BLE001
        tresp = -1
    labels = [-100] * len(ids)
    prev = 0
    for i, m in enumerate(messages):
        if m.get("role") == "assistant":
            s, e = prev, min(bounds[i], len(ids))
            if m.get("tool_calls") and tresp is not None and tresp >= 0:
                for t in range(s, e):
                    if ids[t] == tresp:
                        e = t
                        break
            for t in range(max(0, s), max(0, e)):
                if t < len(ids):
                    labels[t] = ids[t]
        prev = bounds[i]
    if all(x == -100 for x in labels):
        return None
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": labels}

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

    def map_fn(rec):
        ex = build_example(tok, rec, args.seq)
        return ex or {"input_ids": [], "attention_mask": [], "labels": []}

    def prep(rows):
        # 纯 Python 里先 map 成扁平 {input_ids,attention_mask,labels}，避免新版
        # datasets 对异构嵌套列（messages/tools）做 Arrow 类型推断而失败。
        examples = []
        for r in rows:
            if not any(m.get("role") == "assistant"
                       for m in (r.get("messages") or [])):
                continue
            ex = build_example(tok, r, args.seq)
            if ex:
                examples.append(ex)
        return Dataset.from_list(examples)

    train = prep(read_jsonl(args.train))
    val_rows = read_jsonl(args.val) if args.val else []
    val = prep(val_rows) if val_rows else None

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
