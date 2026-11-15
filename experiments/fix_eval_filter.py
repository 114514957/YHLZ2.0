# -*- coding: utf-8 -*-
"""过滤非评测文件（cache/eval_state.json 混进了 tags/history）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# eval_compare.tags：加 detail 校验
P1 = os.path.join(ROOT, "backend", "eval_compare.py")
t1 = io.open(P1, encoding="utf-8").read()
old1 = """        try:
            d = json.loads(io.open(p, encoding="utf-8").read())
            per = d.get("detail", {}).get("persona", [])"""
new1 = """        try:
            d = json.loads(io.open(p, encoding="utf-8").read())
            if not isinstance(d.get("detail"), dict):
                continue          # eval_state.json 之类不是评测结果
            per = d.get("detail", {}).get("persona", [])"""
if old1 in t1:
    t1 = t1.replace(old1, new1, 1)
    io.open(P1, "w", encoding="utf-8").write(t1)
    print("eval_compare 已过滤")
else:
    print("eval_compare 无需改")

# eval_runner.history：同样过滤
P2 = os.path.join(ROOT, "backend", "eval_runner.py")
t2 = io.open(P2, encoding="utf-8").read()
old2 = """        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            per = d.get("detail", {}).get("persona", [])"""
new2 = """        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d.get("detail"), dict):
                continue
            per = d.get("detail", {}).get("persona", [])"""
if old2 in t2:
    t2 = t2.replace(old2, new2, 1)
    io.open(P2, "w", encoding="utf-8").write(t2)
    print("eval_runner 已过滤")
else:
    print("eval_runner 无需改")
