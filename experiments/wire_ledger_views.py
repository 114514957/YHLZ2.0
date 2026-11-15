# -*- coding: utf-8 -*-
"""① 无标题 markdown 的回退（计划表/成长日志没有 ## 标题）
② 接 /api/ledger_* 三个接口
③ 工作台「台账」页改成三个视图（元亨橙 / 项目蓝 / 日记紫）
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① 回退
P1 = os.path.join(ROOT, "backend", "ledger_views.py")
t1 = io.open(P1, encoding="utf-8").read()
old = """    res = []
    for b in out[-limit:]:
        text = "\\n".join(b["lines"]).strip()
        res.append({"title": b["title"] or "（无标题）", "text": text[:1200],
                    "chars": len(text)})
    return res"""
new = """    res = []
    for b in out[-limit:]:
        text = "\\n".join(b["lines"]).strip()
        res.append({"title": b["title"] or "（无标题）", "text": text[:1200],
                    "chars": len(text)})
    if not any(r["title"] != "（无标题）" for r in res) and lines:
        # 该文件没有 `## ` 标题：整段取尾部若干行当一块（计划表/成长日志就是这种）
        tail = [ln for ln in lines if ln.strip()][-40:]
        text = "\\n".join(tail)
        res = [{"title": "最近 %d 行" % len(tail), "text": text[:1600],
                "chars": len(text)}]
    return res"""
assert old in t1, "定位失败"
t1 = t1.replace(old, new, 1)
io.open(P1, "w", encoding="utf-8").write(t1)
print("回退已加")

# ② 接口
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()
if "/api/ledger_her" not in d:
    anchor = '        if method == "GET" and p.startswith("/api/eval_compare"):'
    add = '''        if method == "GET" and p.startswith("/api/ledger_"):
            # 台账分家（台账 1258）：元亨 / 项目 / 日记，三本分开、不混排。
            try:
                from backend import ledger_views as _lv
                import urllib.parse as _up
                qs = _up.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                g = lambda k, dv: (qs.get(k) or [dv])[0]  # noqa: E731
                if p == "/api/ledger_her":
                    self._send(200, {"ok": True, **_lv.her_ledger(int(g("limit", "6")))})
                elif p == "/api/ledger_diary":
                    self._send(200, {"ok": True, **_lv.diary(int(g("limit", "8")))})
                elif p == "/api/ledger_project":
                    self._send(200, {"ok": True, **_lv.project_ledger(
                        int(g("limit", "8")), int(g("offset", "0")),
                        g("only_her", "0") in ("1", "true", "yes"))})
                else:
                    self._send(404, {"ok": False, "error": "未知台账视图"})
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
