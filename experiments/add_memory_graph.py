# -*- coding: utf-8 -*-
"""记忆星图：接口 + 画布（无外部依赖的简易力导向）。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① 接口
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()
if "/api/memory_graph" not in d:
    anchor = '        if method == "GET" and p.startswith("/api/ledger_"):'
    add = '''        if method == "GET" and p.startswith("/api/memory_graph"):
            # 记忆星图（台账 1259）：全量记忆的节点与边。
            try:
                from backend import memory_graph as _mg
                import urllib.parse as _up
                qs = _up.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                lim = int((qs.get("limit") or ["400"])[0])
                mi = int((qs.get("min_importance") or ["0"])[0])
                self._send(200, {"ok": True, **_mg.graph(lim, mi)})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "%s: %s"
                                 % (type(exc).__name__, str(exc)[:140])})
            return True
'''
    assert anchor in d
    d = d.replace(anchor, add + anchor, 1)
    io.open(D, "w", encoding="utf-8").write(d)
    print("接口已加")
else:
    print("接口已存在")

# ② 页面：记忆页加星图卡
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()
CARD = """
          <div class="card" id="mg-card">
            <h3>记忆星图 <small style="font-weight:400;opacity:.6">全量 · 点节点看原文</small></h3>
            <div style="margin-bottom:6px;font-size:12px">
              <input id="mg-q" type="text" placeholder="搜内容（回车高亮）"
                     style="padding:4px 8px;border-radius:6px;border:1px solid #444;background:#1b1b1b;color:#eee;width:180px">
              <label style="margin-left:8px"><input type="checkbox" class="mg-role" value="her" checked> 她说的</label>
              <label style="margin-left:6px"><input type="checkbox" class="mg-role" value="owner" checked> 老爹</label>
              <label style="margin-left:6px"><input type="checkbox" class="mg-role" value="unknown"> 未知</label>
              <label style="margin-left:6px"><input type="checkbox" class="mg-role" value="engineering"> 工程</label>
              <span id="mg-stat" style="opacity:.6;margin-left:8px"></span>
            </div>
            <canvas id="mg-canvas" width="900" height="460"
                    style="width:100%;height:auto;background:#121212;border-radius:8px"></canvas>
            <div id="mg-detail" style="font-size:12px;line-height:1.6;margin-top:6px;opacity:.9"></div>
          </div>
