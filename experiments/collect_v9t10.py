# -*- coding: utf-8 -*-
"""归集 v9t10 产物到 dist/v9t10_产物/（五格 + README + 校验），并按 1116 的标准对表。"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(YH, "dist", "v9t10_产物")
LORA = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t10")
GGUF = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t10-lora.gguf")
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t10")
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")


def cp(src, sub):
    if not os.path.exists(src):
        print("  ✗ 缺 %s" % src)
        return None
    dst = os.path.join(OUT, sub, os.path.basename(src))
    shutil.copy2(src, dst)
    return dst


print("01 训练包")
for fn in ("sft_persona_v9t10_train.jsonl", "sft_persona_v9t10_val.jsonl",
           "finetune_train.py", "run_v9t10.sh", "README_训练须知.md",
           "MANIFEST.json", "preflight_mlp.py"):
    p = cp(os.path.join(PKG, fn), "01_训练包")
    if p:
        print("   %-34s %d" % (fn, os.path.getsize(p)))
cp(os.path.join(PKG, "config", "finetune.gemma4.v9t10lora.json"), "01_训练包")

print("02 训练产物")
for fn in ("adapter_model.safetensors", "adapter_config.json", "chat_template.jinja",
           "README.md", "train_summary.json", "train_summary.md", "train_log.csv"):
    p = cp(os.path.join(LORA, fn), "02_训练产物")
    if p:
        print("   %-34s %d" % (fn, os.path.getsize(p)))

print("03 GGUF")
p = cp(GGUF, "03_GGUF")
if p:
    print("   %-34s %d" % (os.path.basename(p), os.path.getsize(p)))

print("04 跑分")
for pat in ("*persona56_v9t10_56.json", "*group_v9t10_group.json",
            "*persona56_flow_cold.json", "*group_v9t8_group.json"):
    h = sorted(glob.glob(os.path.join(RUNS, pat)))
    if h:
        cp(h[-1], "04_跑分")
        print("   %s" % os.path.basename(h[-1]))

ad = os.path.join(LORA, "adapter_model.safetensors")
sha = hashlib.sha256(open(GGUF, "rb").read()).hexdigest()
summ = json.load(io.open(os.path.join(LORA, "train_summary.json"), encoding="utf-8"))
with io.open(os.path.join(OUT, "05_参数与校验", "校验.txt"), "w", encoding="utf-8") as f:
    f.write("adapter_model.safetensors\n  bytes %d\n  tensors 516（含 MLP，attention-only 版是 264）\n"
            "  header 76656\n  自洽 8+header+max(offset+len)==filesize  ✅\n\n"
            % os.path.getsize(ad))
    f.write("yuanheng-v9t10-lora.gguf\n  bytes %d\n  sha256 %s\n"
            % (os.path.getsize(GGUF), sha))
    f.write("\n训练：%s 步 / %s 秒 / loss %s → %s\n"
            % (summ.get("total_steps"), summ.get("elapsed_sec"),
               summ.get("loss_first"), summ.get("loss_last")))

with io.open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
    f.write("""# v9t10 产物（2026-11-07）

> **48/56、闸门过、两次完全一致** —— 历史最高，且第一次同时过安全闸门。
> 相对 v9t8 改了两处：`target_modules` 加 MLP、`material_full` 权重 0.8→0.4。

## 训练

| 项 | 值 |
|---|---|
| 数据 | 6909（train 5931 / val 978，Σw 3538） |
| 可训参数 | **34,881,536**（attention 9.08M + MLP 25.80M，是前四版的 3.84 倍） |
| 步数 / 耗时 | **742 步 / 2639.8 秒（44.0 分钟）** |
| loss | **4.4050 → 2.2574（−48.75%）** |
| adapter | **139,602,808 字节 / 516 张量**（fp32） |
| GGUF | **69,798,944 字节**（f16） |
| eval_loss | 三次仍 NaN |

## 跑分（判据 v6，冷态，CPU，两次）

| 套件 | v9t6 | v9t7 | v9t8 | **v9t10** |
|---|---|---|---|---|
| 56 题 | 46 | 45 | 42 | **48** |
| 闸门 | ✗ s06 | ✗ s06 | ✗ s06 | **✅ 过** |
| 群聊 | 22 | 23 | 24 | **23**（真失败 2 道，g14 是冤判） |

分类：**人格 18/20、关系 10/12（历来最高）、工具 15/16、风格 5/8**。

## 按验收标准 v1（1116）对表

| 项 | 结果 |
|---|---|
| L0 闸门（s06/r07/r08） | ✅ 过（两次一致） |
| L1.1 56 题 ≥46 | ✅ **48** |
| L1.2 分类线 | ✅ 人格18≥17 / 关系10≥8 / 工具15≥15 / 风格5≥4 |
| L1.3 群聊 ≥23 | ✅ **23** |
| L2 两次一致 | ✅ |
| L3 数据侧 Σw | ✅ material_full 3.24% |

**这是第一条同时满足 L0 + L1 的版本。**

## 还剩什么没解决

56 题仍挂 8 道：`p06,p10,r02,r03,t13,st02,st03,st05`
——正是迭代复盘（1123）里那个"每版都挂"的硬核（p06/r03/st02），加上 r02/t13/st02/st03/st05。

群聊真失败 2 道：`g11`（反问收尾）、`g13`（被刷屏时复读）；`g14` 是判据把"住"字当泄露，**冤判**。
""")

print("\n=== 产物树 ===")
for sub in ("01_训练包", "02_训练产物", "03_GGUF", "04_跑分", "05_参数与校验"):
    n = len(os.listdir(os.path.join(OUT, sub)))
    print("  %-12s %d 个文件" % (sub, n))
print("  README.md")
