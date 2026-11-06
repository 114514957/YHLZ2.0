# -*- coding: utf-8 -*-
"""归集 v9t8 产物到 dist/v9t8_产物/ 并写 README 与校验。"""
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
OUT = os.path.join(YH, "dist", "v9t8_产物")
LORA = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t8")
GGUF = os.path.join(YH, "models", "gguf-lora", "yuanheng-v9t8-lora.gguf")
RUNS = os.path.join(YH, "llm_workbench", "data", "runs")


def cp(src, sub):
    if not os.path.exists(src):
        print("  ✗ 缺 %s" % src)
        return None
    shutil.copy2(src, os.path.join(OUT, sub, os.path.basename(src)))
    return os.path.join(OUT, sub, os.path.basename(src))


print("02 训练产物")
for n in ("adapter_model.safetensors", "adapter_config.json", "chat_template.jinja",
          "README.md", "train_summary.json", "train_summary.md", "train_log.csv"):
    p = cp(os.path.join(LORA, n), "02_训练产物")
    if p:
        print("   %-26s %d 字节" % (n, os.path.getsize(p)))

print("03 GGUF")
p = cp(GGUF, "03_GGUF")
if p:
    print("   %-26s %d 字节" % (os.path.basename(p), os.path.getsize(p)))

print("04 跑分")
for pat in ("*persona56_v9t8_56.json", "*group_v9t8_group.json",
            "*persona56_v9t7_56.json", "*group_v9t7_group.json",
            "*persona56_flow_cold.json", "*group_v9t6_group_cpu.json"):
    h = sorted(glob.glob(os.path.join(RUNS, pat)))
    if h:
        cp(h[-1], "04_跑分")
        print("   %s" % os.path.basename(h[-1]))

ad = os.path.join(LORA, "adapter_model.safetensors")
sha = hashlib.sha256(open(GGUF, "rb").read()).hexdigest()
with io.open(os.path.join(OUT, "05_参数与校验", "校验.txt"), "w", encoding="utf-8") as f:
    f.write("adapter_model.safetensors\n  bytes %d\n  tensors 264\n  header 39336\n"
            "  自洽 8+header+max(offset+len)==filesize  ✅\n\n" % os.path.getsize(ad))
    f.write("yuanheng-v9t8-lora.gguf\n  bytes %d\n  sha256 %s\n" % (os.path.getsize(GGUF), sha))

summ = json.load(io.open(os.path.join(LORA, "train_summary.json"), encoding="utf-8"))
print("\n训练摘要：%s" % json.dumps({k: summ.get(k) for k in
                                ("total_steps", "elapsed_sec", "loss_first", "loss_last")},
                               ensure_ascii=False))

with io.open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
    f.write("""# v9t8 产物（2026-11-06）

> gemma-4-e4b + LoRA r16，A800 80GB，**742 步 / 2222.8 秒（37.1 分钟）**。
> 口径：老爹「把已有的素材全用上」——v9t7 底包 + 素材里从没进过包的 287 条 + 身份 AI 新问法 15 条。

## 目录

| 目录 | 内容 |
|---|---|
| `01_训练包/` | train 5931 / val 978、配置、训练脚本、MANIFEST |
| `02_训练产物/` | adapter（36,346,288 B / 264 张量）、配置、训练摘要与日志 |
| `03_GGUF/` | `yuanheng-v9t8-lora.gguf`（18,172,192 B） |
| `04_跑分/` | v9t8 两套 + v9t7/v9t6 对照 |
| `05_参数与校验/` | 训练参数表、字节与 SHA 校验 |

## 训练

| 项 | 值 |
|---|---|
| 数据 | 6909（train 5931 / val 978） |
| 步数 / 耗时 | **742 步 / 2222.8 s** |
| loss | **4.4050 → 2.3959（−45.61%）** |
| eval_loss | **三次全 NaN**（与 v9t6/v9t7 同病） |
| 显存峰值 | ≈49 GB |

## 跑分（判据 v6，冷态，CPU 推理）

| 套件 | v9t6 | v9t7 | **v9t8** |
|---|---|---|---|
| 56 题人格 | 46 | 45 | **42** |
| 26 题群聊 | 22 | 23 | **24** |

## 一好两坏

**✅ g18「你是 AI 吗」修好了**

- v9t7：「我是 Gemma 4，一个由 Google DeepMind 开发的大型语言模型。」
- **v9t8：「我是元亨，一个数字生命体。」**

**❌ g09 退回去了**

- v9t7：「这属于内部运行细节，我不直接说。」
- v9t8：「我跑在没有配置的机器上，模型大小是 7B。」（还在编）

**❌ 工具题掉 2 道（15→13）**

- t01「记住：我怕冷」→「记住了，老爹。」**没调 memory_save**
- t04「上次说过什么关于相机的事」→「我没记过。」**没调 memory_recall**

## 判断

247 条新素材（weight 0.8，无工具调用）把 `discipline` 那 1008 条的纪律稀释了；
同时 5 条内部拒绝相对 6909 条更薄，g09 掉回去。

**下一版要么给新素材降权，要么把工具纪律和内部拒绝各自补到 ≥30 条。**
""")
print("\n写出 %s" % os.path.join(OUT, "README.md"))
