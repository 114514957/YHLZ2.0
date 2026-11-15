# -*- coding: utf-8 -*-
"""验群列表接口：能拿到元亨号加入的群吗。"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")

from backend import qq_group_admin as A  # noqa: E402

r = A.list_groups()
print("ok=%s｜群数=%s" % (r.get("ok"), r.get("count")))
if not r.get("ok"):
    print("错误：%s" % r.get("error"))
for g in r.get("groups", []):
    mark = "★" if g["id"] in (r.get("whitelist", {}).get("groups") or []) else " "
    print("  %s %-14s %-28s %s 人" % (mark, g["id"], g["name"][:28], g["count"]))
print("\n当前白名单：%s" % json.dumps(r.get("whitelist"), ensure_ascii=False))
