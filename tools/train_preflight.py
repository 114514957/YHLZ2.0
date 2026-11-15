# -*- coding: utf-8 -*-
"""训练前置校验（台账 1211 的可执行版）。

为什么要有：老爹 2026-11-14 立规——训练注意事项要**每次训练前看一遍**。
光写在文档里没人执行，这个脚本把**能自动判定的硬规则**变成闸门：
违反就退出码 2，不许开训。

自动判定（有客观依据的）：
  · epochs ≤ 1（3 epoch 是灾难：25 vs 42）
  · batch×accum = 8（既定形状）
  · lr 在 1e-4..2.2e-4（5e-5 在我们数据上几乎不动）
  · 不允许 deepspeed
  · lr_scheduler_type / optim 必须显式（cosine / paged_adamw_8bit）
  · 4bit 训练必须 load_in_4bit=true
  · 数据量在 4000..12000（>13k 是负收益）
  · target_modules 必须含 7 类（q,k,v,o,gate,up,down）
  · 必须有 train_file 且存在

只提示不阻断（需要人来信）：
  · 冒烟测试做过没有
  · 这次只改了哪一个变量
  · 台账记了没有

用法：
    python tools/train_preflight.py --config dist/retrain_pkg_gemma_v11/config/finetune.gemma4.v11.json
    python tools/train_preflight.py --config <cfg> --n-train 5931 --changed "只改了数据量" --smoke-done
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

REQUIRED_MODULES = ("q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--n-train", type=int, default=0,
                    help="训练集条数（不给就按 config.train_file 数）")
    ap.add_argument("--changed", default="", help="这次只改了哪个变量")
    ap.add_argument("--smoke-done", action="store_true", help="冒烟测试已通过")
    a = ap.parse_args()

    p = a.config if os.path.isabs(a.config) else os.path.join(ROOT, a.config)
    if not os.path.exists(p):
        print("❌ 找不到配置：%s" % p)
        return 2
    cfg = json.load(io.open(p, encoding="utf-8-sig"))

    fails: list[str] = []
    warns: list[str] = []

    epochs = float(cfg.get("epochs") or 0)
    if epochs > 1.0001:
        fails.append("epochs=%s → 必须 ≤1（3 epoch 实测 25 分 vs 1 epoch 42 分）" % epochs)

    bs = int(cfg.get("batch_size") or 0)
    ga = int(cfg.get("grad_accum") or 0)
    if bs * ga != 8:
        fails.append("有效 batch = %d×%d = %d，必须是 8" % (bs, ga, bs * ga))

    lr = float(cfg.get("lr") or 0)
    if not (1e-4 <= lr <= 2.2e-4):
        fails.append("lr=%.6g 不在 1e-4..2.2e-4（5e-5 在我们数据上几乎不动）" % lr)

    if cfg.get("deepspeed"):
        fails.append("配置里有 deepspeed → 禁止（ZeRO-3 可能存半空 adapter）")

    if not cfg.get("lr_scheduler_type"):
        fails.append("lr_scheduler_type 为空 → 必须显式 cosine")
    elif "cosine" not in str(cfg.get("lr_scheduler_type")).lower():
        warns.append("lr_scheduler_type=%s（约定是 cosine）" % cfg.get("lr_scheduler_type"))

    if not cfg.get("optim"):
        fails.append("optim 为空 → 必须显式 paged_adamw_8bit")

    # target_modules 可能是 list，也可能是**正则字符串**（我们的配置就是字符串，
    # 例如 "model\\.language_model\\..*\\.(q_proj|k_proj|...)"）；两种都要认。
    _tm = cfg.get("target_modules")
    if isinstance(_tm, str):
        tm = _tm
    else:
        tm = " ".join(str(x) for x in (_tm or []))
    missing = [m for m in REQUIRED_MODULES if m not in tm]
    if missing:
        fails.append("target_modules 缺 %s（约定 7 类全挂）" % missing)

    if cfg.get("full_finetune"):
        warns.append("这是全参微调（qwen 期实测 29–35 分，低于 gemma LoRA）")

    tf = str(cfg.get("train_file") or "")
    n = a.n_train
    if tf:
        tp = tf if os.path.isabs(tf) else os.path.join(ROOT, tf)
        if not os.path.exists(tp):
            # 云端路径（/root/yh/...）在本机不存在：按"配置同级 + 包根目录"找同名文件
            base = os.path.basename(tf)
            for cand in (os.path.join(os.path.dirname(p), base),
                         os.path.join(os.path.dirname(os.path.dirname(p)), base)):
                if os.path.exists(cand):
                    tp = cand
                    break
        if os.path.exists(tp):
            if not n:
                n = sum(1 for ln in io.open(tp, encoding="utf-8", errors="replace")
                        if ln.strip())
        else:
            warns.append("train_file 不在本机：%s（云端路径，数据量未校验）" % tf)
    if n:
        if n > 12000:
            fails.append("训练集 %d 条 > 12000（实测 13189 条 → 44 分，低于 5931 条的 48 分）" % n)
        elif n < 4000:
            warns.append("训练集只有 %d 条（<4000，样本偏少）" % n)

    if not a.smoke_done:
        warns.append("没声明冒烟测试通过（60 条×6ep，三条判据）——建议先做")
    if not a.changed:
        warns.append("没说明『这次只改哪个变量』——一次改多个就无法归因（v11 的教训）")

    # ── 权重配比检查（2026-11-14 v13 事故后新增，台账 1222）──────────────
    # v13 工具题 16 道挂 13 道的真因：口述故事抢到 26.1% 权重，工具样本被稀释到 6.9%。
    # 只按"条数"看根本看不出来（836 条 vs 900 条，像没事一样），必须看**权重占比**。
    TOOL_MIN = 0.12        # 工具/格式类权重下限
    STORY_MAX = 0.18       # 口述/口味类权重上限
    ONE_MAX = 0.30         # 单来源上限
    if n and tf and os.path.exists(tp):
        import re as _re
        from collections import defaultdict as _dd
        agg = _dd(lambda: {"n": 0, "w": 0.0})
        tot_w = 0.0
        bad_rows = 0
        for ln in io.open(tp, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:  # noqa: BLE001
                bad_rows += 1
                continue
            ms = [m for m in (r.get("messages") or []) if isinstance(m, dict)]
            w = float(r.get("weight") or 1.0)
            tot_w += w
            src = str(r.get("source") or "")
            if any(m.get("tool_calls") for m in ms) or any(
                    m.get("role") == "tool" for m in ms):
                k = "tool"
            elif "story" in src.lower() or "故事" in src:
                k = "story"
            else:
                k = "other"
            agg[k]["n"] += 1
            agg[k]["w"] += w
        if tot_w > 0:
            tool_pct = agg["tool"]["w"] / tot_w
            story_pct = agg["story"]["w"] / tot_w
            print("\n权重配比：工具 %d 条 %.1f%%｜故事 %d 条 %.1f%%｜其余 %.1f%%"
                  % (agg["tool"]["n"], 100 * tool_pct,
                     agg["story"]["n"], 100 * story_pct,
                     100 * (1 - tool_pct - story_pct)))
            if tool_pct < TOOL_MIN:
                fails.append("工具/格式类权重仅 %.1f%% < %.0f%% —— "
                             "会让模型『用话糊过去』而不调工具（v13 就是这样挂掉 13 道工具题）"
                             % (100 * tool_pct, 100 * TOOL_MIN))
            if story_pct > STORY_MAX:
                fails.append("口述/口味类权重 %.1f%% > %.0f%% —— 会挤压格式与工具类"
                             % (100 * story_pct, 100 * STORY_MAX))
            # 单来源上限
            per_src = _dd(float)
            for ln in io.open(tp, encoding="utf-8", errors="replace"):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:  # noqa: BLE001
                    continue
                per_src[_re.split(r"[/:|]", str(r.get("source") or "?"))[0]] += \
                    float(r.get("weight") or 1.0)
            for src, w in per_src.items():
                if w / tot_w > ONE_MAX:
                    fails.append("来源 %s 占权重 %.1f%% > %.0f%%（单来源上限）"
                                 % (src, 100 * w / tot_w, 100 * ONE_MAX))
        if bad_rows:
            warns.append("训练集有 %d 行 JSON 解析失败（会被训练器跳过）" % bad_rows)

    print("配置：%s" % os.path.relpath(p, ROOT))
    print("epochs=%s｜batch=%d×%d｜lr=%s｜seq=%s｜r=%s｜4bit=%s｜数据 %s 条"
          % (epochs, bs, ga, lr, cfg.get("max_seq_len"), cfg.get("lora_r"),
             cfg.get("load_in_4bit"), n or "?"))

    if warns:
        print("\n⚠ 提醒（不阻断）")
        for w in warns:
            print("   · " + w)

    if fails:
        print("\n❌ 拒绝开训（违反硬规则）")
        for f in fails:
            print("   · " + f)
        print("\n依据：台账 1211《训练注意事项总表》｜docs/方案/训练注意事项_必读.md")
        return 2

    print("\n✅ 硬规则全部通过。别忘：先冒烟 → 单变量 → 转 GGUF → 56+28 双跑 → 记账。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
