# -*- coding: utf-8 -*-
"""调整路径：云端包改成纯 ASCII 名（中文会被网盘/面板翻译坏），本地建统一收件箱。

云端：/root/autodl-tmp/pack_<tag>.tar.gz + pack_<tag>.sha256
本地：YH/dist/_inbox/    ← 你手动下的东西都丢这里，我自动认
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAGS = ["v9t7", "v9t8", "v9t10"]

# 本地收件箱（ASCII 名，避免翻译层捣乱）
inbox = os.path.join(YH, "dist", "_inbox")
os.makedirs(inbox, exist_ok=True)
with open(os.path.join(inbox, "README.txt"), "w", encoding="utf-8") as f:
    f.write("把你从任何地方下载的文件丢进这个目录，利贞会自己认。\n"
            "文件名保持原样即可（v9t10_产物.tar.gz / adapter_model.safetensors 等）。\n")
print("本地收件箱：%s" % inbox)

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


print("\n云端改名（纯 ASCII）：")
lines = []
for tag in TAGS:
    old = "/root/autodl-tmp/%s_产物.tar.gz" % tag
    new = "/root/autodl-tmp/pack_%s.tar.gz" % tag
    o, _ = sh("test -f %s && echo YES || echo NO" % old)
    if "YES" not in o:
        o, _ = sh("test -f %s && echo YES || echo NO" % new)
        print("  %-7s 已存在或缺失（%s）" % (tag, "改名过" if "YES" in o else "没有"))
        lines.append(new)
        continue
    sh("mv -f %s %s && sha256sum %s > /root/autodl-tmp/pack_%s.sha256" % (old, new, new, tag))
    lines.append(new)

# 生成一份纯 ASCII 的清单
o, _ = sh("cd /root/autodl-tmp && ls -l pack_*.tar.gz 2>/dev/null | awk '{print $9, $5}'")
print(o)

with c.open_sftp().open("/root/autodl-tmp/PACKS.txt", "w") as f:
    f.write("每版一个瘦包（adapter + 配置 + 摘要 + 日志，不含 checkpoint）\n")
    f.write(o + "\n")
    f.write("下载地址前缀：/root/autodl-tmp/\n")
    f.write("校验：pack_<tag>.sha256\n")
print("\n清单：/root/autodl-tmp/PACKS.txt")
c.close()
