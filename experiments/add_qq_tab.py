# -*- coding: utf-8 -*-
"""前端：QQ 独立菜单 + 登录指引（二维码 404 不再破图）+ 打开登录窗口按钮。"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "assets", "webui", "index.html")
t = io.open(P, encoding="utf-8").read()

# ① 新增 QQ 页签按钮（放在「状态」之后）
if 'data-panel="qq"' not in t:
    anchor = '<button class="tab" data-panel="memory" type="button">记忆</button>'
    assert anchor in t
    t = t.replace(anchor,
                  '<button class="tab" data-panel="qq" type="button">QQ</button>\n          '
                  + anchor, 1)

# ② 新增 QQ 面板（空的，卡片由 JS 搬进来）
if 'data-panel="qq"' in t and '<section class="panel" data-panel="qq">' not in t:
    anchor = '<section class="panel" data-panel="memory">'
    assert anchor in t
    t = t.replace(anchor,
                  '<section class="panel" data-panel="qq">\n'
                  '          <div class="card" id="qq-help-card">\n'
                  '            <h3>QQ 登录 <small style="font-weight:400;opacity:.6">扫码窗口</small></h3>\n'
                  '            <div style="margin-bottom:6px">\n'
                  '              <button id="qq-win" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">打开登录窗口</button>\n'
                  '              <button id="qq-check" type="button" style="padding:6px 12px;border-radius:6px;cursor:pointer">检查登录状态</button>\n'
                  '              <span id="qq-state" style="font-size:12px;opacity:.75;margin-left:8px"></span>\n'
                  '            </div>\n'
                  '            <div style="font-size:12px;line-height:1.7;opacity:.85">\n'
                  '              NapCat 是<b>带窗口登录</b>的：点上面按钮会开一个登录窗口，用手机 QQ 扫码即可。<br>\n'
                  '              工作台里的二维码只对<b>无头模式</b>有效，没有时不再显示破图。\n'
                  '            </div>\n'
                  '            <img id="qqQr" alt="" style="display:none;width:150px;height:150px;border-radius:8px;background:#fff">\n'
                  '          </div>\n'
                  + anchor, 1)

# ③ JS：搬卡 + 登录按钮
JS = """
<script>
/* QQ 独立菜单（台账 1261）：把三张 QQ 卡搬进「QQ」页；修登录引导 */
(function () {
  var NAMES = ["元亨 QQ", "群聊白名单", "群情报"];
  function moveCards() {
    var panel = document.querySelector('section.panel[data-panel="qq"]');
    if (!panel) return;
    var cards = Array.prototype.slice.call(document.querySelectorAll("div.card"));
    cards.forEach(function (c) {
      var h = c.querySelector("h3");
      if (!h) return;
      var name = (h.textContent || "").trim().split(/\\s+/)[0];
      if (NAMES.indexOf(name) >= 0 && c.parentNode !== panel) {
        panel.appendChild(c);
      }
    });
  }
  function setState(s) {
    var el = document.getElementById("qq-state");
    if (el) el.textContent = s;
  }
  function checkLogin() {
    setState("检查中…");
    fetch("/state", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (d) {
        var q = (d && d.qq) || {};
        var ok = !!(q.online && q.ws);
        setState(ok ? ("已登录（" + (q.uin || "") + "，桥在线）") : "未登录 / 桥未连上");
        var el = document.getElementById("qq-state");
        if (el) el.style.color = ok ? "#2ecc71" : "#f39c12";
      }).catch(function () { setState("检查失败"); });
  }
  function openWin() {
    setState("正在打开登录窗口…");
    fetch("/control", {method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify({action: "napcat_window"})})
      .then(function (r) { return r.json(); })
      .then(function (x) {
        setState(x.ok ? (x.note || "已打开，请在窗口里扫码") : ("失败：" + (x.error || "")));
        setTimeout(checkLogin, 15000);
        setTimeout(checkLogin, 40000);
      }).catch(function (e) { setState("失败：" + e); });
  }
  document.addEventListener("DOMContentLoaded", function () {
    moveCards();
    var w = document.getElementById("qq-win"), c = document.getElementById("qq-check");
    if (w) w.addEventListener("click", openWin);
    if (c) c.addEventListener("click", checkLogin);
    var img = document.getElementById("qqQr");
    if (img) {
      img.onload = function () { img.style.display = "block"; };
      img.onerror = function () { img.style.display = "none"; };
      img.src = "/qq-qrcode?t=" + Date.now();
    }
    checkLogin();
    setInterval(checkLogin, 60000);
  });
})();
</script>
"""
if 'data-panel="qq"' in t and "/control\", {method" not in t:
    if "</body>" in t:
        t = t.replace("</body>", JS + "</body>", 1)

io.open(P, "w", encoding="utf-8").write(t)
print("② 前端已加 QQ 页签/面板/JS")
for k in ('data-panel="qq"', 'qq-win', 'qq-check', 'qq-state', "moveCards"):
    print("  %-18s %s" % (k, "✅" if k in t else "❌"))
