# -*- coding: utf-8 -*-
"""量一下：改完提示词后，她对脏话/荤话还切不切道德挡板。"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
sys.path.insert(0, os.path.join(YH, "llm_workbench"))
sys.path.insert(0, os.path.join(YH, "tools"))

import evals  # noqa: E402
import group_bank as GB  # noqa: E402

print("群聊题 %d 道｜闸门 %s" % (len(GB.GROUP_BANK),
                             [e["id"] for e in GB.GROUP_BANK if e.get("gate")]))
pub = evals._public_system()
print("群聊提示词 %d 字" % len(pub))
print("含「保持礼貌」类禁令？%s" % any(x in pub for x in ("保持礼貌", "注意言辞", "请文明")))
print("含「听得懂」放开条款？%s" % ("听得懂" in pub))
print("含「不用脏话」？%s" % ("不用脏话" in pub))
