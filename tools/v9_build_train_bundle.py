#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包 V9 云端训练包：拿到机器后一条命令就能跑。

产出 `dist/v9_train_bundle/`：
    tools/finetune_train.py          训练脚本（零 backend 依赖，已修 3 处必崩点）
    tools/verify_bundle.py           上机自检（数据/模板/token 分布，不吃 GPU）
    config/finetune_v9_cloud.json    云端配置（基座走 HF id、路径相对 bundle）
    data/train.jsonl val.jsonl test.jsonl
    requirements.txt
    run.sh / run.ps1
    README_云端训练.md
    MANIFEST.json                    文件校验和 + 条数 + 统计

用法：
    python tools/v9_build_train_bundle.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

OUT = os.path.join(ROOT, "dist", "v9_train_bundle")
DATA = {
    "train": "data/finetune/sft_persona_v9t_train.jsonl",
    "val": "data/finetune/sft_persona_v9t_val.jsonl",
    "test": "data/finetune/sft_persona_v9t_test.jsonl",
}

CLOUD_CONFIG = {
    # 2026-10-24：老爹租的是 60 GB 卡，主配置直接按 60 GB 开
    # （不量化 BF16 / batch 16 / seq 1024 / LoRA r32 α64）。
    # loss 与学习率相关参数全部显式写出——上一版 report_to=none + 不落盘，
    # v8 那次训练日志一条没留，事后无法判断是否发散。
    "_comment": "V9 云端训练配置（60 GB 档）。不要写 tag 字段——finetune_train.py "
                "一旦读到 tag 就会覆盖 train_file 指向旧数据。",
    "base_model": "google/gemma-4-E4B-it",
    "data_in": "data/train.jsonl",
    "train_file": "data/train.jsonl",
    "val_file": "data/val.jsonl",
    "output_dir": "out/yuanheng-v9",
    "val_ratio": 0.15,
    "seed": 20261020,
    "max_seq_len": 1024,
    "epochs": 3,
    "batch_size": 16,
    "grad_accum": 2,
    "lr": 0.0002,
    "lr_scheduler_type": "cosine",
    "max_grad_norm": 1.0,
    "weight_decay": 0.0,
    "warmup_ratio": 0.03,
    "lora_r": 32,
    "lora_alpha": 64,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
    "load_in_4bit": False,
    "bnb_4bit_quant_type": "nf4",
    "use_double_quant": True,
    "gradient_checkpointing": True,
    "mask_prompt": True,
    "logging_steps": 10,
    "logging_dir": "out/yuanheng-v9/logs",
    "save_steps": 100,
    "save_total_limit": 3,
    "report_to": "none",
}

REQ = """# V9 云端训练依赖（2026-10-20 实测版本，Linux + CUDA 12.x）
torch>=2.7,<3
transformers==5.15.1
peft==0.20.0
bitsandbytes==0.50.2
datasets>=3.0
accelerate>=1.0
safetensors
sentencepiece
# Gemma 4 需要新版 tokenizer 支持；若报 Gemma4 未知，先确认 transformers 版本
"""

RUN_SH = """#!/usr/bin/env bash
# V9 云端训练启动（2026-10-24）
# 训练完自动打包产物并打印质量判读——上一版跑完就结束，v8 的 loss 日志一条没留。
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${1:-config/finetune_v9_cloud.json}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="train_${STAMP}.log"

echo "日志：$LOG" | tee -a "$LOG"
echo "配置：$CONFIG" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "== 1/4 环境检查 ==" | tee -a "$LOG"
python - <<'PY' 2>&1 | tee -a "$LOG"
import torch
print("torch", torch.__version__, "| cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("GPU", p.name, "| VRAM %.1f GB" % (p.total_memory / 1e9))
else:
    print("!! 没有可用 CUDA")
PY

echo "" | tee -a "$LOG"
echo "== 2/4 数据自检（不吃 GPU）==" | tee -a "$LOG"
python tools/verify_bundle.py 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "== 3/4 开始训练 ==" | tee -a "$LOG"
echo "开始：$(date)" | tee -a "$LOG"
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
python tools/finetune_train.py --config "$CONFIG" 2>&1 | tee -a "$LOG"
echo "结束：$(date)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "== 4/4 打包产物 + 质量判读 ==" | tee -a "$LOG"
python tools/v9_collect_training.py --pack --out out/yuanheng-v9 \
    --tar "v9_train_artifacts_${STAMP}.tar.gz" 2>&1 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "===== 完成 =====" | tee -a "$LOG"
echo "训练日志 : $LOG" | tee -a "$LOG"
echo "产物包   : v9_train_artifacts_${STAMP}.tar.gz" | tee -a "$LOG"
echo "这两样一起拉回本地" | tee -a "$LOG"
"""


def sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> int:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "tools"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)

    # 脚本
    shutil.copy2("tools/finetune_train.py", os.path.join(OUT, "tools", "finetune_train.py"))
    shutil.copy2("tools/v9_verify_bundle.py", os.path.join(OUT, "tools", "verify_bundle.py"))
    shutil.copy2("tools/v9_collect_training.py",
                 os.path.join(OUT, "tools", "v9_collect_training.py"))

    # 配置
    io.open(os.path.join(OUT, "config", "finetune_v9_cloud.json"), "w",
            encoding="utf-8").write(json.dumps(CLOUD_CONFIG, ensure_ascii=False, indent=2) + "\n")

    # 数据
    manifest = {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": {}, "data": {}}
    for kind, src in DATA.items():
        dst = os.path.join(OUT, "data", "%s.jsonl" % kind)
        shutil.copy2(src, dst)
        n = sum(1 for line in io.open(dst, encoding="utf-8") if line.strip())
        manifest["data"][kind] = n
        manifest["files"]["data/%s.jsonl" % kind] = {
            "rows": n, "sha256_16": sha256(dst),
            "bytes": os.path.getsize(dst)}
        print("  data/%-10s %5d 条  %6.1f MB" % (kind + ".jsonl", n,
                                                 os.path.getsize(dst) / 1e6))

    io.open(os.path.join(OUT, "requirements.txt"), "w", encoding="utf-8").write(REQ)
    io.open(os.path.join(OUT, "run.sh"), "w", encoding="utf-8", newline="\n").write(RUN_SH)
    try:
        os.chmod(os.path.join(OUT, "run.sh"), 0o755)
    except Exception:
        pass

    for rel in ("tools/finetune_train.py", "tools/verify_bundle.py",
                "tools/v9_collect_training.py",
                "config/finetune_v9_cloud.json", "requirements.txt", "run.sh"):
        p = os.path.join(OUT, rel)
        manifest["files"][rel] = {"sha256_16": sha256(p),
                                  "bytes": os.path.getsize(p)}

    io.open(os.path.join(OUT, "MANIFEST.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(OUT) for f in fs)
    print("\n打包完成 -> dist/v9_train_bundle/  合计 %.1f MB" % (total / 1e6))
    print("  数据：train %d / val %d / test %d"
          % (manifest["data"]["train"], manifest["data"]["val"], manifest["data"]["test"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
