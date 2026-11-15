# -*- coding: utf-8 -*-
"""确认这台到底有没有 GPU（nvidia-smi 不在，可能是 CPU 机）。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.sha1.seetacloud.com", 22175, "root", "ir253496QXik"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=120):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


for label, cmd in (
    ("nvidia 设备文件", "ls -l /dev/nvidia* 2>/dev/null || echo 没有 /dev/nvidia*"),
    ("nvidia driver", "ls /proc/driver/nvidia 2>/dev/null || echo 没有 /proc/driver/nvidia"),
    ("lspci", "lspci 2>/dev/null | grep -i -E 'nvidia|vga|3d' || echo lspci 无输出"),
    ("机器规格", "nproc; grep 'model name' /proc/cpuinfo | head -1"),
    ("镜像信息", "cat /etc/motd 2>/dev/null | head -5; ls /root/ | head"),
):
    o, e = sh(cmd)
    print("=== %s ===" % label)
    print((o or e or "（空）")[:400])
    print()
c.close()
