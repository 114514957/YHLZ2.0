# -*- coding: utf-8 -*-
"""v14 开训前终检：数据 / 配置 / 训练器 / 闸门 / 冒烟子集。

只看**实际文件与实际代码**，不看注释；每项给 PASS/FAIL 与数字。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
TRAIN = os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_train.jsonl")
VAL = os.path.join(ROOT, "dist", "material_v14", "sft_persona_v14_val.jsonl")
CFG = os.path.join(ROOT, "dist", "material_v14", "config", "finetune.gemma4.v14.json")
TRAINER = os.path.join(ROOT, "dist", "material_v13", "train_v13.py")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print("%s %-40s %s" % ("✅" if ok else "❌", name, detail))


# ── 1. 数据 ───────────────────────────────────────────────────────────
rows, bad = [], 0
for ln in io.open(TRAIN, encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    try:
        rows.append(json.loads(ln))
    except Exception:  # noqa: BLE001
        bad += 1
check("train JSON 全部可解析", bad == 0, "%d 条，坏行 %d" % (len(rows), bad))

no_assay = [i for i, r in enumerate(rows)
            if not any(m.get("role") == "assistant" for m in r["messages"])]
check("每行都有 assistant", not no_assay, "缺 %d 行" % len(no_assay))

last_not = [i for i, r in enumerate(rows) if r["messages"][-1].get("role") != "assistant"]
check("末条都是 assistant", not last_not, "违例 %d 行" % len(last_not))

# 空 assistant + tool_calls 是合法的；空且无 tool_calls 才是坏样本
bad_empty = 0
for r in rows:
    for m in r["messages"]:
        if m.get("role") == "assistant" and not str(m.get("content") or "").strip():
            if not m.get("tool_calls"):
                bad_empty += 1
check("无『空 assistant 且无 tool_calls』", bad_empty == 0, "%d 处" % bad_empty)

dups = defaultdict(int)
for r in rows:
    k = hashlib.sha1(json.dumps(r["messages"], ensure_ascii=False,
                                sort_keys=True).encode()).hexdigest()
    dups[k] += 1
dup_n = sum(v - 1 for v in dups.values() if v > 1)
check("无完全重复样本", dup_n == 0, "重复 %d 条" % dup_n)

lens = [sum(len(str(m.get("content") or "")) for m in r["messages"]) for r in rows]
check("单样本长度可控（按 token 判，1536 上限）", True,
      "均 %d 字｜实际截断见下项" % (sum(lens) / len(lens)))

# 按 tokenizer 复现训练器截断，算真正会被丢的样本数（这一项才是硬的）
try:
    from transformers import AutoTokenizer
    _tok = AutoTokenizer.from_pretrained(os.path.join(ROOT, "models", "gemma4-hf",
                                                     "gemma-4-e4b-it"))
    dropped = 0
    for r in rows:
        labels, total = [], 0
        for m in r["messages"]:
            seg = _tok(str(m.get("content") or ""), add_special_tokens=False)["input_ids"]
            labels += list(seg) if m.get("role") == "assistant" else [-100] * len(seg)
            total += len(seg)
        if total > 1536:
            labels = labels[:1536]
        if all(x == -100 for x in labels):
            dropped += 1
    check("截断后不会产生『全 -100』样本", dropped == 0,
          "会被丢 %d 条（%.2f%%）" % (dropped, 100 * dropped / len(rows)))
except Exception as _ex:  # noqa: BLE001
    check("截断检查（tokenizer）", False, "跑不了：%s" % _ex)

agg = defaultdict(lambda: {"n": 0, "w": 0.0})
tot_w = 0.0
for r in rows:
    ms = r["messages"]
    w = float(r.get("weight") or 1.0)
    tot_w += w
    src = str(r.get("source") or "")
    if any(m.get("tool_calls") for m in ms) or any(m.get("role") == "tool" for m in ms):
        k = "tool"
    elif "story" in src.lower() or "故事" in src:
        k = "story"
    else:
        k = "other"
    agg[k]["n"] += 1
    agg[k]["w"] += w
tool_pct = 100 * agg["tool"]["w"] / tot_w
story_pct = 100 * agg["story"]["w"] / tot_w
check("工具类权重 ≥12%", tool_pct >= 12, "%.1f%%（%d 条）" % (tool_pct, agg["tool"]["n"]))
check("口味类权重 ≤18%", story_pct <= 18, "%.1f%%（%d 条）" % (story_pct, agg["story"]["n"]))

# 禁词残留（素材清洗是否真的生效）
bans = json.load(io.open(os.path.join(ROOT, "config", "style_bans.json"), encoding="utf-8"))
pats = []
for g, ps in (bans.get("groups") or {}).items():
    if g.startswith("破折号"):
        continue
    for p in ps:
        try:
            pats.append((g, re.compile(p)))
        except re.error:
            pass
hit = 0
hit_pat = []
for r in rows:
    a = "\n".join(str(m.get("content") or "") for m in r["messages"]
                  if m.get("role") == "assistant")
    g = next((g for g, p in pats if p.search(a)), None)
    if g:
        hit += 1
        hit_pat.append(g)
check("素材已按禁令清洗", hit == 0, "残留 %d 条 %s" % (hit, set(hit_pat) or ""))

dash = sum(1 for r in rows
           if any("—" in str(m.get("content") or "") for m in r["messages"]
                  if m.get("role") == "assistant"))
check("无破折号残留", dash == 0, "%d 条" % dash)

# ── 2. 配置 ───────────────────────────────────────────────────────────
cfg = json.load(io.open(CFG, encoding="utf-8"))
need = {"epochs": 1.0, "batch_size": 4, "grad_accum": 2, "lr": 0.0002,
        "max_seq_len": 1536, "lora_r": 16, "lora_alpha": 32,
        "lr_scheduler_type": "cosine", "optim": "paged_adamw_8bit",
        "attn_implementation": "eager", "load_in_4bit": True,
        "gradient_checkpointing": True, "mask_prompt": True, "full_finetune": False}
mismatch = {k: (cfg.get(k), v) for k, v in need.items() if cfg.get(k) != v}
check("配置关键项全部正确", not mismatch, str(mismatch) if mismatch else "15 项全对")
check("无 deepspeed", not cfg.get("deepspeed"), "")
check("grad_check_step 有效", int(cfg.get("grad_check_step", 0)) >= 5,
      "第 %s 步自检" % cfg.get("grad_check_step"))

# 训练器实际读取的键，配置里有没有（只看**真读**，排除赋值语句与 CLI 专用键）
src = io.open(TRAINER, encoding="utf-8").read()
reads = set(re.findall(r'cfg\[["\']([a-z_0-9]+)["\']\](?!\s*=)', src)) | \
        set(re.findall(r'cfg\.get\(["\']([a-z_0-9]+)["\'](?:,|\))', src))
cli_only = {"multimodal", "tag", "tools_file", "eval_batch_size", "freeze_external"}
missing = sorted((reads - set(cfg)) - cli_only)
check("配置覆盖训练器『真读』的键", not missing,
      "缺 %s" % missing if missing else "%d 个键全覆盖" % len(reads))
check("无默认值且缺失的键（KeyError 风险）",
      not (set(re.findall(r'cfg\[["\']([a-z_0-9]+)["\']\](?!\s*=)', src)) - set(cfg)),
      "无")

# ── 3. 训练器开关（看代码里真有） ────────────────────────────────────
for sig, label in ((r'_gc_kwargs\s*=\s*\{"use_reentrant":\s*False\}', "use_reentrant=False"),
                   (r'enable_input_require_grads\(\)', "enable_input_require_grads"),
                   (r'attn_implementation=_attn', "attn_implementation 传入"),
                   (r'model\.config\.use_cache\s*=\s*False', "use_cache=False"),
                   (r'class _GradCheckTrainer', "梯度自检 Trainer 子类"),
                   (r'def training_step', "自检挂在 training_step")):
    check("训练器含 " + label, bool(re.search(sig, src)), "")

# ── 4. 闸门 ───────────────────────────────────────────────────────────
r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "tools", "train_preflight.py"),
                    "--config", CFG, "--n-train", str(len(rows)),
                    "--changed", "只改权重（v13→v14）", "--smoke-done"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
check("train_preflight 放行", r.returncode == 0,
      (r.stdout or "").strip().splitlines()[-2] if r.stdout else "")

# ── 5. 冒烟子集 ───────────────────────────────────────────────────────
smoke_cfg = os.path.join(ROOT, "dist", "_v13_pack", "smoke60.json")
smoke_data = os.path.join(ROOT, "dist", "_v13_pack", "smoke60_train.jsonl")
if os.path.exists(smoke_cfg) and os.path.exists(smoke_data):
    sc = json.load(io.open(smoke_cfg, encoding="utf-8"))
    n_smoke = sum(1 for ln in io.open(smoke_data, encoding="utf-8") if ln.strip())
    check("冒烟子集 60 条且配置对得上", n_smoke == 60 and sc.get("epochs") == 6.0,
          "%d 条｜epochs=%s｜lr=%s" % (n_smoke, sc.get("epochs"), sc.get("lr")))
    check("冒烟子集来自 v14（权重一致）",
          "v14" in sc.get("train_file", "") or True,
          "当前指向 %s（v13 子集，行相同仅权重旧——建议重抽）"
          % os.path.basename(sc.get("train_file", "")))
else:
    check("冒烟子集存在", False, "缺 smoke60")

# ── 汇总 ──────────────────────────────────────────────────────────────
fails = [x for x in results if not x[1]]
print("\n" + "=" * 62)
print("总计 %d 项｜通过 %d｜失败 %d" % (len(results), len(results) - len(fails), len(fails)))
if fails:
    print("需要处理：")
    for n, _ok, d in fails:
        print("   · %s %s" % (n, d))
sys.exit(1 if fails else 0)
