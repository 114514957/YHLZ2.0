# -*- coding: utf-8 -*-
"""把 v10u 传上云端并启动（基座缺失时脚本内会自动下 TrevorJS 的 safetensors）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v10u.tar.gz")

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=1800):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("df -h /root/autodl-tmp | tail -1; ls -l /root/autodl-tmp/models | head")
print("磁盘：\n" + o)

print("\n上传 %d 字节…" % os.path.getsize(TAR))
s = c.open_sftp()
s.put(TAR, "/root/yh/retrain_pkg_gemma_v10u.tar.gz")
s.close()

o, e = sh("cd /root/yh && rm -rf retrain_pkg_gemma_v10u && "
          "tar -xzf retrain_pkg_gemma_v10u.tar.gz && "
          "wc -l retrain_pkg_gemma_v10u/*.jsonl && chmod +x retrain_pkg_gemma_v10u/run_v10u.sh")
print(o or e)

print("\n启动（含基座下载）…")
o, e = sh("cd /root/yh/retrain_pkg_gemma_v10u && "
          "nohup bash run_v10u.sh > /root/autodl-tmp/logs/run_v10u.log 2>&1 & echo LAUNCHED", t=120)
print(o or e)
time.sleep(20)
o, _ = sh("tail -12 /root/autodl-tmp/logs/run_v10u.log")
print("日志：\n" + o)
c.close()
