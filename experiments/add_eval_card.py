# -*- coding: utf-8 -*-
"""接 /api/eval_run + /api/eval_status，并加工作台「一键评测」卡。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()

if "api/eval_status" not in d:
    anchor = '        if method == "GET" and p.startswith("/api/recent_turns"):'
    add = '''        if method == "GET" and p == "/api/eval_status":
            # 工作台「一键评测」卡（2026-11-15 台账 1255）：状态 + 最近几轮结果。
            try:
                from backend import eval_runner as _er
                st = _er.status()
                self._send(200, {"ok": True, **st, "history": _er.history(6)})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "%s: %s"
                                 % (type(exc).__name__, str(exc)[:120])})
            return True
'''
    assert anchor in d
    d = d.replace(anchor, add + anchor, 1)

    anchor2 = '        if self.path == "/api/try_turn":'
    add2 = '''        if self.path == "/api/eval_run":
            # 起一轮云端评测（152+75，约 4 分钟，约 ¥2.5）。
            try:
                from backend import eval_runner as _er
                res = _er.start(str(payload.get("tag") or ""))
                self._send(200 if res.get("ok") else 409, res)
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "%s: %s"
                                 % (type(exc).__name__, str(exc)[:120])})
            return
'''
    assert anchor2 in d
    d = d.replace(anchor2, add2 + anchor2, 1)
    io.open(D, "w", encoding="utf-8").write(d)
    print("接口已加")
else:
    print("接口已存在")

P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()
CARD = """
          <div class="card" id="eval-card">
            <h3>一键评测 <small style="font-weight:400;opacity:.6">152+75 · 云端 · 约4分钟</small></h3>
            <div style="margin-bottom:8px">
              <button id="eval-go" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">跑一轮</button>
              <span id="eval-state" style="font-size:12px;opacity:.75;margin-left:8px"></span>
            </div>
            <div id="eval-result" style="font-size:12px;line-height:1.7"></div>
            <div id="eval-history" style="font-size:12px;line-height:1.7;margin-top:8px;opacity:.9"></div>
          </div>
"""
if 'id="eval-card"' not in t:
    anchor = '<div class="card" id="turns-card">'
    assert anchor in t
    t = t.replace(anchor, CARD + anchor, 1)

JS = """
<script>
/* 一键评测（台账 1255） */
(function () {
  function paint(d) {
    var st = document.getElementById("eval-state");
    var rs = document.getElementById("eval-result");
    var hs = document.getElementById("eval-history");
    if (!st) return;
    var cur = d.state || {};
    st.textContent = d.running
      ? ("跑着：" + (cur.tag || "") + "（pid " + cur.pid + "）")
      : ((cur.tag ? ("上一轮：" + cur.tag) : "还没跑过"));
    rs.innerHTML = "";
    if (d.result) {
      var r = d.result;
      rs.innerHTML = "<b>人格 " + r.persona + "　群聊 " + r.group + "</b>"
        + (r.persona_failed && r.persona_failed.length
            ? "<br><span style='opacity:.7'>人格挂：" + r.persona_failed.slice(0, 8).join(",") + "</span>" : "")
        + (r.group_failed && r.group_failed.length
            ? "<br><span style='opacity:.7'>群聊挂：" + r.group_failed.join(",") + "</span>" : "");
    }
    if (hs && d.history) {
      hs.innerHTML = "<div style='opacity:.6'>最近几轮</div>" + d.history.map(function (h) {
        return "<div>" + h.tag + "　人格 " + h.persona + "/" + h.persona_n
          + "　群聊 " + h.group + "/" + h.group_n + "</div>";
      }).join("");
    }
  }
  function load() {
    fetch("/api/eval_status", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(paint).catch(function () {});
  }
  function go() {
    var btn = document.getElementById("eval-go");
    if (btn) { btn.disabled = true; btn.textContent = "起…"; }
    fetch("/api/eval_run", {method: "POST", headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({})})
      .then(function (r) { return r.json(); })
      .catch(function () { return {}; })
      .then(function () {
        if (btn) { btn.disabled = false; btn.textContent = "跑一轮"; }
        load();
        setTimeout(load, 20000); setTimeout(load, 60000);
      });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("eval-go");
    if (b) b.addEventListener("click", go);
    load(); setInterval(load, 30000);
  });
})();
</script>
"""
if "/api/eval_status" not in t.split("</body>")[-1]:
    t = t.replace("</body>", JS + "</body>", 1)
io.open(P, "w", encoding="utf-8").write(t)
print("卡片已加")