"""
if 'id="mg-card"' not in t:
    anchor = '<section class="panel" data-panel="memory">'
    assert anchor in t
    i = t.find(anchor) + len(anchor)
    j = t.find('<div class="card">', i)
    assert j > i
    t = t[:j] + CARD + "\n          " + t[j:]

JS = """
<script>
/* 记忆星图（台账 1259）：简易力导向，无外部依赖 */
(function () {
  var nodes = [], links = [], sel = null, xf = {x: 0, y: 0, k: 1};
  function canvas() { return document.getElementById("mg-canvas"); }
  function want() {
    var out = {};
    Array.prototype.forEach.call(document.querySelectorAll(".mg-role"), function (c) {
      out[c.value] = c.checked;
    });
    return out;
  }
  function layout() {
    var w = 900, h = 460, i, j, n = nodes.length;
    for (i = 0; i < n; i++) {
      var a = nodes[i];
      if (a.x == null) { a.x = w / 2 + (Math.random() - 0.5) * 300; a.y = h / 2 + (Math.random() - 0.5) * 300; }
      a.vx = a.vy = 0;
    }
    for (var it = 0; it < 120; it++) {
      for (i = 0; i < n; i++) {
        var p = nodes[i];
        for (j = i + 1; j < n; j++) {
          var q = nodes[j], dx = p.x - q.x, dy = p.y - q.y;
          var d2 = dx * dx + dy * dy + 0.01, f = 900 / d2;
          var d = Math.sqrt(d2);
          p.vx += dx / d * f; p.vy += dy / d * f;
          q.vx -= dx / d * f; q.vy -= dy / d * f;
        }
        p.vx += (w / 2 - p.x) * 0.002; p.vy += (h / 2 - p.y) * 0.002;
      }
      links.forEach(function (l) {
        var a = nodes[l.si], b = nodes[l.ti];
        if (!a || !b) return;
        var dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01;
        var f = (d - 60) * 0.02;
        a.vx += dx / d * f; a.vy += dy / d * f;
        b.vx -= dx / d * f; b.vy -= dy / d * f;
      });
      for (i = 0; i < n; i++) {
        var s = nodes[i];
        s.x += Math.max(-8, Math.min(8, s.vx)); s.y += Math.max(-8, Math.min(8, s.vy));
        s.x = Math.max(12, Math.min(w - 12, s.x)); s.y = Math.max(12, Math.min(h - 12, s.y));
        s.vx *= 0.6; s.vy *= 0.6;
      }
    }
  }
  function draw() {
    var c = canvas(); if (!c) return;
    var ctx = c.getContext("2d"), on = want();
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.strokeStyle = "rgba(255,255,255,.10)";
    links.forEach(function (l) {
      var a = nodes[l.si], b = nodes[l.ti];
      if (!a || !b || !on[a.role] || !on[b.role]) return;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    });
    nodes.forEach(function (n) {
      if (!on[n.role]) return;
      var r = 3 + Math.min(9, n.imp);
      ctx.fillStyle = n.color;
      ctx.globalAlpha = sel === n ? 1 : .85;
      ctx.beginPath();
      if (n.shape === "square") ctx.rect(n.x - r, n.y - r, r * 2, r * 2);
      else if (n.shape === "triangle") { ctx.moveTo(n.x, n.y - r); ctx.lineTo(n.x + r, n.y + r); ctx.lineTo(n.x - r, n.y + r); }
      else ctx.arc(n.x, n.y, r, 0, 6.284);
      ctx.fill();
      if (sel === n) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke(); ctx.lineWidth = 1; }
      ctx.globalAlpha = 1;
    });
  }
  function indexLinks() {
    var idx = {}; nodes.forEach(function (n, i) { idx[n.id] = i; });
    links.forEach(function (l) {
      if (l.si == null) { l.si = idx[l.source]; l.ti = idx[l.target]; }
    });
  }
  function load() {
    fetch("/api/memory_graph?limit=400", {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        nodes = d.nodes || []; links = d.links || [];
        indexLinks(); layout();
        var st = d.stats || {};
        var s = document.getElementById("mg-stat");
        if (s) s.textContent = (st.nodes || 0) + " 节点 / " + (st.links || 0) + " 边";
        draw();
      }).catch(function () {});
  }
  function hit(ev) {
    var c = canvas(); if (!c) return null;
    var rect = c.getBoundingClientRect();
    var x = (ev.clientX - rect.left) * (c.width / rect.width);
    var y = (ev.clientY - rect.top) * (c.height / rect.height);
    var best = null, bd = 1e9;
    nodes.forEach(function (n) {
      var d = (n.x - x) * (n.x - x) + (n.y - y) * (n.y - y);
      if (d < bd) { bd = d; best = n; }
    });
    return (best && bd < 400) ? best : null;
  }
  document.addEventListener("DOMContentLoaded", function () {
    var c = canvas(); if (!c) return;
    c.addEventListener("click", function (ev) {
      sel = hit(ev);
      var det = document.getElementById("mg-detail");
      if (sel) {
        det.innerHTML = "<b>" + sel.id + "</b>　" + sel.type + " / " + sel.role
          + " ｜重要度 " + sel.imp + "<br>" + (sel.text || "");
      } else { det.textContent = ""; }
      draw();
    });
    Array.prototype.forEach.call(document.querySelectorAll(".mg-role"), function (x) {
      x.addEventListener("change", draw);
    });
    var q = document.getElementById("mg-q");
    if (q) q.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var kw = (q.value || "").trim();
      var found = nodes.filter(function (n) { return kw && (n.text || "").indexOf(kw) >= 0; });
      var det = document.getElementById("mg-detail");
      if (!found.length) { det.textContent = "没找到"; return; }
      sel = found[0];
      det.innerHTML = "命中 " + found.length + " 条，第一条：<b>" + sel.id + "</b><br>" + (sel.text || "");
      draw();
    });
    load();
  });
})();
</script>
"""
if "mg-card" in t and "/api/memory_graph" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("星图卡已加")
