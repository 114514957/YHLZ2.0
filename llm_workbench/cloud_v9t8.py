# -*- coding: utf-8 -*-
"""v9t8 云端：上传 → 解包 → 后台开训 → 盯。密码从 YH_SSH_PASS 或 --password。"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t8.tar.gz")
RTAR = "/root/yh/retrain_pkg_gemma_v9t8.tar.gz"
PKG = "/root/yh/retrain_pkg_gemma_v9t8"
LOG = "/root/autodl-tmp/logs/train_v9t8.log"


def conn(a):
    import paramiko
    pw = a.password or os.environ.get("YH_SSH_PASS", "")
    if not pw:
        sys.exit("需要密码")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=int(a.port), username=a.user, password=pw,
              timeout=30, banner_timeout=30, auth_timeout=30)
    return c


def sh(c, cmd, t=900):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


ap = argparse.ArgumentParser()
ap.add_argument("--host", default="connect.nma1.seetacloud.com")
ap.add_argument("--port", default="39522")
ap.add_argument("--user", default="root")
ap.add_argument("--password", default="")
ap.add_argument("--upload", action="store_true")
ap.add_argument("--run", action="store_true")
ap.add_argument("--poll", action="store_true")
a = ap.parse_args()

c = conn(a)
try:
    if a.upload:
        print("上传 %.2f MB…" % (os.path.getsize(TAR) / 1048576))
        sh(c, "mkdir -p /root/yh")
        s = c.open_sftp()
        t0 = time.time()
        s.put(TAR, RTAR)
        s.close()
        print("  %s" % sh(c, "ls -l %s" % RTAR)[0])

    if a.run:
        o, e = sh(c, "cd /root/yh && tar -xzf %s && cd %s && wc -l sft_persona_v9t8_*.jsonl && "
                     "mkdir -p /root/autodl-tmp/logs && "
                     "nohup bash run_v9t8.sh > /root/autodl-tmp/logs/run_v9t8.log 2>&1 < /dev/null & "
                     "sleep 3; echo LAUNCHED" % (RTAR, PKG))
        print(o or e)

    if a.poll:
        o, _ = sh(c, "tail -c 600 %s 2>/dev/null | tr '\\r' '\\n' | grep -a . | tail -3" % LOG)
        print(o)
finally:
    c.close()
