# -*- coding: utf-8 -*-
"""核对：滑窗图案 / 全局层数 / 我们的提示词与上下文长度 vs 512 窗口。"""
from __future__ import annotations

import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
GG = os.path.join(ROOT, "models", "gemma4-gguf", "gemma-4-E4B_q4_0-it.gguf")


def gguf_kv(path):
    with open(path, "rb") as f:
        f.read(4)
        struct.unpack("<I", f.read(4))
        struct.unpack("<Q", f.read(8))
        n_kv = struct.unpack("<Q", f.read(8))[0]

        def rs():
            n = struct.unpack("<Q", f.read(8))[0]
            return f.read(n).decode("utf-8", "replace")

        def rv(t):
            if t == 0: return struct.unpack("<B", f.read(1))[0]
            if t == 1: return struct.unpack("<b", f.read(1))[0]
            if t == 2: return struct.unpack("<H", f.read(2))[0]
            if t == 3: return struct.unpack("<h", f.read(2))[0]
            if t == 4: return struct.unpack("<I", f.read(4))[0]
            if t == 5: return struct.unpack("<i", f.read(4))[0]
            if t == 6: return struct.unpack("<f", f.read(4))[0]
            if t == 7: return bool(struct.unpack("<B", f.read(1))[0])
            if t == 8: return rs()
            if t == 9:
                et = struct.unpack("<I", f.read(4))[0]
                n = struct.unpack("<Q", f.read(8))[0]
                return [rv(et) for _ in range(n)]
            if t == 10: return struct.unpack("<Q", f.read(8))[0]
            if t == 11: return struct.unpack("<q", f.read(8))[0]
            if t == 12: return struct.unpack("<d", f.read(8))[0]
            raise ValueError(t)

        m = {}
        for _ in range(n_kv):
            k = rs()
            t = struct.unpack("<I", f.read(4))[0]
            m[k] = rv(t)
        return m


m = gguf_kv(GG)
pat = m.get("gemma4.attention.sliding_window_pattern") or []
n = len(pat)
glob = sum(1 for p in pat if not p)
print("层数 %d｜滑窗层 %d｜全局层 %d" % (n, n - glob, glob))
print("滑窗窗口 = %s" % m.get("gemma4.attention.sliding_window"))
print("图案前 18 层：%s" % "".join("S" if p else "G" for p in pat[:18]))
print("（S=sliding 512 窗口，G=global 全可见）")

print("\n=== 我们的实际长度 vs 512 窗口 ===")
sys.path.insert(0, ROOT)
from backend import prompt_overrides as PO  # noqa: E402
for pub in (False, True):
    p = PO.preview(pub)
    tok = p["approx_tokens"]
    print("   %s提示词：%d 字 ≈ %d token → 是 512 窗口的 %.1f 倍"
          % ("群聊" if pub else "私聊", p["chars"], tok, tok / 512))
    print("     → 滑窗层（%d/%d）只能看到最后约 512 token，**开头的人设条款它们看不见**"
          % (n - glob, n))
    print("     → 只有 %d 个全局层能看到完整提示词" % glob)
