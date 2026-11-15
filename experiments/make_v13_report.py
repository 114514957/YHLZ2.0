# -*- coding: utf-8 -*-
"""为 material_v13 出报告 + 训练配置，并与 v9t10 做配比对照。"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
V13 = os.path.join(ROOT, "dist", "material_v13")


def comp(path: str) -> dict:
    stat = defaultdict(lambda: {"n": 0, "w": 0.0})
    for ln in io.open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        fam = str(r.get("source") or "?").split(":")[0].split("/")[0]
        stat[fam]["n"] += 1
        stat[fam]["w"] += float(r.get("weight") or 1.0)
    tw = sum(v["w"] for v in stat.values()) or 1.0
    return {k: {"n": v["n"], "w": v["w"], "pct": 100 * v["w"] / tw} for k, v in stat.items()}


old = comp(os.path.join(ROOT, "dist", "retrain_pkg_gemma_v9t10",
                        "sft_persona_v9t10_train.jsonl"))
new = comp(os.path.join(V13, "sft_persona_v13_train.jsonl"))
man = json.load(open(os.path.join(V13, "manifest.json"), encoding="utf-8"))

lines = [
    "# 素材集 v13（重建版）",
    "",
    "> 2026-11-14 · 依据：训练素材盘点_20261114（v9t10 48 分 vs v11 44 分，差在 LCCC 稀释）",
    "> 构建器：`tools/build_material_v13.py`（可重跑，确定性）",
    "",
    "## 一、做了什么",
    "",
    "| 动作 | 内容 |",
    "|---|---|",
    "| 底 | **v9t10 全部 5931 条**（原样、原权重——那是 48 分的配比） |",
    "| 加 | **口述故事 488 条**，权重 **1.5×**（v11 当时是 3.5×，那次混了 LCCC，不能照抄） |",
    "| 不加 | **LCCC**（证据：7.3% 权重换 -4 分） |",
    "| 不加 | persona_gen / revised / other（合成或来路不明，留待单独实验） |",
    "| 清洗 | 去重（sha1 角色+内容+tool_calls）｜末条必须 assistant｜≥4 字答案｜≤1400 字｜≤11 条消息｜坏自称丢弃 |",
    "| 上限 | 单来源权重 ≤30%（防某一类再次挤掉人格） |",
    "",
    "## 二、成品",
    "",
    "| 项 | 值 |",
    "|---|---|",
    "| train | **%d 条** |" % man["n_train"],
    "| val | **%d 条** |" % man["n_val"],
    "| Σ权重 | **%.1f** |" % man["sum_weight"],
    "| 丢弃 | %s |" % json.dumps(man["filters"]["drop"], ensure_ascii=False),
    "",
    "## 三、配比对照（权重占比）",
    "",
    "| 来源 | v9t10 | v13 | 变化 |",
    "|---|---|---|---|",
]
_BAN_BLOCK = [
    "",
    "## 三之二、禁令清洗（老爹 2026-11-14 的硬规则）",
    "",
    "| 规则 | 处理 | 命中 |",
    "|---|---|---|",
    "| **破折号**（——、—、–） | **修**：换成句号，样本保留 | **%d 处** |"
    % man["filters"].get("dash_fixed", 0),
    "| 对称句「不是A，而是B」 | 整条丢 | %d |" % man.get("bans_hit", {}).get("对称句（不是A而是B）", 0),
    "| 万能开头「行，」 | 整条丢 | %d |" % man.get("bans_hit", {}).get("万能开头「行」", 0),
    "| 阴阳收尾（满意了？/够了吗？） | 整条丢 | %d |" % man.get("bans_hit", {}).get("阴阳收尾", 0),
    "| 陪伴式（我守着/我不拦/不催） | 整条丢 | %d |" % man.get("bans_hit", {}).get("陪伴式（我守着那套）", 0),
    "| 认领式（我认/认这个） | 整条丢 | %d |" % man.get("bans_hit", {}).get("认领式", 0),
    "| 表态冒充内容（我记下了/本人记住） | 整条丢 | %d |" % man.get("bans_hit", {}).get("表态冒充内容", 0),
    "| 拿姿态当挡箭牌（这话我不接） | 整条丢 | %d |" % man.get("bans_hit", {}).get("拿姿态当挡箭牌", 0),
    "| 评价对方的话（这句话稳/接得漂亮） | 整条丢 | %d |" % man.get("bans_hit", {}).get("评价对方的话（最该减）", 0),
    "| 空泛评价（值得一看/挺有意思） | 整条丢 | %d |" % man.get("bans_hit", {}).get("放哪都成立的评价（空泛）", 0),
    "| 掂量 / 元话语 / 记账式 / 汇报式开头 | 整条丢 | %d |"
    % (man.get("bans_hit", {}).get("掂量式", 0)
       + man.get("bans_hit", {}).get("元话语（说自己的话本身）", 0)
       + man.get("bans_hit", {}).get("记账式（我记下了那套）", 0)
       + man.get("bans_hit", {}).get("汇报式开头", 0)),
    "| 助理腔（我理解你的意思/还需要我做什么） | 整条丢 | 0 |",
    "",
    "> 原则：**破折号是标点习惯→修；其它是「这句话本身不该说」→丢。**",
    "> 词表与线上约束同一份（`config/style_bans.json`），所以线上禁的和训练禁的是同一套。",
    "",
]
for fam in sorted(set(old) | set(new), key=lambda k: -new.get(k, {}).get("pct", 0)):
    o = old.get(fam, {}).get("pct")
    n = new.get(fam, {}).get("pct")
    if o is None and n is None:
        continue
    if o is None:      # 新加
        lines.append("| **%s**（新加） | — | **%.1f%%** | +%.1f |" % (fam, n, n))
        continue
    if n is None:      # 被剔除
        lines.append("| ~~%s~~（剔除） | %.1f%% | — | **-%.1f** |" % (fam, o, o))
        continue
    d = n - o
    if abs(d) < 0.3:
        continue
    lines.append("| %s | %.1f%% | %.1f%% | %+.1f |" % (fam, o, n, d))

lines += _BAN_BLOCK
lines += [
    "",
    "要点：**人格权重 33.5%→25.6%、口述故事 26.1% 成为第一大类**（老爹要求「重」）。",
    "口述故事是老爹亲讲、均 38 字，属「口味」信号；要再调就改",
    "`tools/build_material_v13.py` 的 `DAD_STORY_WEIGHT`（现 **2.0**）后重跑。",
    "",
    "## 四、配套训练配置",
    "",
    "`dist/material_v13/config/finetune.gemma4.v13.json`：",
    "epochs 1｜batch 4×2｜lr 2e-4｜cosine + paged_adamw_8bit｜seq 1536｜r16/α32(7 模块)｜4bit nf4。",
    "与 v12-A 完全一致，**唯一变量是数据**。",
    "",
    "## 五、怎么验",
    "",
    "```bash",
    "python tools/train_preflight.py --config dist/material_v13/config/finetune.gemma4.v13.json \\",
    '    --n-train %d --changed "数据：v9t10 底 + 口述故事，去 LCCC"' % man["n_train"],
    "```",
]

os.makedirs(os.path.join(V13, "config"), exist_ok=True)
io.open(os.path.join(V13, "report.md"), "w", encoding="utf-8").write("\n".join(lines))

cfg = {
    "_说明": "gemma v13：素材重建版（v9t10 底 + 口述故事 488 条 @1.5×，去 LCCC）。"
             "与 v12-A 超参完全一致，唯一变量是数据。",
    "base_model": "/root/autodl-tmp/models/gemma-4-e4b-it",
    "train_file": "/root/yh/material_v13/sft_persona_v13_train.jsonl",
    "val_file": "/root/yh/material_v13/sft_persona_v13_val.jsonl",
    "output_dir": "/root/autodl-tmp/models/lora/yuanheng-v13-material",
    "max_seq_len": 1536, "epochs": 1.0, "batch_size": 4, "grad_accum": 2,
    "lr": 0.0002, "weight_decay": 0.0, "warmup_ratio": 0.03,
    "lr_scheduler_type": "cosine", "optim": "paged_adamw_8bit", "max_grad_norm": 1.0,
    "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
    "target_modules": ".*language_model\\..*\\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)",
    "load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "use_double_quant": True,
    "bnb_compute_dtype": "fp32", "gradient_checkpointing": True, "mask_prompt": True,
    "full_finetune": False, "logging_steps": 20, "save_steps": 200,
    "save_total_limit": 2, "save_only_model": True, "report_to": "none",
    "seed": 20261114,
}
io.open(os.path.join(V13, "config", "finetune.gemma4.v13.json"), "w",
        encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
print("报告：%s" % os.path.relpath(os.path.join(V13, "report.md"), ROOT))
print("配置：%s" % os.path.relpath(os.path.join(V13, "config", "finetune.gemma4.v13.json"), ROOT))
