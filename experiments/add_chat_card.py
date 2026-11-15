# -*- coding: utf-8 -*-
"""工作台「对话台」：多会话（列表 + 切换 + 新建）+ 对话记录 + 发送。

复用既有接口，不新造轮子：
  GET  /sessions        会话列表
  GET  /history?session= 某会话消息
  POST /talk            发送（SSE；这里整段读完再渲染，简单可靠）
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
          <div class="card" id="chat-card">
            <h3>对话台 <small style="font-weight:400;opacity:.6">多会话 · 与 QQ 同一条链路</small></h3>
            <div style="display:flex;gap:8px;align-items:flex-start">
              <div id="ch-list" style="width:180px;max-height:300px;overflow:auto;font-size:12px;line-height:1.7"></div>
              <div style="flex:1">
                <div id="ch-body" style="font-size:13px;line-height:1.65;max-height:260px;overflow:auto;white-space:pre-wrap;border:1px solid #333;border-radius:8px;padding:8px"></div>
                <div style="display:flex;gap:6px;margin-top:6px">
                  <input id="ch-in" type="text" placeholder="说点什么…"
                         style="flex:1;padding:6px 8px;border-radius:6px;border:1px solid #444;background:#1b1b1b;color:#eee">
                  <button id="ch-send" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">发</button>
                  <button id="ch-new" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">新会话</button>
                </div>
                <div id="ch-meta" style="font-size:12px;opacity:.65;margin-top:4px"></div>
              </div>
            </div>
          </div>
"""
if 'id="chat-card"' not in t:
    anchor = '<div class="card" id="mg-card">'
    assert anchor in t
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 对话台（台账 1260）：多会话复用 /sessions、/history、/talk */
(function () {
  var cur = "console";
  function el(id) { return document.getElementById(id); }
  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
  function paint(msgs) {
    var b = el("ch-body"); if (!b) return;
    b.innerHTML = (msgs || []).map(function (m) {
      var who = m.role === "user" ? "老爹" : "元亨";
      var color = m.role === "user" ? "#3498db" : "#2ecc71";
      return "<div style='margin-bottom:6px'><b style='color:" + color + "'>" + who + "：</b>"
        + esc(m.content) + "</div>";
    }).join("");
    b.scrollTop = b.scrollHeight;
  }
  function listSessions() {
    fetch("/sessions", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (d) {
        var box = el("ch-list"); if (!box) return;
        var items = (d && d.items) || [];
        box.innerHTML = items.map(function (s) {
          var act = (s.name === cur) ? "background:#243;border-left:3px solid #2ecc71" : "border-left:3px solid transparent";
          return "<div class='ch-item' data-n='" + s.name + "' style='cursor:pointer;padding:3px 6px;" + act + "'>"
            + "<b>" + esc(s.name.replace(/^qq_/, "")) + "</b> <span style='opacity:.6'>(" + (s.turns || 0) + ")</span>"
            + "<br><span style='opacity:.55'>" + esc(String(s.title || "").slice(0, 18)) + "</span></div>";
        }).join("");
        Array.prototype.forEach.call(box.querySelectorAll(".ch-item"), function (x) {
          x.addEventListener("click", function () { cur = x.getAttribute("data-n"); load(); });
        });
      }).catch(function () {});
  }
  function load() {
    var m = el("ch-meta"); if (m) m.textContent = "会话：" + cur;
    fetch("/history?session=" + encodeURIComponent(cur), {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) { paint((d && d.messages) || []); listSessions(); })
      .catch(function () {});
  }
  function send() {
    var inp = el("ch-in"); var text = (inp && inp.value || "").trim();
    if (!text) return;
    var btn = el("ch-send"); if (btn) { btn.disabled = true; btn.textContent = "…"; }
    var meta = el("ch-meta"); if (meta) meta.textContent = "发送中（约 3–15 秒）…";
    inp.value = "";
    fetch("/talk", {method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({text: text, channel: cur})})
      .then(function (r) { return r.text(); })
      .then(function (raw) {
        var out = [];
        raw.split("\\n").forEach(function (ln) {
          ln = ln.trim();
          if (!ln.startsWith("data:")) return;
          try {
            var ev = JSON.parse(ln.slice(5).trim());
            if (ev.type === "delta" && ev.delta) out.push(ev.delta);
            if (ev.type === "turn_done" && ev.text) out = [ev.text];
            if (ev.type === "error") out = ["⚠ " + (ev.message || "出错")];
          } catch (e) {}
        });
        if (meta) meta.textContent = "会话：" + cur + "（已回复）";
        load();
        var b = el("ch-body");
        if (b && out.length) b.innerHTML += "<div style='margin-bottom:6px'><b style='color:#2ecc71'>元亨：</b>" + esc(out.join("")) + "</div>";
      })
      .catch(function (e) { if (meta) meta.textContent = "失败：" + e; })
      .then(function () { if (btn) { btn.disabled = false; btn.textContent = "发"; } });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var s = el("ch-send"), n = el("ch-new"), i = el("ch-in");
    if (s) s.addEventListener("click", send);
    if (i) i.addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
    if (n) n.addEventListener("click", function () {
      cur = "wb_" + Date.now().toString(36);
      load();
      var m = el("ch-meta"); if (m) m.textContent = "新会话：" + cur + "（发一句就会建起来）";
    });
    load();
  });
})();
</script>
"""
if "chat-card" in t and "/history?session=" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("对话台卡已加")
