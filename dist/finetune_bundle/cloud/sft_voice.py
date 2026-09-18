"""Voice SFT for Yuanheng (ledger 0429): audio -> transcript / audio -> reply.

Continues training on top of an existing SFT adapter (v6) with two behaviours:
  ASR pairs   : system(转写助手) + user(audio) + assistant(transcript)
  Reply pairs : system(元亨+语音纪律) + user(audio) + assistant(short reply)
plus `--rehearsal` text rows from the v6 data so tools/persona do not drift.

Audio examples are single-turn: labels mask everything up to the generation
prompt (computed with the processor, so audio soft tokens are accounted for).
Batch must be 1 for audio rows (frames vary); the collator handles both audio
and text rows so rehearsal mixes in the same run.

Usage (Linux/GPU, run from the bundle root so `voice/audio/...` resolves):
    python sft_voice.py --base $BASE --sft-adapter $DISK/models/lora/yuanheng-v6-sft \
        --train voice/voice_v1_train.jsonl --val voice/voice_v1_val.jsonl \
        --rehearsal sft_persona_v6_train.jsonl --rehearsal-n 120 \
        --out $DISK/models/lora/yuanheng-v7-sft --no-4bit

Local dry-run (CPU, no model, no GPU):
    python sft_voice.py --dry-run --base <hf-base> --train voice/voice_v1_train.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TAG = "voice"

# ---------------------------------------------------------------- data helpers
def read_jsonl(p):
    rows = []
    if not Path(p).exists():
        return rows
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def _resolve_media(rows: list[dict], media_root: Path) -> list[dict]:
    """Make audio paths absolute so the processor can read them anywhere."""
    for r in rows:
        for m in r.get("messages") or []:
            c = m.get("content")
            if not isinstance(c, list):
                continue
            for part in c:
                if isinstance(part, dict) and part.get("type") == "audio":
                    for key in ("audio", "path", "url"):
                        v = part.get(key)
                        if v and not str(v).startswith(("http", "data:")):
                            p = Path(str(v))
                            part[key] = str(p if p.is_absolute() else media_root / p)
    return rows


def build_audio_example(proc, rec, seq):
    """Single-turn audio chat -> tensors; labels mask up to the reply prompt."""
    msgs = rec.get("messages") or []
    if len(msgs) < 2 or msgs[-1].get("role") != "assistant":
        return None
    prefix = msgs[:-1]
    full = proc.apply_chat_template(msgs, tokenize=True, return_dict=True,
                                    return_tensors="pt",
                                    add_generation_prompt=False)
    pre = proc.apply_chat_template(prefix, tokenize=True, return_dict=True,
                                   return_tensors="pt", add_generation_prompt=True)
    ids = full["input_ids"][0]
    n = int(pre["input_ids"].shape[1])
    if ids.shape[0] > seq:
        return None  # too long: skip (truncating would desync audio features)
    labels = [-100] * min(n, ids.shape[0]) + ids[min(n, ids.shape[0]):].tolist()
    return {
        "input_ids": ids.tolist(),
        "attention_mask": full["attention_mask"][0].tolist(),
        "labels": labels,
        "input_features": full["input_features"][0],
        "input_features_mask": full["input_features_mask"][0],
        "mm_token_type_ids": full["mm_token_type_ids"][0].tolist(),
    }


def build_text_example(tok, rec, seq):
    """Rehearsal rows: reuse the v6 text masking (assistant turns only)."""
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
    labels = [-100] * len(ids)
    prev = 0
    for i, m in enumerate(messages):
        if m.get("role") == "assistant":
            for t in range(max(0, prev), max(0, min(bounds[i], len(ids)))):
                if t < len(ids):
                    labels[t] = ids[t]
        prev = bounds[i]
    if all(x == -100 for x in labels):
        return None
    return {"input_ids": ids, "attention_mask": [1] * len(ids), "labels": labels}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--sft-adapter", default="")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", default="")
    ap.add_argument("--rehearsal", default="")
    ap.add_argument("--rehearsal-n", type=int, default=120)
    ap.add_argument("--media-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="")
    ap.add_argument("--seq", type=int, default=3072)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--no-4bit", dest="no_4bit", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dry-limit", type=int, default=40)
    ap.add_argument("--smoke", action="store_true",
                    help="3 样本 1 步前向冒烟（上云第一步先跑它）")
    args = ap.parse_args()
    media_root = Path(args.media_root)

    from transformers import AutoProcessor

    proc = AutoProcessor.from_pretrained(args.base, trust_remote_code=True)
    tok = getattr(proc, "tokenizer", None)
    if tok is None:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    audio_rows = _resolve_media(read_jsonl(args.train), media_root)
    if args.dry_run:
        rows = audio_rows[: args.dry_limit]
        ok = 0
        lens, masked = [], []
        for r in rows:
            try:
                ex = build_audio_example(proc, r, args.seq)
            except Exception as exc:  # noqa: BLE001
                print(f"[dry] ERR {r.get('id')}: {type(exc).__name__}: {str(exc)[:140]}")
                continue
            if not ex:
                print(f"[dry] skip {r.get('id')} (empty/too long)")
                continue
            ok += 1
            lens.append(len(ex["input_ids"]))
            masked.append(sum(1 for x in ex["labels"] if x != -100))
            if ok == 1:
                print("[dry] first example keys:", sorted(ex.keys()),
                      "| feat:", tuple(ex["input_features"].shape),
                      "| mask:", tuple(ex["input_features_mask"].shape))
        print(json.dumps({"dry_ok": ok, "tried": len(rows),
                          "len_min": min(lens or [0]), "len_max": max(lens or [0]),
                          "masked_min": min(masked or [0]),
                          "masked_max": max(masked or [0])}, ensure_ascii=False))
        return 0 if ok else 1

    # ---------------- real training ----------------
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import (BitsAndBytesConfig, Trainer, TrainingArguments)
    from transformers import Gemma4ForConditionalGeneration as LM

    rows = audio_rows
    texts = []
    if args.rehearsal:
        import random

        pool = read_jsonl(args.rehearsal)
        random.seed(20260918)
        random.shuffle(pool)
        texts = pool[: args.rehearsal_n]

    examples = []
    for r in rows:
        try:
            ex = build_audio_example(proc, r, args.seq)
        except Exception:  # noqa: BLE001
            ex = None
        if ex:
            examples.append(ex)
    for r in texts:
        ex = build_text_example(tok, r, args.seq)
        if ex:
            examples.append(ex)
    if args.smoke:
        examples = examples[:3]
    print(f"[voice] examples={len(examples)} (audio={len(rows)}, rehearsal={len(texts)})",
          flush=True)

    ds = Dataset.from_list(examples)

    val_examples = []
    for r in _resolve_media(read_jsonl(args.val), media_root) if args.val else []:
        try:
            ex = build_audio_example(proc, r, args.seq)
        except Exception:  # noqa: BLE001
            ex = None
        if ex:
            val_examples.append(ex)
    val_ds = Dataset.from_list(val_examples) if val_examples else None
    if val_ds is not None:
        print(f"[voice] val examples={len(val_examples)}", flush=True)

    def collate(features):
        maxlen = max(len(f["input_ids"]) for f in features)
        pad = tok.pad_token_id or 0
        ids, att, lab = [], [], []
        for f in features:
            n = maxlen - len(f["input_ids"])
            ids.append(f["input_ids"] + [pad] * n)
            att.append(f["attention_mask"] + [0] * n)
            lab.append(f["labels"] + [-100] * n)
        batch = {"input_ids": torch.tensor(ids), "attention_mask": torch.tensor(att),
                 "labels": torch.tensor(lab)}
        if all("input_features" in f for f in features):
            batch["input_features"] = torch.stack([f["input_features"] for f in features])
            batch["input_features_mask"] = torch.stack(
                [f["input_features_mask"] for f in features])
            mt = [f["mm_token_type_ids"] + [0] * (maxlen - len(f["mm_token_type_ids"]))
                  for f in features]
            batch["mm_token_type_ids"] = torch.tensor(mt)
        return batch

    bnb = None if args.no_4bit else BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16)
    model = LM.from_pretrained(args.base, quantization_config=bnb, device_map={"": 0},
                               dtype=torch.bfloat16, low_cpu_mem_usage=True,
                               trust_remote_code=True)
    model.config.use_cache = False
    if not args.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    if args.sft_adapter:
        model = PeftModel.from_pretrained(model, args.sft_adapter, is_trainable=True)
    else:
        projs = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
        target = r"model\.language_model\..*\.(" + "|".join(projs) + ")"
        model = get_peft_model(model, LoraConfig(
            r=args.r, lora_alpha=args.alpha, lora_dropout=0.05,
            target_modules=target, bias="none", task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    import inspect

    _kw = dict(output_dir=args.out or "voice-sft", per_device_train_batch_size=1,
               gradient_accumulation_steps=args.grad_accum,
               num_train_epochs=args.epochs, learning_rate=args.lr,
               warmup_steps=20, logging_steps=5, save_steps=200,
               save_total_limit=2, bf16=True, gradient_checkpointing=True,
               report_to="none", seed=20260918, remove_unused_columns=False)
    if args.smoke:
        _kw.update(max_steps=1, logging_steps=1, save_steps=1,
                   gradient_accumulation_steps=1)
    if val_ds is not None:
        _kw.update(eval_strategy="steps", eval_steps=100)
    _sig = set(inspect.signature(TrainingArguments.__init__).parameters)
    cfg = TrainingArguments(**{k: v for k, v in _kw.items() if k in _sig})
    Trainer(model=model, args=cfg, train_dataset=ds, eval_dataset=val_ds,
            data_collator=collate).train()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print("[voice] adapter ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
