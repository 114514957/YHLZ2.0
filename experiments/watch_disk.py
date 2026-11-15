# -*- coding: utf-8 -*-
"""在云端挂一个看门狗：checkpoint-600 一写稳就删，给最后的 save_model 腾地方。"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"

import paramiko  # noqa: E402

WATCH = r"""#!/bin/bash
D=/root/autodl-tmp/models/full/yuanheng-v9f1-gemma
LOG=/root/autodl-tmp/logs/watch_disk.log
for i in $(seq 1 240); do
  for ck in $D/checkpoint-*; do
    [ -d "$ck" ] || continue
    sz=$(du -sm "$ck" 2>/dev/null | cut -f1)
    free=$(df -m /root/autodl-tmp | tail -1 | awk '{print $4}')
    if [ "$sz" -gt 10000 ] && [ "$free" -lt 18000 ]; then
      echo "$(date +%H:%M:%S) 删 $ck（${sz}MB），盘剩 ${free}MB" >> $LOG
      rm -rf "$ck"
    fi
  done
  sleep 30
done
echo "$(date +%H:%M:%S) 看门狗退出" >> $LOG
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)
s = c.open_sftp()
with s.open("/root/yh/watch_disk.sh", "w") as f:
    f.write(WATCH)
s.close()
_i, o, e = c.exec_command("chmod +x /root/yh/watch_disk.sh && "
                          "( setsid bash /root/yh/watch_disk.sh >/dev/null 2>&1 </dev/null & ) ; "
                          "sleep 2; pgrep -fc watch_disk", timeout=60)
print("看门狗进程数：%s" % o.read().decode().strip())
_i, o, e = c.exec_command("df -h /root/autodl-tmp | tail -1", timeout=60)
print("磁盘：%s" % o.read().decode().strip())
c.close()
