# -*- coding: utf-8 -*-
"""测云端端口通不通（多行脚本，避免 cmd 吃掉换行）。"""
from __future__ import annotations

import socket
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST = "connect.nma1.seetacloud.com"
for port in (39522, 22):
    s = socket.socket()
    s.settimeout(6)
    try:
        s.connect((HOST, port))
        print("%s:%d  ✅ 通" % (HOST, port))
    except Exception as ex:  # noqa: BLE001
        print("%s:%d  ❌ %s" % (HOST, port, type(ex).__name__))
    finally:
        s.close()
