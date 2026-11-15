# -*- coding: utf-8 -*-
"""打包 v13 全部产物：adapter / GGUF / 评测 / 日志 / 报告。"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "dist", "v13_产出_20261114")
os.makedirs(OUT, exist_ok=True)
for sub in ("01_adapter", "02_gguf", "03_eval", "04_logs"):
    os.makedirs(os.path.join(OUT, sub), exist_ok=True)

COPIES = [
    (os.path.join(ROOT, "models", "lora", "yuanheng-v13", "adapter_config.json"), "01_adapter", None),
    (os.path.join(ROOT, "models", "lora", "yuanheng-v13", "adapter_model.safetensors"), "01_adapter", None),
    (os.path.join(ROOT, "models", "gguf-lora", "yuanheng-v13-lora.gguf"), "02_gguf", None),
    (os.path.join(ROOT, "cache", "eval_v13.json"), "03_eval", None),
    (os.path.join(ROOT, "cache", "eval_基线b_带工具.json"), "03_eval", "eval_基线.json"),
    (os.path.join(ROOT, "dist", "material_v13", "report.md"), "04_logs", "素材报告.md"),
    (os.path.join(ROOT, "dist", "material_v13", "manifest.json"), "04_logs", "素材manifest.json"),
]
for src, sub, rename in COPIES:
    if os.path.exists(src):
        name = rename or os.path.basename(src)
        shutil.copy2(src, os.path.join(OUT, sub, name))
        print("  %-46s %8.1f MB" % (sub + "/" + name, os.path.getsize(src) / 1048576))
    else:
        print("  ⚠ 缺 %s" % src)

# 云端日志从本地缓存正文（训练日志已拉回一部分：见 cache/pull_v13.log）
READ = """
# v13 产出包（2026-11-14）

## 一、结果（本机 llama.cpp q4_0 + 该 adapter，greedy，同一套评测器）

| 套 | 基线（生产权重） | **v13** | 修好 | 新挂 | 判定 |
|---|---|---|---|---|---|
| 56 题 | 45/56 | **38/56** | 3（p06/r03/st03） | **10** | **变差** |
| 28 题群聊 | 28/28 | **26/28** | 0 | 2（g13/g23） | **变差** |

新挂的 10 道里 **8 道是工具题**（t02/t03/t04/t07/t08/t09/t10/t11/t14）。

## 二、为什么差（我的判断，有依据）

1. **口述故事给太重**：477 条 ×2.0 = 954 权重，占 **26.1%**，把「格式类/工具类」样本的相对权重压下去了。
   故事是 38 字的短口语问答，**教的是味道，不教工具调用格式**。
2. **禁令清洗连带删掉 543 条**，其中对称句 250 条多在场景/思辨长答里 →
   `scene` 从 1641 掉到 1179（-28%），场景覆盖面受损。
3. 工具样本本身只少了 64 条（900→836），**不是被误删**。

## 三、训练本身是健康的（这点没问题）

```
attn_implementation = eager
enable_input_require_grads() 已显式开启
trainable params 34,881,536 (0.4373%)
[gradcheck] 第 10 步：LoRA 参数 516 个，非零梯度 516 个
loss 5.5845 → 1.8822（-66.3%），706 步，1885 秒
```

## 四、下一步（按性价比）

| 优先级 | 动作 | 预期 |
|---|---|---|
| **P0** | 口述故事权重 **2.0 → 1.0**（约 13%），工具/纪律样本权重 **×1.5** | 找回工具题 |
| P1 | 禁令清洗从「整条丢」改成「只删那句」，把 462 条场景样本捞回来 ~70% | 场景题回升 |
| P2 | 若仍不如基线，回到 v9t10 数据 + 只加故事 @1.0 的单变量对照 | 干净归因 |

## 五、文件

| 文件 | 说明 |
|---|---|
| `01_adapter/adapter_model.safetensors` | LoRA 权重（133 MB，fp32） |
| `01_adapter/adapter_config.json` | LoRA 配置 |
| `02_gguf/yuanheng-v13-lora.gguf` | 已转好的 GGUF（66.6 MB，f16），可直接给 llama-server `--lora` |
| `03_eval/eval_v13.json` | v13 逐题明细（含每道题的答案原文） |
| `03_eval/eval_基线.json` | 基线逐题明细（对拍用） |
| `04_logs/素材报告.md` + `素材manifest.json` | 数据构成与清洗记录 |
"""
io.open(os.path.join(OUT, "README_结果与结论.md"), "w", encoding="utf-8").write(READ)

# 打包 zip
zp = os.path.join(ROOT, "dist", "v13_产出_20261114.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, _d, fs in os.walk(OUT):
        for f in fs:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, OUT))
print("\n目录：%s" % OUT)
print("压缩包：%s（%.1f MB）" % (zp, os.path.getsize(zp) / 1048576))
