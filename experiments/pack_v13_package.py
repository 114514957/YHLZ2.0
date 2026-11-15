# -*- coding: utf-8 -*-
"""打包 v13 训练整套：训练集 / 验证集 / 题库 / 参数 / 训练器 / 脚本 / 说明。

产出：dist/retrain_pkg_gemma_v13/
    ├─ sft_persona_v13_train.jsonl     5641 条（训练集）
    ├─ sft_persona_v13_val.jsonl        115 条（验证集）
    ├─ config/finetune.gemma4.v13.json 正式参数
    ├─ config/smoke60.json             冒烟参数（60 条 ×6ep）
    ├─ train_v13.py                    训练器（Gemma 开关 + 梯度自检）
    ├─ eval/persona_bank.py            56 题题库（确定性判分）
    ├─ eval/group_bank.py              28 题群聊题库
    ├─ eval/eval56_28.py               评测脚本
    ├─ run_smoke.sh / run_full.sh / run_eval.sh
    ├─ README_训练说明.md
    └─ manifest.json（每个文件的 sha256 与条数）
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SRC = os.path.join(ROOT, "dist", "material_v13")
OUT = os.path.join(ROOT, "dist", "retrain_pkg_gemma_v13")
os.makedirs(os.path.join(OUT, "config"), exist_ok=True)
os.makedirs(os.path.join(OUT, "eval"), exist_ok=True)


def sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(p: str) -> int:
    return sum(1 for ln in io.open(p, encoding="utf-8", errors="replace") if ln.strip())


COPIES = [
    (os.path.join(SRC, "sft_persona_v13_train.jsonl"), "sft_persona_v13_train.jsonl"),
    (os.path.join(SRC, "sft_persona_v13_val.jsonl"), "sft_persona_v13_val.jsonl"),
    (os.path.join(SRC, "config", "finetune.gemma4.v13.json"), "config/finetune.gemma4.v13.json"),
    (os.path.join(ROOT, "dist", "_v13_pack", "smoke60.json"), "config/smoke60.json"),
    (os.path.join(SRC, "train_v13.py"), "train_v13.py"),
    (os.path.join(ROOT, "tools", "persona_bank.py"), "eval/persona_bank.py"),
    (os.path.join(ROOT, "tools", "group_bank.py"), "eval/group_bank.py"),
    (os.path.join(ROOT, "experiments", "eval56_28.py"), "eval/eval56_28.py"),
    (os.path.join(SRC, "manifest.json"), "manifest_material.json"),
    (os.path.join(SRC, "report.md"), "素材构建报告.md"),
]
files = []
for src, rel in COPIES:
    if not os.path.exists(src):
        print("⚠ 缺 %s（跳过）" % src)
        continue
    dst = os.path.join(OUT, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    info = {"path": rel, "bytes": os.path.getsize(dst), "sha256": sha256(dst)}
    if rel.endswith(".jsonl"):
        info["rows"] = count_rows(dst)
    files.append(info)
    print("  %-40s %8d B%s" % (rel, info["bytes"],
                               "  %d 行" % info["rows"] if "rows" in info else ""))

# ── 运行脚本 ──────────────────────────────────────────────────────────
SH = r"""#!/usr/bin/env bash
# v13 训练脚本（云端 Linux）。用法：bash run_full.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-/root/miniconda3/bin/python}"
BASE="${BASE:-/root/autodl-tmp/models/gemma-4-e4b-it}"
CFG="${1:-$HERE/config/finetune.gemma4.v13.json}"

# 把配置里的路径改成本机路径（幂等）
"$PY" - "$CFG" "$HERE" "$BASE" <<'PYEOF'
import json,sys,os
cfg_path,here,base = sys.argv[1],sys.argv[2],sys.argv[3]
c=json.load(open(cfg_path))
c["base_model"]=base
c["train_file"]=os.path.join(here,"sft_persona_v13_train.jsonl")
c["val_file"]=os.path.join(here,"sft_persona_v13_val.jsonl")
c.setdefault("output_dir","/root/autodl-tmp/models/lora/yuanheng-v13")
json.dump(c,open(cfg_path+".local.json","w"),ensure_ascii=False,indent=2)
print("本地配置：",cfg_path+".local.json")
PYEOF

