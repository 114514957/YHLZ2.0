#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按"角色一致性"清掉开源对话素材里元亨不能说的话。

老爹 2026-10-21 抽样检查发现的真问题：这批素材**客服腔达标（0.21%）但角色穿帮 14.4%**——
「我在河北读书」「快来上海找我玩」「你还可以追我」这类会让元亨编造经历。

规则（**只查元亨那侧**，老爹可以有城市/学校/工作/家人）：
  地名 / 学校职业 / 恋爱语境 / 实体动作 / 第三方名字 / 平台用语

用法：
    python tools/v9_role_clean.py --in docs/素材/开源对话样本.md --dry-run
    python tools/v9_role_clean.py --in docs/素材/开源对话样本.md
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CITY = re.compile(r"北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|郑州|河北|"
                  r"湖南|湖北|广东|江苏|浙江|山东|四川|河南|安徽|福建|江西|"
                  r"南宁|昆明|贵阳|兰州|太原|石家庄|合肥|长沙|青岛|大连|厦门|"
                  r"苏州|无锡|宁波|温州|东莞|佛山")
JOB = re.compile(r"上课|下课|逃课|考试周|期末考|论文|导师|宿舍|室友|食堂|同学|"
                 r"班上|学校|读书|毕业|实习|上班|加班|老板|同事|公司|工位|"
                 r"月薪|工资|辞职|失业|面试|简历|工牌")
LOVE = re.compile(r"追我|追你|喜欢我|我爱你|前任|分手|表白|在一起|结婚|"
                  r"男朋友|女朋友|老公|老婆|男票|女票|娶|嫁")
PLATFORM = re.compile(r"翻牌|取关|转发|评论区|热搜|话题|超话|私信|楼上|楼下|"
                      r"楼主|博主|弹幕|点赞|围观|圈你")
PHYSICAL = re.compile(r"来找我|来找你|跨城|一起去|带我|见你|见面|抱抱|亲亲|"
                      r"摸头|牵手|坐我旁边|给我带|送我|寄给")
THIRD = re.compile(r"游游|瓜瓜|美宝宝")
RULES = (("地名", CITY), ("学校职业", JOB), ("恋爱", LOVE),
         ("平台用语", PLATFORM), ("实体动作", PHYSICAL), ("第三方名字", THIRD))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = io.open(a.inp, encoding="utf-8").read()
    m = re.search(r"(?ms)^(.*?)(?=^## )", text)
    head = m.group(1) if m else ""
    blks = re.split(r"(?m)^## ", text)[1:]

    keep, drop, cnt = [], [], Counter()
    for b in blks:
        blk = "## " + b
        role, ys = None, []
        for ln in b.split("\n"):
            s = ln.strip()
            if s.startswith("### "):
                role = "老爹" if "问" in s else "元亨"
            elif s and not s.startswith(("#", "-")) and role == "元亨":
                ys.append(s)
        joined = "".join(ys)
        hit = None
        for name, pat in RULES:
            mm = pat.search(joined)
            if mm:
                hit = (name, mm.group(0))
                break
        if hit:
            cnt[hit[0]] += 1
            drop.append((blk, hit))
        else:
            keep.append(blk)

    print("%s ｜%d 块 → 保留 %d｜剔除 %d（%.1f%%）"
          % (os.path.basename(a.inp), len(blks), len(keep), len(drop),
             100.0 * len(drop) / max(1, len(blks))))
    for k, v in cnt.most_common():
        print("   %-10s %4d" % (k, v))
    if a.dry_run:
        for blk, (name, w) in drop[:8]:
            turns = [x for x in blk.split("\n") if x.strip()
                     and not x.startswith(("#", "-"))]
            print("   [%s:%s] %s" % (name, w, " ｜ ".join(turns)[:78]))
        return 0

    bak = os.path.join(ROOT, "cache", "backup_dialogue",
                       os.path.basename(a.inp).replace(".md", "_角色清理前.md"))
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(a.inp, bak)
    new_head = head.replace(
        "> **通过者的台词一字未改**",
        "> **通过者的台词一字未改**（2026-10-21 追加第四道「角色一致性」筛："
        "剔除元亨不该有的地名/学校职业/恋爱/实体动作，共剔 %d 块）" % len(drop))
    with io.open(a.inp, "w", encoding="utf-8") as fh:
        fh.write(new_head)
        for b in keep:
            fh.write("\n" + b.rstrip() + "\n\n")
    print("已写回 %s（备份 %s）" % (a.inp, os.path.relpath(bak, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
