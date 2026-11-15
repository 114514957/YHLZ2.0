# -*- coding: utf-8 -*-
"""形象区（台账 1261）：把 Live2D 皮套嵌进工作站首屏，另留「新窗口打开」。

老爹定论（1230）：「形象按原来的那样继续」+「两边都留」——
所以这里只是**嵌入一份**，原 `avatar.html` 独立窗口照旧。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

CARD = """
          <div class="card" id="avatar-card">
            <h3>形象 <small style="font-weight:400;opacity:.6">2D 皮套（独立窗口照旧）</small></h3>
            <div style="display:flex;gap:10px;align-items:flex-start">
              <iframe src="/avatar.html" title="元亨形象" loading="lazy"
                      style="width:320px;height:220px;border:1px solid #333;border-radius:8px;background:#111"></iframe>
              <div style="font-size:12px;line-height:1.8;opacity:.85">
                <div>这里嵌的是同一份 Live2D 页面。</div>
                <div style="margin-top:6px">
                  <a href="/avatar.html" target="_blank" rel="noopener"
                     style="color:#3498db">在新窗口打开 ↗</a>
                </div>
                <div style="margin-top:6px;opacity:.65">
                  模型/背景沿用原设置，不在工作站里改。
                </div>
              </div>
            </div>
          </div>
"""

if 'id="avatar-card"' not in t:
    anchor = '<section class="panel on" data-panel="status">'
    assert anchor in t
    t = t.replace(anchor, anchor + CARD, 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("形象卡已加")
else:
    print("形象卡已存在")

# 验证
t2 = io.open(P, encoding="utf-8").read()
for k in ("avatar-card", "/avatar.html", "在新窗口打开"):
    print("  %-14s %s" % (k, "✅" if k in t2 else "❌"))