exec "$PY" -u "$HERE/train_v13.py" --config "$CFG.local.json"
"""
io.open(os.path.join(OUT, "run_full.sh"), "w", encoding="utf-8", newline="\n").write(SH)

SH_SMOKE = r"""#!/usr/bin/env bash
# v13 冒烟：60 条 ×6 epoch，只验证训练通路与梯度（不出分）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec bash "$HERE/run_full.sh" "$HERE/config/smoke60.json"
"""
io.open(os.path.join(OUT, "run_smoke.sh"), "w", encoding="utf-8", newline="\n").write(SH_SMOKE)

SH_EVAL = r"""#!/usr/bin/env bash
# 56+28 评测（需先起 llama-server：--lora <adapter.gguf> --port 8093）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-/root/miniconda3/bin/python}"
PORT="${PORT:-8093}"
exec "$PY" -u "$HERE/eval/eval56_28.py" --tag "v13" --port "$PORT"
"""
io.open(os.path.join(OUT, "run_eval.sh"), "w", encoding="utf-8", newline="\n").write(SH_EVAL)

# ── 说明 ──────────────────────────────────────────────────────────────
manifest = json.load(io.open(os.path.join(SRC, "manifest.json"), encoding="utf-8"))
by = manifest["by_source"]
top = sorted(by.items(), key=lambda kv: -kv[1]["w"])[:6]
lines = [
    "# v13 训练包（2026-11-14）",
    "",
    "## 里面有什么",
    "",
    "| 文件 | 说明 |",
    "|---|---|",
    "| `sft_persona_v13_train.jsonl` | **训练集 %d 条** |" % manifest["n_train"],
    "| `sft_persona_v13_val.jsonl` | **验证集 %d 条** |" % manifest["n_val"],
    "| `config/finetune.gemma4.v13.json` | 正式参数（1 epoch / lr 2e-4 / 706 步） |",
    "| `config/smoke60.json` | 冒烟参数（60 条 × 6 epoch，先跑它） |",
    "| `train_v13.py` | 训练器：Gemma 开关清单 + **梯度自检** |",
    "| `eval/persona_bank.py` | 56 题题库（确定性判分，无 LLM 判官） |",
    "| `eval/group_bank.py` | 28 题群聊题库 |",
    "| `eval/eval56_28.py` | 评测脚本（greedy，带 43 个工具定义） |",
    "| `run_smoke.sh` / `run_full.sh` / `run_eval.sh` | 三条命令搞定 |",
    "| `manifest.json` | 每个文件的 sha256（校验用） |",
    "",
    "## 素材构成（按权重占比）",
    "",
    "| 来源 | 条数 | 权重占比 |",
    "|---|---|---|",
]
for name, v in top:
    lines.append("| %s | %d | %.1f%% |" % (name, v["n"], v["share_w"]))
lines += [
    "",
    "已按老爹禁令清洗：破折号 %d 处改句号（样本保留）；禁令命中 543 条整条丢"
    "（对称句 250 / 「行，」97 / 阴阳收尾 48 / 陪伴式 43 / 认领式 29 / 表态 24 …）。"
    % (manifest["filters"].get("dash_fixed", 0)),
    "",
    "## 三条命令",
    "",
    "```bash",
    "bash run_smoke.sh                 # 1) 冒烟（约 2 分钟）：必须看到 gradcheck 非零梯度 = 参数数",
    "bash run_full.sh                  # 2) 正式（约 31 分钟）：706 步",
    "bash run_eval.sh                  # 3) 评测（需先起 llama-server --lora ... --port 8093）",
    "```",
    "",
    "## 训练参数（全部显式）",
    "",
    "| 项 | 值 |",
    "|---|---|",
    "| epochs | **1** |",
    "| batch × grad_accum | **4 × 2 = 8** |",
    "| lr | **2e-4**，cosine，warmup 3% |",
    "| max_seq_len | 1536 |",
    "| lora | r=16, α=32, dropout 0.05, **7 类模块全挂** |",
    "| 量化 | 4bit **nf4** + double_quant，计算精度 **fp32** |",
    "| 调度/优化器 | cosine + paged_adamw_8bit（**显式写死**） |",
    "| 梯度裁剪 | 1.0 |",
    "| **attn_implementation** | **eager**（Gemma4 音频塔不支持 sdpa，写 sdpa 直接报错） |",
    "| 梯度检查点 | 开，`use_reentrant=False`，并显式 `enable_input_require_grads()` |",
    "| DeepSpeed | **不用** |",
    "",
    "## 必须看的三行日志",
    "",
    "```",
    "[train] attn_implementation = eager",
    "[train] enable_input_require_grads() 已显式开启",
    "[gradcheck] 第 10 步（backward 后）：LoRA 参数 516 个，非零梯度 516 个",
    "```",
    "",
    "**第三行是判生死的**：非零梯度数必须等于参数数。为 0 说明通路断了（见 README 末尾排查）。",
    "",
    "## 常见故障",
    "",
    "| 现象 | 原因 |",
    "|---|---|",
    "| `Gemma4AudioModel does not support ... scaled_dot_product_attention` | 配置里 `attn_implementation` 写成了 sdpa，必须 `eager` |",
    "| `[gradcheck] 非零梯度 0` | `use_reentrant=False` 没传 / `enable_input_require_grads()` 没开 |",
    "| 显存 OOM | `bnb_compute_dtype` 用 bf16，或降 batch |",
    "| loss 不降 | 查 `trainable params` 是不是 34,881,536 |",
]
io.open(os.path.join(OUT, "README_训练说明.md"), "w", encoding="utf-8").write("\n".join(lines))

# ── 总 manifest ───────────────────────────────────────────────────────
for rel, name in (("README_训练说明.md", "README_训练说明.md"),
                  ("run_smoke.sh", "run_smoke.sh"),
                  ("run_full.sh", "run_full.sh"),
                  ("run_eval.sh", "run_eval.sh")):
    p = os.path.join(OUT, rel)
    files.append({"path": rel, "bytes": os.path.getsize(p), "sha256": sha256(p)})

io.open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8").write(
    json.dumps({
        "package": "retrain_pkg_gemma_v13",
        "built_at": "2026-11-14",
        "n_train": manifest["n_train"], "n_val": manifest["n_val"],
        "files": files,
    }, ensure_ascii=False, indent=1))

print("\n打包完成：%s" % OUT)
total = sum(os.path.getsize(os.path.join(OUT, f["path"].replace("/", os.sep)))
            for f in files)
print("文件 %d 个，合计 %.1f MB" % (len(files), total / 1048576))
