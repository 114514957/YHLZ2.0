# -*- coding: utf-8 -*-
"""给 1022 条记忆分类：多少是"工程流水账"、多少是"她该记得的事"。"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
con = sqlite3.connect(os.path.join(ROOT, "cache", "memstore", "memstore.db"))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    "select id,type,importance,summary,source,evidence_ref,created_at,access_count "
    "from l2_items").fetchall()]

ENG = re.compile(r"(台账|记录 ?0\d{3}|记录 ?1\d{3}|用户决策|用户要求|本轮依据|链路|验收|探针|"
                 r"冻结|Provider|测试证据|只动目标|工作流|架构|重构|部署|日志|接口|配置|端口|"
                 r"数据库|脚本|编译|CPU|GPU|显存|模型|训练|LoRA|数据集|评测)")
LIFE = re.compile(r"(老爹|元亨|利贞|喜欢|讨厌|怕|冷|睡|累|心情|感觉|记得|想|家|日记|故事|"
                  r"名字|生日|习惯|口头禅|发火|哄|陪)")
TALK = re.compile(r"元亨[:：]")

cat = Counter()
samples = {}
for r in rows:
    t = str(r["summary"] or "")
    eng = len(ENG.findall(t))
    life = len(LIFE.findall(t))
    if TALK.search(t):
        k = "她的群聊原话"
    elif eng >= 2 and life == 0:
        k = "工程流水账"
    elif life >= 2 and eng == 0:
        k = "生活/关系/偏好"
    elif eng >= 2 and life >= 2:
        k = "混合"
    else:
        k = "其它/中性"
    cat[k] += 1
    samples.setdefault(k, []).append(t[:90])

print("=== 1022 条记忆的实际构成 ===")
for k, v in cat.most_common():
    print("   %-14s %4d 条（%.1f%%）" % (k, v, 100 * v / len(rows)))
print()
for k in cat:
    print("--- %s 样例 ---" % k)
    for s in samples[k][:3]:
        print("   · " + s)
    print()

print("=== 结论用的三个硬数 ===")
print("   access_count>0 的条目：%d（说明从未被检索计数写回）"
      % sum(1 for r in rows if (r["access_count"] or 0) > 0))
print("   source 为空：%d 条" % sum(1 for r in rows if not str(r["source"] or "").strip()))
print("   '工程流水账' 占比：%.1f%%" % (100 * cat["工程流水账"] / len(rows)))
con.close()
