# -*- coding: utf-8 -*-
"""工作台「提示词历史」卡：列快照 + 一键回滚（整份或单块）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

CARD = """
          <div class="card" id="pv-card">
            <h3>提示词历史 <small style="font-weight:400;opacity:.6">改坏了能回去</small></h3>
            <div style="margin-bottom:6px">
              <button id="pv-snap" type="button" style="padding:4px 10px;border-radius:6px;cursor:pointer">现在存一份</button>
              <span id="pv-msg" style="font-size:12px;opacity:.7;margin-left:8px"></span>
            </div>
            <div id="pv-list" style="font-size:12px;line-height:1.8;max-height:220px;overflow:auto"></div>
          </div>
"""

if 'id="pv-card"' not in t:
    anchor = '<div class="card" id="eval-card">'
    assert anchor in t
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 提示词历史（台账 1256）：GET /api/prompt_versions + POST /api/prompt_restore */
(function () {
  function msg(s) { var m = document.getElementById("pv-msg"); if (m) m.textContent = s; }
  function render(d) {
    var box = document.getElementById("pv-list");
    if (!box) return;
    var vs = (d && d.versions) || [];
    if (!vs.length) { box.textContent = "还没有快照（保存一次提示词就会有）"; return; }
    box.innerHTML = vs.map(function (v) {
      return "<div>" + v.ts
        + "　<span style='opacity:.65'>" + (v.key || "(整份)") + "</span>"
        + "　<span style='opacity:.5'>" + (v.note || "") + "</span>"
        + "　<button data-ts='" + v.ts + "' data-key='" + (v.key || "") + "' class='pv-restore'"
        + " style='padding:2px 8px;border-radius:5px;cursor:pointer'>回滚</button></div>";
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll(".pv-restore"), function (b) {
      b.addEventListener("click", function () {
        var ts = b.getAttribute("data-ts"), key = b.getAttribute("data-key");
        if (!confirm("回滚到 " + ts + (key ? (" 的 " + key) : " 的整份配置") + "？")) return;
        fetch("/api/prompt_restore", {method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({ts: ts, key: key})})
          .then(function (r) { return r.json(); })
          .then(function (x) { msg(x.ok ? ("已回滚 " + ts) : ("失败：" + (x.error || ""))); load(); })
          .catch(function (e) { msg("失败：" + e); });
      });
    });
  }
  function load() {
    fetch("/api/prompt_versions", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(render).catch(function () {});
  }
  function snap() {
    fetch("/api/prompt_snapshot", {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({key: ""})})
      .then(function (r) { return r.json(); })
      .then(function (x) { msg(x.ok ? ("已存 " + x.ts) : "存失败"); load(); })
      .catch(function (e) { msg("失败：" + e); });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var s = document.getElementById("pv-snap");
    if (s) s.addEventListener("click", snap);
    load(); setInterval(load, 30000);
  });
})();
</script>
"""
if "/api/prompt_versions" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("已加提示词历史卡")
