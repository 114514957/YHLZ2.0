# -*- coding: utf-8 -*-
"""工作台「群情报」卡（前端）：每个群一行 + Top 成员。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

CARD = """
          <div class="card" id="intel-card">
            <h3>群情报 <small style="font-weight:400;opacity:.6">人多，活跃的少</small></h3>
            <div id="intel-body" style="font-size:12px;line-height:1.7">加载中…</div>
          </div>
"""

if 'id="intel-card"' not in t:
    anchor = '<div class="card" id="try-card">'
    assert anchor in t
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 群情报卡（台账 1253）：GET /api/qq_intel */
(function () {
  function render(d) {
    var box = document.getElementById("intel-body");
    if (!box) return;
    if (!d || !d.ok || !(d.cards || []).length) {
      box.textContent = "没有群数据";
      return;
    }
    box.innerHTML = d.cards.map(function (c) {
      var nm = (d.names || {})[c.group_id] || c.group_id;
      var tops = (c.members || []).slice(0, 3).map(function (m) {
        return m.name + "(" + m.messages + ")";
      }).join("、");
      return "<div style='margin-bottom:8px'>"
        + "<b>" + nm + "</b>　" + c.people + "人（活跃 " + c.active_people + "）"
        + "｜" + c.messages + " 条｜近7天 " + c.messages_recent_7d
        + "<br><span style='opacity:.75'>话题：" + (c.topics || []).join("/") + "</span>"
        + "<br><span style='opacity:.9'>主力：" + tops + "</span></div>";
    }).join("");
  }
  function load() {
    fetch("/api/qq_intel", {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(render).catch(function () {});
  }
  document.addEventListener("DOMContentLoaded", function () {
    load();
    setInterval(load, 60000);
  });
})();
</script>
"""

if "/api/qq_intel" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)

io.open(P, "w", encoding="utf-8").write(t)
print("已加「群情报」卡")
