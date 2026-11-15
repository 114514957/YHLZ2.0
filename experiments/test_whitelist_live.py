# -*- coding: utf-8 -*-
"""验：工作台写入白名单后，桥的 _allowed_groups() 是否立刻读到。

做法：临时写入 1 个群 → 调桥的函数 → 恢复空列表。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, YH)

from backend import qq_group_admin as A  # noqa: E402

CFG = os.path.join(YH, "config", "qq_groups_whitelist.json")


def bridge_allowed():
    import importlib.util
    spec = importlib.util.spec_from_file_location("qb", os.path.join(YH, "tools", "qq_bot.py"))
    # 不整份导入（会连带跑主程序的副作用），只把函数抠出来：
    import re
    src = open(os.path.join(YH, "tools", "qq_bot.py"), encoding="utf-8").read()
    m = re.search(r"^def _allowed_groups\(\):.*?(?=^def |^_SILENCE_RE)", src, re.S | re.M)
    if not m:
        raise SystemExit("抠不出 _allowed_groups")
    ns = {"os": os, "re": re, "__name__": "qb"}
    exec(compile(m.group(0), "qq_bot._allowed_groups", "exec"), ns)
    return ns["_allowed_groups"]()


print("① 当前（空列表）→", bridge_allowed())

print("\n② 临时写入 [855372167]")
A.set_whitelist(["855372167"])
print("   文件：", json.load(open(CFG, encoding="utf-8"))["groups"])
print("   桥读到 →", bridge_allowed())

print("\n③ 恢复空列表")
A.set_whitelist([])
print("   文件：", json.load(open(CFG, encoding="utf-8"))["groups"])
print("   桥读到 →", bridge_allowed())

print("\n④ 环境变量优先验证")
os.environ["YHLZ_QQ_GROUPS"] = "111,222"
print("   env=111,222 且文件为空 →", bridge_allowed())
del os.environ["YHLZ_QQ_GROUPS"]
