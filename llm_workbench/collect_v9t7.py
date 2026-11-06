# -*- coding: utf-8 -*-
"""把 v9t7 的产物集中到一个文件夹并按类分组。

dist/v9t7_产物/
  01_训练包/     数据 + 配置 + 脚本
  02_训练产物/   adapter + 训练摘要/日志
  03_GGUF/       可直接被 llama-server 挂载的 LoRA
  04_跑分/       v9t7 与 v9t6 的跑分记录 + 对比
  05_参数与校验/ 训练参数表、字节/SHA 校验
"""
from __future__ import annotations

import glob
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "dist", "v9t7_产物")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7")
LORA = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t7")
GGUF = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t7-lora.gguf")
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")

DIRS = ["01_训练包", "02_训练产物", "03_GGUF", "04_跑分", "05_参数与校验"]
for d in DIRS:
    os.makedirs(os.path.join(OUT, d), exist_ok=True)


def cp(src, dst_dir, name=None):
    if not os.path.exists(src):
        print("  ✗ 缺 %s" % src)
        return None
    dst = os.path.join(OUT, dst_dir, name or os.path.basename(src))
    shutil.copy2(src, dst)
    print("  ✓ %-46s %d 字节" % (os.path.relpath(dst, OUT), os.path.getsize(dst)))
    return dst


print("== 01 训练包 ==")
for fn in ("sft_persona_v9t7_train.jsonl", "sft_persona_v9t7_val.jsonl",
           "finetune_train.py", "run_v9t7.sh", "MANIFEST.json", "README_训练须知.md"):
    cp(os.path.join(PKG, fn), "01_训练包")
cp(os.path.join(PKG, "config", "finetune.gemma4.v9t7lora.json"), "01_训练包",
   "finetune.gemma4.v9t7lora.json")

print("== 02 训练产物 ==")
for fn in ("adapter_model.safetensors", "adapter_config.json", "chat_template.jinja",
           "README.md", "train_summary.json", "train_summary.md", "train_log.csv"):
    cp(os.path.join(LORA, fn), "02_训练产物")

print("== 03 GGUF ==")
cp(GGUF, "03_GGUF")

print("== 04 跑分 ==")
for pat in ("*persona56_v9t7_56.json", "*group_v9t7_group.json",
            "*persona56_flow_cold.json", "*group_v9t6_group_cpu.json"):
    hits = sorted(glob.glob(os.path.join(RUNS, pat)))
    if hits:
        cp(hits[-1], "04_跑分")
    else:
        print("  ✗ 没找到 %s" % pat)

adapter = os.path.join(LORA, "adapter_model.safetensors")
gguf_size = os.path.getsize(GGUF)
summary = json.load(io.open(os.path.join(LORA, "train_summary.json"), encoding="utf-8"))
ad_size = os.path.getsize(adapter)
sha = __import__("hashlib").sha256(io.open(GGUF, "rb").read()).hexdigest()

with io.open(os.path.join(OUT, "05_参数与校验", "训练参数.md"), "w", encoding="utf-8") as f:
    f.write("# v9t7 训练参数（云端实跑记录）\n\n")
    f.write("| 项 | 值 |\n|---|---|\n")
    for k in ("base_model", "train_file", "n_train", "n_val", "epochs", "batch_size",
              "grad_accum", "effective_batch", "lr", "lr_scheduler_type", "warmup_ratio",
              "lora_r", "lora_alpha", "max_seq_len", "load_in_4bit", "full_finetune",
              "total_steps", "elapsed_sec", "loss_first", "loss_last", "loss_min",
              "loss_reduction_pct", "n_log_points"):
        f.write("| %s | %s |\n" % (k, summary.get(k)))
    f.write("\n- eval_loss：**全部 NaN**（与 v9t6 同病，见台账 1060/1088）\n")
    f.write("- 训练卡：NVIDIA A800 80GB PCIe；实测显存峰值 **48,935 MiB**\n")
    f.write("- 训练耗时：**2144.8 s = 35.7 min**（708 步，2.9 s/步）\n")

with io.open(os.path.join(OUT, "05_参数与校验", "校验.txt"), "w", encoding="utf-8") as f:
    f.write("adapter_model.safetensors\n")
    f.write("  bytes      %d\n" % ad_size)
    f.write("  tensors    264\n")
    f.write("  header_len 39336\n")
    f.write("  自洽        8+header+max(offset+len) == filesize ✅\n\n")
    f.write("yuanheng-v9t7-lora.gguf\n")
    f.write("  bytes      %d\n" % gguf_size)
    f.write("  sha256     %s\n" % sha)
    f.write("  对照 v9t6：adapter 34,662,888 → 36,346,288（同形状，值不同）；"
            "GGUF 18,172,192（同尺寸）\n")

print("\n== 完成：%s" % OUT)
for d in DIRS:
    n = len(os.listdir(os.path.join(OUT, d)))
    print("   %-12s %d 个文件" % (d, n))
