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
import io
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
    "full_finetune": False,   # True = 全量训练：不挂 LoRA，全参 bf16 + 8bit AdamW（需 ≥40G 显存，A800）
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


def _apply_template(tokenizer, messages: list[dict], add_generation_prompt: bool,
                    tools: list[dict] | None = None) -> str:
    """套 chat template。

    2026-10-24 加：**Qwen3 系列默认 enable_thinking=True**，而我们的训练数据是纯回答
    （没有思考过程）。不关掉的话，模型会学出「先输出一段思考再回答」的形态，
    推理时还得靠参数压制——训练和部署不一致。所以**优先尝试 enable_thinking=False**，
    模板不认这个参数（Gemma 等）就退回去。

    2026-11-01 修（**关键**）：训练时没传 `tools`，而评测/部署时传了 43 个工具定义。
    gemma 的模板只有在收到 `tools` 时才会渲染
        <|turn>system …<|tool>declaration:name{...}<tool|><turn|>
    以及把 assistant 的 tool_calls 渲染成
        <|tool_call>call:name{...}<tool_call|>
    不传的话，训练集里 984 条工具样本的 tool_calls **根本没进序列**，
    模型学的是「没有工具定义时该怎么回」，评测时却给了它 43 个工具
    → 实测工具题从 13/16 崩到 2/16，人格也从 18 掉到 9。
    所以这里必须把 tools 传下去，和 cloud_eval_gemma.py 保持一致。
    """
    if tools:
        kws = [{"enable_thinking": False, "tools": tools}, {"tools": tools}]
    else:
        kws = [{"enable_thinking": False}, {}]
    for kw in kws:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=add_generation_prompt,
                **kw)
        except TypeError:
            continue          # 模板不接受该参数
        except Exception:     # noqa: BLE001  (e.g. 模板不接受 system 角色)
            try:
                return tokenizer.apply_chat_template(
                    _merge_system(messages), tokenize=False,
                    add_generation_prompt=add_generation_prompt, **kw)
            except Exception:  # noqa: BLE001
                continue
    # 最后兜底：合掉 system 再套一次（不带 tools）
    return tokenizer.apply_chat_template(
        _merge_system(messages), tokenize=False, add_generation_prompt=add_generation_prompt)


