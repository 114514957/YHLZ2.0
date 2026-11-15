# -*- coding: utf-8 -*-
"""解 .9.note：看是不是同一篇的富文本，有没有额外内容。"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\_inbox\note9\.9.note"
raw = open(P, "rb").read()
print("字节 %d｜头 32 字节：%s" % (len(raw), raw[:32].hex()))

for enc in ("utf-8", "utf-16-le", "utf-16-be", "gbk"):
    try:
        t = raw.decode(enc, errors="strict")
        print("\n按 %s 解码成功，长度 %d" % (enc, len(t)))
        body = re.sub(r"<[^>]+>", " ", t)
        body = re.sub(r"\s+", " ", body).strip()
        print("去标签后 %d 字，前 600 字：" % len(body))
        print(body[:600])
        break
    except Exception as ex:  # noqa: BLE001
        print("  %s 失败：%s" % (enc, type(ex).__name__))

# 尽力抽中文
zh = re.findall(r"[\u4e00-\u9fff，。！？、；：""''（）]{6,}", raw.decode("utf-8", "ignore"))
print("\n从原始字节里捞出 %d 段中文，前 10 段：" % len(zh))
for s in zh[:10]:
    print("   %s" % s[:70])
