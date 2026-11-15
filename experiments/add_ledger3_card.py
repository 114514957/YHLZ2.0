# -*- coding: utf-8 -*-
"""工作台「台账」页：三本分开（元亨橙 / 项目蓝 / 日记紫），默认只看元亨台账。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

CARD = """
          <div class="card" id="ledger3-card">
            <h3>台账 <small style="font-weight:400;opacity:.6">三本分开，不混排</small></h3>
            <div style="margin-bottom:8px">
              <button class="l3-tab" data-v="her" type="button" style="padding:5px 12px;border-radius:6px;cursor:pointer;border:1px solid #e67e22">元亨台账</button>
              <button class="l3-tab" data-v="project" type="button" style="padding:5px 12px;border-radius:6px;cursor:pointer;border:1px solid #3498db">项目台账</button>
              <button class="l3-tab" data-v="diary" type="button" style="padding:5px 12px;border-radius:6px;cursor:pointer;border:1px solid #9b59b6">日记</button>
              <label style="font-size:12px;margin-left:10px;opacity:.8">
                <input type="checkbox" id="l3-onlyher"> 只看元亨相关
              </label>
              <span id="l3-msg" style="font-size:12px;opacity:.7;margin-left:8px"></span>
            </div>
            <div id="l3-body" style="font-size:12px;line-height:1.75;max-height:320px;overflow:auto"></div>
          </div>
"""

if 'id="ledger3-card"' not in t:
    anchor = '<section class="panel" data-panel="ledger">'
    assert anchor in t
    # 插到 ledger 面板的第一个 card 之前
    i = t.find(anchor) + len(anchor)
    j = t.find('<div class="card">', i)
    assert j > i
    t = t[:j] + CARD + "\n          " + t[j:]

JS = """
<script>
/* 台账分家（台账 1258）：三本独立视图 */
(function () {
  var cur = "her";
  function msg(s) { var m = document.getElementById("l3-msg"); if (m) m.textContent = s; }
  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
  function paint(html) {
    var b = document.getElementById("l3-body");
    if (b) b.innerHTML = html;
  }
  function renderHer(d) {
    var color = "#e67e22";
    var html = "";
    Object.keys(d.parts || {}).forEach(function (k) {
      var p = d.parts[k];
      html += "<div style='margin-bottom:8px;border-left:3px solid " + color + ";padding-left:8px'>"
        + "<b>" + k + "</b>　<span style='opacity:.6'>" + (p.chars || 0) + " 字节</span>";
      (p.blocks || []).forEach(function (b) {
        html += "<div style='margin-top:4px'><span style='opacity:.75'>" + esc(b.title) + "</span>"
          + "<div style='white-space:pre-wrap'>" + esc((b.text || "").slice(0, 400)) + "</div></div>";
      });
      html += "</div>";
    });
    return html || "（没有内容）";
  }
  function renderDiary(d) {
    var color = "#9b59b6";
    var html = "<div style='opacity:.7'>" + d.chars + " 字（日记单独存，不并进元亨台账）</div>";
    (d.blocks || []).forEach(function (b) {
      html += "<div style='margin-top:8px;border-left:3px solid " + color + ";padding-left:8px'>"
        + "<b>" + esc(b.title) + "</b><div style='white-space:pre-wrap'>"
        + esc((b.text || "").slice(0, 800)) + "</div></div>";
    });
    return html || "（还没有日记）";
  }
  function renderProject(d) {
    var color = "#3498db";
    var html = "<div style='opacity:.7'>共 " + d.total + " 条｜元亨相关 " + d.her_tagged
      + " 条" + (d.offset ? ("｜第 " + (d.offset + 1) + " 起") : "") + "</div>";
    (d.items || []).forEach(function (it) {
      html += "<div style='margin-top:8px;border-left:3px solid " + color + ";padding-left:8px'>"
        + "<b>" + esc(it.title) + "</b><div style='white-space:pre-wrap;opacity:.85'>"
        + esc((it.text || "").slice(0, 500)) + "</div></div>";
    });
    return html || "（没有条目）";
  }
  function load(v) {
    cur = v || cur;
    Array.prototype.forEach.call(document.querySelectorAll(".l3-tab"), function (b) {
      b.style.opacity = (b.getAttribute("data-v") === cur) ? "1" : ".55";
    });
    var only = document.getElementById("l3-onlyher");
    var url = cur === "her" ? "/api/ledger_her?limit=4"
      : cur === "diary" ? "/api/ledger_diary?limit=6"
      : ("/api/ledger_project?limit=6" + (only && only.checked ? "&only_her=1" : ""));
    msg("加载中…");
    fetch(url, {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) { paint("取不到：" + ((d && d.error) || "")); msg(""); return; }
        paint(cur === "her" ? renderHer(d) : cur === "diary" ? renderDiary(d) : renderProject(d));
        msg("");
      }).catch(function (e) { paint("失败：" + e); msg(""); });
  }
  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".l3-tab"), function (b) {
      b.addEventListener("click", function () { load(b.getAttribute("data-v")); });
    });
    var only = document.getElementById("l3-onlyher");
    if (only) only.addEventListener("change", function () { if (cur === "project") load("project"); });
    load("her");
  });
})();
</script>
"""
if "ledger3-card" in t and "/api/ledger_her" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("已加台账三分卡")