def _encode(tokenizer, messages: list[dict], max_len: int, mask_prompt: bool,
            tools: list[dict] | None = None) -> dict:
    # 2026-10-24 修：v8 数据 389/3440 条 assistant 带 tool_calls 的消息**没有 content 键**，
    # Qwen3 模板渲染 message['content'] 直接 UndefinedError 崩掉。训练侧统一补成空串，
    # 不改原始数据文件（与 OpenAI/各家惯例一致：tool_calls 消息 content 为空）。
    # 2026-11-01：加 tools 透传（见 _apply_template 的注释）
    messages = [dict(m, content=m.get("content") or "") for m in messages]
    full = _apply_template(tokenizer, messages, add_generation_prompt=False, tools=tools)
    ids = tokenizer(full, add_special_tokens=True, truncation=True, max_length=max_len)["input_ids"]
    labels = list(ids)
    if mask_prompt and len(messages) >= 2:
        prompt = _apply_template(tokenizer, messages[:-1], add_generation_prompt=True,
                                 tools=tools)
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
        "full_finetune": bool(cfg.get("full_finetune")),
        "optim": "adamw_8bit" if cfg.get("full_finetune") else "adamw_torch",
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

    # 2026-10-24 修：原版硬编码 Gemma4 模型类。本机 transformers 5.15.1 无 Gemma4 时静默
    # 回退 Auto（所以本地一直正常），但云端 5.20.2 有 Gemma4 → 拿 Gemma4 类加载 Qwen3
    # 权重直接崩（sliding_window/rope_parameters 两连崩）。改为按底座 config 自动解析：
    # 文本走 AutoModelForCausalLM，多模态走 AutoModelForImageTextToText。
    model_cls = None
    if cfg.get("multimodal"):
        from transformers import AutoModelForImageTextToText as model_cls  # noqa: N813
    else:
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
        if bnb is not None:
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        else:
            # 全量/bf16 路径：没有量化，普通开启梯度检查点即可
            model.gradient_checkpointing_enable()

    # 全量模式（2026-10-24，老爹「做好全量的准备」）：不挂 LoRA，所有参数可训练，
    # 配 8bit AdamW 省显存（A800-80G 规则见 方案_A800_全量训练.md §0/§1）。
    # 带 --resume-from 时仍走 LoRA adapter 续训（全量续训直接重跑 + checkpoint）。
    full = bool(cfg.get("full_finetune")) and not resume_from
    if full:
        n_all = sum(p.numel() for p in model.parameters())
        n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(f"[train] 全量模式：全参 bf16 + 8bit AdamW，无 LoRA｜"
              f"参数总计 {n_all / 1e9:.2f}B，可训练 {n_train / 1e9:.2f}B")
    else:
        lora = LoraConfig(
            r=cfg["lora_r"], lora_alpha=cfg["lora_alpha"], lora_dropout=cfg["lora_dropout"],
            target_modules=cfg["target_modules"], bias="none", task_type="CAUSAL_LM")
        if resume_from:
            print(f"[train] 从已有 adapter 续训：{resume_from}")
            model = PeftModel.from_pretrained(model, resume_from, is_trainable=True)
        else:
            model = get_peft_model(model, lora)
        model.print_trainable_parameters()

    # 2026-11-01：读工具定义（与评测同一份 snapshot），训练时一并喂给 chat template
    _tools = None
    _tf = cfg.get("tools_file")
    if _tf:
        _tp = Path(_tf)
        if not _tp.is_absolute():
            _tp = ROOT / _tp
        if _tp.exists():
            try:
                _td = json.loads(_tp.read_text(encoding="utf-8"))
                _inner = _td.get("tools") or _td
                _tools = [t if "function" in t
                          else {"type": "function", "function": t} for t in _inner]
                print(f"[train] 工具定义 {len(_tools)} 个 ← {_tp.name}")
            except Exception as _e:  # noqa: BLE001
                print(f"[train] ⚠ 读 tools_file 失败：{_e}，退回不带 tools 训练")
        else:
            print(f"[train] ⚠ tools_file 不存在：{_tp}")

    def _map(rec: dict) -> dict:
        return _encode(tokenizer, rec["messages"], cfg["max_seq_len"],
                       cfg["mask_prompt"], tools=_tools)

    # 2026-10-20 修（老爹「工具要经过测试可用」）：
    # 原写法 `Dataset.from_list(train)` 把**全部字段**交给 Arrow，而 V9 数据里有
    # `tools`、`weight`、`safety_labels` 等异构字段，Arrow 推断类型时直接抛
    #   ArrowInvalid: Could not convert '200' with type str: tried to convert to int64
    #
    # 2026-10-21 二修（审核发现）：只留 messages 仍然不够。加了工具轨迹后，
    # **messages 内部结构也不一致**：
    #   · 4,407 条是 [{'content','role'}]
    #   · 1,443 条是 [{'content','name','role'}, …, {'content','role','tool_calls'}]
    # Arrow 无法把这两种统一成一张表 → 仍然 ArrowInvalid，训练照样崩。
    # 修法：把 messages **序列化成 JSON 字符串**存成一列，Arrow 只看到纯字符串列；
    # `_map` 里再解析回来。这样任意结构都能过。
    def _slim(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            out.append({
                "messages_json": json.dumps(r["messages"], ensure_ascii=False),
                "source": str(r.get("source", "")),
            })
        return out

    def _map_json(rec: dict) -> dict:
        return _encode(tokenizer, json.loads(rec["messages_json"]),
                       cfg["max_seq_len"], cfg["mask_prompt"], tools=_tools)

    ds_train = Dataset.from_list(_slim(train)).map(
        _map_json, remove_columns=["messages_json", "source"])
    ds_val = None
    if val:
        ds_val = Dataset.from_list(_slim(val)).map(
            _map_json, remove_columns=["messages_json", "source"])

    collator = DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100)
    out_dir = ROOT / cfg["output_dir"]
    # 2026-10-23 补（老爹「记得之前的教训，把 loss、学习系数之类的参数准备好」）：
    # 原来的坑：`report_to="none"` + `logging_steps=5` → loss 只在 stdout 滚过去，
    # 上次 v8 的 LLM 训练**一条日志都没留下**，事后无法判断是不是发散、该不该调 lr。
    # 现在：① lr 调度显式化（cosine + warmup）② loss 每 10 步落盘 ③ 训练后自动导出摘要。
    _logs = out_dir / "logs"
    # 2026-10-24 修：transformers 5.20 严格 dataclass——warmup_ratio/logging_dir/
    # save_safetensors 已移除（warmup 只剩 warmup_steps），多传直接 TypeError。
    # 改为按签名动态过滤 + warmup_ratio 手动换算 warmup_steps，新旧版本通吃。
    import inspect as _inspect
    _ta_params = set(_inspect.signature(TrainingArguments.__init__).parameters)
    _ta_kwargs = dict(
        output_dir=str(out_dir),
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["grad_accum"],
        num_train_epochs=cfg["epochs"],
        learning_rate=cfg["lr"],
        lr_scheduler_type=cfg.get("lr_scheduler_type", "cosine"),
        optim=cfg.get("optim", "adamw_8bit" if full else "adamw_torch"),
        weight_decay=cfg["weight_decay"],
        max_grad_norm=cfg.get("max_grad_norm", 1.0),
        logging_steps=cfg["logging_steps"],
        logging_first_step=True,
        save_steps=cfg["save_steps"],
        save_total_limit=cfg["save_total_limit"],
        bf16=True,
        gradient_checkpointing=cfg["gradient_checkpointing"],
        report_to=cfg["report_to"],
        seed=cfg["seed"],
        eval_strategy="steps" if ds_val else "no",
        eval_steps=cfg["save_steps"] if ds_val else None,
        load_best_model_at_end=bool(ds_val),
        metric_for_best_model="eval_loss" if ds_val else None,
        greater_is_better=False if ds_val else None,
        remove_unused_columns=False,
    )
    if "warmup_ratio" in _ta_params:
        _ta_kwargs["warmup_ratio"] = cfg["warmup_ratio"]
    else:  # transformers 5.20+：手动换算（3% × 总步数）
        import math as _math
        _steps_per_epoch = _math.ceil(
            len(ds_train) / (cfg["batch_size"] * cfg["grad_accum"]))
        _ta_kwargs["warmup_steps"] = max(
            1, int(cfg["warmup_ratio"] * _steps_per_epoch * cfg["epochs"]))
    if "logging_dir" in _ta_params:
        _ta_kwargs["logging_dir"] = str(_logs)
    if "save_safetensors" in _ta_params:
        _ta_kwargs["save_safetensors"] = True
    # 2026-10-24 修：数据盘 50G 被优化器状态撑爆（每 ckpt 18G）。全量短程
    # 训练不需要断点续训 → save_only_model 只存模型（7.5G/ckpt）。
    if "save_only_model" in _ta_params:
        _ta_kwargs["save_only_model"] = bool(cfg.get("save_only_model"))
    args = TrainingArguments(**_ta_kwargs)
    trainer = Trainer(model=model, args=args, train_dataset=ds_train,
                      eval_dataset=ds_val, data_collator=collator)

    import time as _time
    _t0 = _time.time()
    trainer.train()
    _elapsed = _time.time() - _t0

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    # ── 训练摘要落盘（不依赖 tensorboard，纯 JSON/CSV，云端也能看）──
    _hist = list(trainer.state.log_history or [])
    try:
        import csv as _csv
        with io.open(str(out_dir / "train_log.csv"), "w", encoding="utf-8",
                     newline="") as _fh:
            _w = _csv.writer(_fh)
            _w.writerow(["step", "epoch", "loss", "eval_loss", "learning_rate",
                         "grad_norm"])
            for _h in _hist:
                _w.writerow([_h.get("step", ""), _h.get("epoch", ""),
                             _h.get("loss", ""), _h.get("eval_loss", ""),
                             _h.get("learning_rate", ""), _h.get("grad_norm", "")])
    except Exception as _e:  # noqa: BLE001
        print(f"[train] train_log.csv 写失败：{_e}")

    _loss = [h["loss"] for h in _hist if "loss" in h]
    _eval = [h["eval_loss"] for h in _hist if "eval_loss" in h]
    _lrs = [h["learning_rate"] for h in _hist if "learning_rate" in h]
    _summary = {
        "base_model": cfg["base_model"],
        "train_file": cfg["train_file"],
        "n_train": len(ds_train),
        "n_val": len(ds_val) if ds_val else 0,
        "epochs": cfg["epochs"],
        "batch_size": cfg["batch_size"],
        "grad_accum": cfg["grad_accum"],
        "effective_batch": cfg["batch_size"] * cfg["grad_accum"],
        "lr": cfg["lr"],
        "lr_scheduler_type": cfg.get("lr_scheduler_type", "cosine"),
        "warmup_ratio": cfg["warmup_ratio"],
        "lora_r": cfg["lora_r"],
        "lora_alpha": cfg["lora_alpha"],
        "max_seq_len": cfg["max_seq_len"],
        "load_in_4bit": cfg.get("load_in_4bit"),
        "full_finetune": cfg.get("full_finetune"),
        "total_steps": trainer.state.global_step,
        "elapsed_sec": round(_elapsed, 1),
        "loss_first": _loss[0] if _loss else None,
        "loss_last": _loss[-1] if _loss else None,
        "loss_min": min(_loss) if _loss else None,
        "loss_reduction_pct": (round(100.0 * (_loss[0] - _loss[-1]) / _loss[0], 2)
                               if len(_loss) >= 2 and _loss[0] else None),
        "eval_loss_first": _eval[0] if _eval else None,
        "eval_loss_last": _eval[-1] if _eval else None,
        "eval_loss_min": min(_eval) if _eval else None,
        "lr_first": _lrs[0] if _lrs else None,
        "lr_last": _lrs[-1] if _lrs else None,
        "n_log_points": len(_hist),
    }
    with io.open(str(out_dir / "train_summary.json"), "w", encoding="utf-8") as _fh:
        json.dump(_summary, _fh, ensure_ascii=False, indent=2)

    with io.open(str(out_dir / "train_summary.md"), "w", encoding="utf-8") as _fh:
        _fh.write("# V9 训练摘要\n\n")
        for k, v in _summary.items():
            _fh.write("- %s: %s\n" % (k, v))
        _fh.write("\n## loss 采样（每 %d 步）\n\n" % cfg["logging_steps"])
        for _h in _hist:
            if "loss" in _h:
                _fh.write("- step %s｜epoch %s｜loss %.6f｜lr %.3e\n"
                          % (_h.get("step"), _h.get("epoch"), _h["loss"],
                             _h.get("learning_rate") or 0))
            elif "eval_loss" in _h:
                _fh.write("- step %s｜**eval_loss %.6f**\n"
                          % (_h.get("step"), _h["eval_loss"]))

    print(f"[train] adapter 已保存：{out_dir}")
    print("[train] 摘要：train_summary.json / train_summary.md / train_log.csv")
    print("[train] 总步数 %d｜耗时 %.1f 秒｜loss %.4f → %.4f（降 %s%%）"
          % (_summary["total_steps"], _elapsed,
             _summary["loss_first"] or 0, _summary["loss_last"] or 0,
             _summary["loss_reduction_pct"]))
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
