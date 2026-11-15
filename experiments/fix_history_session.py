# -*- coding: utf-8 -*-
"""让 /history 支持 ?session=（多会话隔离）——之前它写死读 console。

原因：console_server._history() 固定 self.runtime._session("console")，
所以对话台切到别的会话时看到的还是 console 的记录（实测两个会话内容一模一样）。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "console_server.py")
t = io.open(P, encoding="utf-8").read()

old = '''    def _history(self) -> dict:
        """Console session dialogue history (persisted per turn in cache/sessions/
        console.json) so a page refresh restores the conversation."""
        try:
            s = self.runtime._session("console")'''
new = '''    def _history(self, name: str = "") -> dict:
        """某会话的对话历史。2026-11-15（台账 1260）：支持 ?session= 切换，
        之前写死 "console"，导致对话台切会话看到的永远是 console 的记录。"""
        try:
            s = self.runtime._session(str(name or "console"))'''
assert old in t, "定位失败"
t = t.replace(old, new, 1)

old2 = '''        elif p == "/history":
            self._send_json(200, self._history())'''
new2 = '''        elif p == "/history":
            _sess = ""
            if "?" in self.path:
                import urllib.parse as _up
                _sess = (_up.parse_qs(self.path.split("?", 1)[1]).get("session") or [""])[0]
            self._send_json(200, self._history(_sess))'''
assert old2 in t, "找不到 /history 分发"
t = t.replace(old2, new2, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("已改：/history 支持 ?session=")
