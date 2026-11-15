# -*- coding: utf-8 -*-
"""训练完了：检查 adapter 内容 → 打包 → sha256（不依赖守护脚本）。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v11"
PACK = "/root/autodl-tmp/pack_v11.tar.gz"

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    o.channel.settimeout(t - 5)
    try:
        return o.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


print("=== adapter 目录 ===")
print(sh("ls -l %s; du -sh %s" % (OUT, OUT)))

print("\n=== 摘要 ===")
print(sh("cat %s/train_summary.md 2>/dev/null | head -20" % OUT))

print("\n=== 打包 ===")
print(sh("rm -f %s && tar -czf %s --exclude='checkpoint-*' -C %s . && "
         "ls -l %s && sha256sum %s | cut -d' ' -f1 && df -h /root/autodl-tmp | tail -1"
         % (PACK, PACK, OUT, PACK, PACK), t=1800))
c.close()
