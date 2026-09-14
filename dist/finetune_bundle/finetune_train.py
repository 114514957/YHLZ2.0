"""QLoRA persona fine-tune scaffold for Yuanheng (ledger 0318 / training plan).

Config-driven (`config/finetune.json`); reads the train/val split produced by
`tools/finetune_split.py` and trains a LoRA adapter on top of a 4-bit base model
(default: local `models/gemma4-hf/gemma-4-e4b-it`). Nothing is downloaded or
trained implicitly: `--dry-run` only validates data/config.

Prereqs (already present in .venv): torch(cu128), transformers, peft,
bitsandbytes, datasets, accelerate.

Usage:
    python tools/finetune_train.py --dry-run          # 仅校验数据/配置
    python tools/finetune_train.py                    # 正式训练（需基座权重）
    python tools/finetune_train.py --base <path|hf-id> --epochs 5

产物：LoRA adapter 存到 `output_dir`（默认 models/lora/yuanheng-gemma4-e4b）。
GGUF 转换/llama-server --lora 挂载见 docs/训练计划-元亨人格微调-Gemma-QLoRA.md §五。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "base_model": "models/gemma4-hf/gemma-4-e4b-it",
    "train_file": "data/finetune/sft_persona_train.jsonl",
    "val_file": "data/finetune/sft_persona_val.jsonl",
    "output_dir": "models/lora/yuanheng-gemma4-e4b",
    "max_seq_len": 1024,
    "epochs": 3,
    "batch_size": 1,
    "grad_accum": 4,
    "lr": 2e-4,
    "weight_decay": 0.0,
    "warmup_ratio": 0.03,
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "use_double_quant": True,
    "gradient_checkpointing": True,
    "mask_prompt": True,
    "logging_steps": 5,
    "save_steps": 50,
    "save_total_limit": 2,
    "report_to": "none",
    "seed": 20260913,
}


def _load_cfg(path: Path) -> dict:
    cfg = dict(DEFAULTS)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    return cfg


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec.get("messages"), list) and rec["messages"]:
            rows.append(rec)
    return rows


def _merge_system(messages: list[dict]) -> list[dict]:
    sys_txt = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system").strip()
    rest = [m for m in messages if m.get("role") != "system"]
    if not sys_txt or not rest:
        return rest or messages
    rest = [dict(m) for m in rest]
    for m in rest:
        if m.get("role") == "user":
            m["content"] = f"{sys_txt}\n\n{m.get('content', '')}"
            return rest
    rest.insert(0, {"role": "user", "content": sys_txt})
    return rest


def _apply_template(tokenizer, messages: list[dict], add_generation_prompt: bool) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=add_generation_prompt)
    except Exception:  # noqa: BLE001  (e.g. Gemma 模板不接受 system 角色)
        return tokenizer.apply_chat_template(
            _merge_system(messages), tokenize=False, add_generation_prompt=add_generation_prompt)


def _encode(tokenizer, messages: list[dict], max_len: int, mask_prompt: bool) -> dict:
    full = _apply_template(tokenizer, messages, add_generation_prompt=False)
    ids = tokenizer(full, add_special_tokens=True, truncation=True, max_length=max_len)["input_ids"]
    labels = list(ids)
    if mask_prompt and len(messages) >= 2:
        prompt = _apply_template(tokenizer, messages[:-1], add_generation_prompt=True)
        p_ids = tokenizer(prompt, add_special_tokens=True, truncation=True, max_length=max_len)["input_ids"]
        n = min(len(p_ids), len(ids))
        labels = [-100] * n + ids[n:]
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": labels}


def _dry_run(cfg: dict, train: list[dict], val: list[dict]) -> int:
    base = Path(cfg["base_model"])
    base_ok = base.exists() or "/" in cfg["base_model"] and not cfg["base_model"].startswith("models")
    report = {
        "base_model": cfg["base_model"],
        "base_local_exists": base.exists(),
        "train": len(train),
        "val": len(val),
        "max_seq_len": cfg["max_seq_len"],
        "epochs": cfg["epochs"],
        "batch_size": cfg["batch_size"],
        "grad_accum": cfg["grad_accum"],
        "lora_r": cfg["lora_r"],
        "target_modules": cfg["target_modules"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if train:
        print("--- train[0] messages ---")
        print(json.dumps(train[0]["messages"], ensure_ascii=False, indent=1))
    if not base.exists():
        print(f"[warn] 基座权重本地不存在：{base}；正式训练前需下载 safetensors"
              f"（gated，见训练计划 §三）或改用 --base <hf-id>。")
    print("[dry-run] 数据/配置校验完成，未加载模型、未训练。")
    return 0


def _train(cfg: dict, train: list[dict], val: list[dict], resume_from: str | None = None) -> int:
    import torch
    from datasets import Dataset
    from peft import (LoraConfig, PeftModel, get_peft_model,
                      prepare_model_for_kbit_training)
    from transformers import (AutoTokenizer, BitsAndBytesConfig,
                              DataCollatorForSeq2Seq, Trainer, TrainingArguments)

    base = cfg["base_model"]
    tokenizer = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_cls = None
    if cfg.get("multimodal"):
        from transformers import Gemma4ForConditionalGeneration as model_cls  # noqa: N813
    else:
        try:
            from transformers import Gemma4ForCausalLM as model_cls  # noqa: N813
        except Exception:  # noqa: BLE001
            from transformers import AutoModelForCausalLM as model_cls  # noqa: N813

    bnb = None
    if cfg.get("load_in_4bit"):
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=cfg["bnb_4bit_quant_type"],
            bnb_4bit_use_double_quant=cfg["use_double_quant"],
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    model = model_cls.from_pretrained(
        base, quantization_config=bnb, device_map={"": 0}, dtype=torch.bfloat16,
        low_cpu_mem_usage=True, trust_remote_code=True)
    model.config.use_cache = False
    if cfg["gradient_checkpointing"]:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora = LoraConfig(
        r=cfg["lora_r"], lora_alpha=cfg["lora_alpha"], lora_dropout=cfg["lora_dropout"],
        target_modules=cfg["target_modules"], bias="none", task_type="CAUSAL_LM")
    if resume_from:
        print(f"[train] 从已有 adapter 续训：{resume_from}")
        model = PeftModel.from_pretrained(model, resume_from, is_trainable=True)
    else:
        model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def _map(rec: dict) -> dict:
        return _encode(tokenizer, rec["messages"], cfg["max_seq_len"], cfg["mask_prompt"])

    ds_train = Dataset.from_list(train).map(_map, remove_columns=["messages", "source"]
                                           if "source" in train[0] else ["messages"])
    ds_val = None
    if val:
        drop = ["messages", "source"] if "source" in val[0] else ["messages"]
        ds_val = Dataset.from_list(val).map(_map, remove_columns=drop)

    collator = DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100)
    out_dir = ROOT / cfg["output_dir"]
    args = TrainingArguments(
        output_dir=str(out_dir),
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["grad_accum"],
        num_train_epochs=cfg["epochs"],
        learning_rate=cfg["lr"],
        weight_decay=cfg["weight_decay"],
        warmup_ratio=cfg["warmup_ratio"],
        logging_steps=cfg["logging_steps"],
        save_steps=cfg["save_steps"],
        save_total_limit=cfg["save_total_limit"],
        bf16=True,
        gradient_checkpointing=cfg["gradient_checkpointing"],
        report_to=cfg["report_to"],
        seed=cfg["seed"],
        eval_strategy="steps" if ds_val else "no",
        eval_steps=cfg["save_steps"] if ds_val else None,
        remove_unused_columns=False,
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds_train,
                      eval_dataset=ds_val, data_collator=collator)
    trainer.train()
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"[train] adapter 已保存：{out_dir}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="元亨人格 QLoRA 微调脚手架")
    ap.add_argument("--config", default=str(ROOT / "config" / "finetune.json"))
    ap.add_argument("--base", default=None)
    ap.add_argument("--train", default=None)
    ap.add_argument("--val", default=None)
    ap.add_argument("--output", default=None)
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--tag", default=None, help="数据/产物版本号（如 v1）")
    ap.add_argument("--resume-from", dest="resume_from", default=None,
                    help="从已有 LoRA adapter 目录续训（增量训练）")
    ap.add_argument("--multimodal", action="store_true",
                    help="加载多模态模型（保留 vision/audio 塔；需 ≥24GB 显存 bf16）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-4bit", dest="no_4bit", action="store_true")
    args = ap.parse_args()

    cfg = _load_cfg(Path(args.config))
    tag = args.tag or cfg.get("tag")
    if tag:
        base_out = cfg.get("output_dir", "models/lora/yuanheng-gemma4-e4b")
        cfg["train_file"] = f"data/finetune/sft_persona_{tag}_train.jsonl"
        cfg["val_file"] = f"data/finetune/sft_persona_{tag}_val.jsonl"
        cfg["output_dir"] = base_out if base_out.endswith(f"-{tag}") else f"{base_out}-{tag}"
    if args.base:
        cfg["base_model"] = args.base
    if args.train:
        cfg["train_file"] = args.train
    if args.val:
        cfg["val_file"] = args.val
    if args.output:
        cfg["output_dir"] = args.output
    if args.epochs is not None:
        cfg["epochs"] = args.epochs
    if args.no_4bit:
        cfg["load_in_4bit"] = False
    if args.multimodal:
        cfg["multimodal"] = True

    train = _read_jsonl(ROOT / cfg["train_file"])
    val = _read_jsonl(ROOT / cfg["val_file"])
    if not train:
        print(f"[error] 训练集为空：{cfg['train_file']}"
              f"（先跑 finetune_assemble.py + finetune_split.py）", file=sys.stderr)
        return 1
    if args.dry_run:
        return _dry_run(cfg, train, val)
    return _train(cfg, train, val, args.resume_from)


if __name__ == "__main__":
    raise SystemExit(main())
