#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LCCC（MIT）真实中文对话 → 元亨素材（老爹：「直接用可用的原话」）。

LCCC = 2,667,000 条微博对话，**分词带空格**，需先去空格恢复自然中文。
本轮只做三件事，**台词一字不改**：
  ① 去分词空格    ② 按质量规则筛（下面 QUALITY）    ③ 交替映射为 老爹问N / 元亨答N

质量规则（全是否决式，任一条不过就丢）：
  · 轮数 3–8（1–2 轮没来回，>8 轮冗长且常跑题）
  · 每轮 2–80 字；总字数 24–500
  · 排除 URL / @提及 / #话题# / 纯数字表情 / 电话号码 / 二维码话术
  · 排除广告与营销词（签到|会员|优惠|包邮|下载|链接|扫码|加群|代理|刷单…）
  · 排除含 `[` `]` 微博表情占位、含英文长串（>6 连续字母）
  · 跨条去重（整段归一化后比较）

用法：
    python tools/v9_lccc_to_material.py --limit 1200
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import v9_story_gate as G  # noqa: E402

P = os.path.join(ROOT, "cache", "v9_open_corpus", "20261020_hf", "lccc_train0.parquet")
OUT = os.path.join(ROOT, "docs", "素材", "开源对话样本.md")

AD = re.compile(r"签到|会员|优惠|包邮|下载|链接|扫码|加群|代理|刷单|返现|优惠券|"
                r"充值|客服|价格|多少钱|店铺|淘宝|京东|拼多多|直播|直播间|"
                r"二维码|公众号|转发抽奖|点赞|关注我")
JUNK = re.compile(r"https?://|@[\w\u4e00-\u9fff]|#[\w\u4e00-\u9fff]+#|"
                  r"\d{5,}|\[[^\]]{1,6}\]")
PUNCT = "，。！？、；：""''（）《》…—~"


def deseg(t: str) -> str:
    """去 LCCC 分词空格，恢复自然中文。"""
    s = str(t).strip()
    s = re.sub(r"\s*([" + re.escape(PUNCT) + r"])\s*", r"\1", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def good_turn(t: str) -> bool:
    n = len(t)
    if n < 2 or n > 80:
        return False
    if JUNK.search(t) or AD.search(t):
        return False
    if re.search(r"[a-zA-Z]{7,}", t):
        return False
    if not re.search(r"[\u4e00-\u9fff]", t):
        return False
    # 至少一半是中文
    zh = len(re.findall(r"[\u4e00-\u9fff]", t))
    if zh / max(1, n) < 0.5:
        return False
    return True


def main() -> int:
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1200, help="想要多少块")
    ap.add_argument("--max-scan", type=int, default=400000, help="最多扫多少条原始对话")
    ap.add_argument("--pair-all", action="store_true",
                    help="3 轮也凑成 2 轮（默认丢弃奇数轮）")
    a = ap.parse_args()

    df = pd.read_parquet(P)
    print("原始对话 %d 条" % len(df))
    blocks, seen, stat = [], set(), {}
    scanned = 0
    for raw in df["dialog"].tolist():
        if len(blocks) >= a.limit or scanned >= a.max_scan:
            break
        scanned += 1
        turns = [deseg(x) for x in raw]
        turns = [t for t in turns if t]
        if not (3 <= len(turns) <= 8):
            stat["轮数不合适"] = stat.get("轮数不合适", 0) + 1
            continue
        if not all(good_turn(t) for t in turns):
            stat["单轮不合格"] = stat.get("单轮不合格", 0) + 1
            continue
        total = sum(len(t) for t in turns)
        if not (24 <= total <= 500):
            stat["总长不合适"] = stat.get("总长不合适", 0) + 1
            continue
        key = re.sub(r"\s+", "", "".join(turns))
        if key in seen:
            stat["重复"] = stat.get("重复", 0) + 1
            continue
        seen.add(key)
        # 交替映射：偶数位=老爹，奇数位=元亨；奇数轮丢弃最后一轮
        pairs = [(turns[i], turns[i + 1]) for i in range(0, len(turns) - 1, 2)]
        if not pairs:
            continue
        name = "lccc-%04d" % (len(blocks) + 1)
        meta = ("## %s\n- category: 日常对话\n- emotion: neutral\n"
                "- length_tier: %s\n- contract: ANCHOR\n"
                "- source: LCCC(silver/lccc)\n- license: MIT\n- polish: none\n"
                % (name, "short" if total <= 80 else "medium"))
        body = []
        for i, (q, r) in enumerate(pairs, 1):
            body.append("### 老爹问%d" % i)
            body.append(q)
            body.append("### 元亨答%d" % i)
            body.append(r)
        blk = meta + "\n".join(body) + "\n"
        rr = G.check_block(name, blk, "general")
        if rr["status"] == "FAIL":
            for f in rr["fails"]:
                k = "门禁:" + re.sub(r"×\d+", "", f).split(":")[0].strip()
                stat[k] = stat.get(k, 0) + 1
            continue
        blocks.append(blk)

    print("扫 %d 条 → 收货 %d 块" % (scanned, len(blocks)))
    print("丢弃原因：%s" % dict(sorted(stat.items(), key=lambda kv: -kv[1])[:8]))
    if not blocks:
        return 1

    head = ("# 元亨开源对话样本（LCCC 原话直采 · MIT）\n\n"
            "> **老爹 2026-10-20 定：不再生成，直接用可用的原话。**\n"
            "> 来源 `silver/lccc`（LCCC，**MIT**），2,667,000 条微博真实对话；本批取 %d 块。\n"
            "> **台词一字未改**，只做：去分词空格、按质量规则筛、交替映射为对话、过门禁（FAIL 不收）。\n"
            "> 采集脚本 `tools/v9_lccc_to_material.py`。\n\n" % len(blocks))
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write(head)
        for b in blocks:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写 -> %s" % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
