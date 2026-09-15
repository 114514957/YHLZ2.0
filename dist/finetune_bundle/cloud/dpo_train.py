"""DPO for Yuanheng on top of the SFT LoRA adapter (Linux/GPU, trl).

Usage:
    python dpo_train.py --base models/gemma4-hf/gemma-4-e4b-it \
        --sft-adapter models/lora/yuanheng-sft --pairs dpo_pairs.jsonl \
        --out models/lora/yuanheng-dpo
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path


def read_jsonl(p):
    out = []
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except Exception: pass
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--sft-adapter", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out", default="models/lora/yuanheng-dpo")
    ap.add_argument("--epochs", type=float, default=1)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--no-4bit", dest="no_4bit", action="store_true")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import DPOTrainer, DPOConfig
    try:
        from transformers import Gemma4ForConditionalGeneration as LM
    except Exception:
        from transformers import Gemma4ForCausalLM as LM

    tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = None if args.no_4bit else BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16)
    model = LM.from_pretrained(args.base, quantization_config=bnb, device_map={"": 0},
                               dtype=torch.bfloat16, trust_remote_code=True)
    model.config.use_cache = False
    model = PeftModel.from_pretrained(model, args.sft_adapter, is_trainable=True)

    pairs = read_jsonl(args.pairs)
    ds = Dataset.from_list([{"prompt": p["prompt"], "chosen": p["chosen"], "rejected": p["rejected"]}
                            for p in pairs])
    cfg = DPOConfig(output_dir=args.out, per_device_train_batch_size=args.batch,
                    gradient_accumulation_steps=args.grad_accum, num_train_epochs=args.epochs,
                    learning_rate=args.lr, beta=args.beta, max_length=args.seq,
                    logging_steps=5, save_steps=100, save_total_limit=2, bf16=True,
                    gradient_checkpointing=(not args.no_4bit), report_to="none", seed=20260913)
    trainer = DPOTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
    trainer.train()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out); tok.save_pretrained(args.out)
    print("[dpo] adapter ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
