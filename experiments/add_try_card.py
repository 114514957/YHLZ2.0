# -*- coding: utf-8 -*-
"""工作台「试一句话」卡（前端）：文本 + 按钮 + 回复 + 耗时/token/费用。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

CARD = """
          <div class="card" id="try-card">
            <h3>试一句话 <small style="font-weight:400;opacity:.6">走生产同款路径</small></h3>
            <div style="display:flex;gap:6px;margin-bottom:6px">
              <input id="try-in" type="text" placeholder="比如：你还记得我不吃香菜吗"
                     style="flex:1;padding:6px 8px;border-radius:6px;border:1px solid #444;background:#1b1b1b;color:#eee">
              <button id="try-go" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">发</button>
            </div>
            <div id="try-meta" style="font-size:12px;opacity:.75;margin-bottom:4px"></div>
            <div id="try-out" style="font-size:13px;line-height:1.6;white-space:pre-wrap;min-height:20px"></div>
          </div>
"""

if 'id="try-card"' not in t:
    anchor = '<div class="card" id="stack-card">'
    assert anchor in t, "找不到插入点"
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 「试一句话」（台账 1250/1254）：POST /api/try_turn，显示回复与 token/费用。 */
(function () {
  function run() {
    var inp = document.getElementById("try-in");
    var out = document.getElementById("try-out");
    var meta = document.getElementById("try-meta");
    var btn = document.getElementById("try-go");
    var text = (inp && inp.value || "").trim();
    if (!text) return;
    btn.disabled = true; btn.textContent = "…";
    out.textContent = ""; meta.textContent = "发送中（大模型约 3–15 秒）";
    fetch("/api/try_turn", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: text})
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.ok) {
        out.textContent = "❌ " + ((d && d.error) || "失败");
        meta.textContent = "";
        return;
      }
      out.textContent = d.reply || "（空回复）";
      meta.textContent = [
        (d.model || "") + "｜" + Math.round(d.ms || 0) + " ms",
        "in " + (d.tokens_in || 0) + " / out " + (d.tokens_out || 0),
        "¥" + (d.cost || 0),
        (d.tools && d.tools.length) ? ("工具:" + d.tools.join(",")) : ""
      ].filter(Boolean).join("｜");
    }).catch(function (e) {
      out.textContent = "❌ " + e;
    }).then(function () {
      btn.disabled = false; btn.textContent = "发";
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("try-go");
    var inp = document.getElementById("try-in");
    if (btn) btn.addEventListener("click", run);
    if (inp) inp.addEventListener("keydown", function (e) {
      if (e.key === "Enter") run();
    });
  });
})();
</script>
"""

if "/api/try_turn" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)

io.open(P, "w", encoding="utf-8").write(t)
print("已加「试一句话」卡与脚本")
