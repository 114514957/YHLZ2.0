# -*- coding: utf-8 -*-
"""给工作台加「链路状态」卡的脚本（插在 </body> 之前，纯前端轮询 /api/stack_status）。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

SCRIPT = """
<script>
/* 链路状态卡（2026-11-15 台账 1251/1252）：四灯 + 费用 + 告警，15 秒轮询。 */
(function () {
  var on = "#2ecc71", off = "#e74c3c", warn = "#f39c12";
  function setDot(id, ok, extra) {
    var el = document.getElementById(id);
    if (!el) return;
    el.style.background = ok ? on : off;
    el.style.boxShadow = ok ? "0 0 6px " + on : "none";
    if (extra !== undefined) {
      var n = document.getElementById(id + "-n") || document.getElementById(id + "-m");
      if (n) n.textContent = extra || "";
    }
  }
  function refresh() {
    fetch("/api/stack_status", {cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        var s = d.snapshot || {};
        setDot("st-daemon", !!(s.daemon && s.daemon.ok),
               s.daemon && s.daemon.instances > 1 ? "×" + s.daemon.instances : "");
        setDot("st-napcat", !!(s.napcat && s.napcat.ok));
        setDot("st-cloud", !!(s.cloud && s.cloud.ok), (s.cloud && s.cloud.model) || "");
        setDot("st-llama", !!(s.llama && s.llama.ok));
        var u = s.usage || {};
        var c = document.getElementById("st-cost");
        if (c) {
          c.textContent = "¥" + (u.today_cost != null ? u.today_cost : "—")
            + " / ¥" + (u.cost != null ? u.cost : "—")
            + "（" + (u.calls || 0) + " 次）";
        }
        var w = document.getElementById("st-warn");
        if (w) {
          var list = d.warnings || [];
          w.innerHTML = list.length
            ? list.map(function (x) { return "<div style='color:" + warn + "'>" + x + "</div>"; }).join("")
            : "<div style='color:" + on + "'>链路正常</div>";
        }
        var ts = document.getElementById("st-ts");
        if (ts) ts.textContent = new Date().toLocaleTimeString();
      })
      .catch(function () {});
  }
  document.addEventListener("DOMContentLoaded", function () {
    refresh();
    setInterval(refresh, 15000);
  });
})();
</script>
"""

if "/api/stack_status" not in t:
    assert "</body>" in t, "找不到 </body>"
    t = t.replace("</body>", SCRIPT + "</body>", 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("已插入前端脚本")
else:
    print("脚本已存在，跳过")
