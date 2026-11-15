# -*- coding: utf-8 -*-
"""接 /api/eval_compare + 在「一键评测」卡里加对拍区。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()

if "/api/eval_compare" not in d:
    anchor = '        if method == "GET" and p.startswith("/api/recent_turns"):'
    add = '''        if method == "GET" and p.startswith("/api/eval_compare"):
            # 逐题对拍（台账 1257）：A=旧、B=新，列出修好/新挂与题目原文。
            try:
                from backend import eval_compare as _ec
                import urllib.parse as _up
                qs = _up.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                a = (qs.get("a") or [""])[0]
                b = (qs.get("b") or [""])[0]
                ts = _ec.tags(12)
                if not (a and b):
                    if len(ts) < 2:
                        self._send(200, {"ok": False, "error": "至少要有两版评测"})
                        return True
                    a, b = ts[1]["tag"], ts[0]["tag"]
                self._send(200, {"ok": True, **{"compare": _ec.compare(a, b)},
                                 "tags": ts})
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

P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()
if 'id="cmp-box"' not in t:
    anchor = '<div id="eval-result" style="font-size:12px;line-height:1.7"></div>'
    add = ('<div id="eval-result" style="font-size:12px;line-height:1.7"></div>\n'
           '            <div style="margin-top:6px"><button id="cmp-go" type="button" '
           'style="padding:4px 10px;border-radius:6px;cursor:pointer">与上一版对拍</button>'
           ' <span id="cmp-msg" style="font-size:12px;opacity:.7"></span></div>\n'
           '            <div id="cmp-box" style="font-size:12px;line-height:1.7"></div>')
    assert anchor in t
    t = t.replace(anchor, add, 1)

    JS = """
<script>
/* 逐题对拍（台账 1257）：GET /api/eval_compare */
(function () {
  function render(d) {
    var box = document.getElementById("cmp-box");
    var msg = document.getElementById("cmp-msg");
    if (!box) return;
    if (!d || !d.ok) { box.innerHTML = "<span style='color:#f39c12'>" + ((d && d.error) || "取不到") + "</span>"; return; }
    var c = d.compare;
    if (msg) msg.textContent = c.a + " → " + c.b;
    var html = "";
    ["persona", "group"].forEach(function (s) {
      var x = c.suites[s];
      if (!x) return;
      var name = s === "persona" ? "人格" : "群聊";
      html += "<div style='margin-top:6px'><b>" + name + " " + x.a_ok + " → " + x.b_ok
        + "（" + (x.delta >= 0 ? "+" : "") + x.delta + "）</b>";
      if (x.fixed.length) html += "<br><span style='color:#2ecc71'>修好 " + x.fixed.length
        + "：" + x.fixed.map(function (f) { return f.id; }).join(",") + "</span>";
      if (x.broke.length) html += "<br><span style='color:#e74c3c'>新挂 " + x.broke.length
        + "：" + x.broke.map(function (f) { return f.id; }).join(",") + "</span>"
        + "<br><span style='opacity:.65'>" + x.broke.slice(0, 4).map(function (f) {
            return "· " + f.q.slice(0, 18); }).join("<br>") + "</span>";
      html += "</div>";
    });
    box.innerHTML = html;
  }
  function load() {
    fetch("/api/eval_compare", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(render).catch(function () {});
  }
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("cmp-go");
    if (b) b.addEventListener("click", load);
  });
})();
</script>
"""
    if "/api/eval_compare" not in t.split("</body>")[-1]:
        t = t.replace("</body>", JS + "</body>", 1)
    io.open(P, "w", encoding="utf-8").write(t)
    print("界面已加")
else:
    print("界面已存在")
