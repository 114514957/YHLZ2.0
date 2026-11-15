# -*- coding: utf-8 -*-
"""接 /api/recent_turns + 工作台「最近回合」卡。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① daemon 侧接口（与 stack_status 同法：直拦，避免被 /api/* 转发）
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()
if "api/recent_turns" not in d:
    anchor = '        if method == "GET" and p == "/api/qq_intel":'
    add = '''        if method == "GET" and p.startswith("/api/recent_turns"):
            # 工作台「最近回合」卡（2026-11-15 台账 1254）：问句/注入/费用一屏。
            try:
                from backend import recent_turns as _rt
                lim = 20
                if "?" in self.path:
                    import urllib.parse as _up
                    qs = _up.parse_qs(self.path.split("?", 1)[1])
                    lim = int((qs.get("limit") or [20])[0])
                self._send(200, {"ok": True, **_rt.recent(max(1, min(lim, 100)))})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "%s: %s"
                                 % (type(exc).__name__, str(exc)[:120])})
            return True
'''
    assert anchor in d
    d = d.replace(anchor, add + anchor, 1)
    io.open(D, "w", encoding="utf-8").write(d)
    print("已加 /api/recent_turns")
else:
    print("接口已存在")

# ② 页面卡
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()
CARD = """
          <div class="card" id="turns-card">
            <h3>最近回合 <small style="font-weight:400;opacity:.6">问句／注入／费用</small></h3>
            <div id="turns-body" style="font-size:12px;line-height:1.6">加载中…</div>
          </div>
"""
if 'id="turns-card"' not in t:
    anchor = '<div class="card" id="intel-card">'
    assert anchor in t
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 最近回合（台账 1254）：GET /api/recent_turns */
(function () {
  function render(d) {
    var box = document.getElementById("turns-body");
    if (!box) return;
    if (!d || !d.ok || !(d.rows || []).length) { box.textContent = "还没有回合记录"; return; }
    box.innerHTML = d.rows.slice().reverse().map(function (r) {
      var hit = r.n > 0
        ? "<span style='color:#2ecc71'>注入" + r.n + " " + (r.ids || []).join(",") + "</span>"
        : "<span style='opacity:.5'>无注入</span>";
      return "<div style='margin-bottom:6px'>"
        + "<span style='opacity:.65'>" + r.time + "</span>　"
        + "<b>" + (r.q || "") + "</b><br>"
        + hit
        + (r.tokens_in != null ? "　in " + r.tokens_in + " / out " + r.tokens_out : "")
        + (r.cost != null ? "　¥" + r.cost : "")
        + "</div>";
    }).join("");
  }
  function load() {
    fetch("/api/recent_turns?limit=20", {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(render).catch(function () {});
  }
  document.addEventListener("DOMContentLoaded", function () {
    load(); setInterval(load, 20000);
  });
})();
</script>
"""
if "/api/recent_turns" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("已加「最近回合」卡")
