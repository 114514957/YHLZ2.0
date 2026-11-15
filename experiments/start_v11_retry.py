# -*- coding: utf-8 -*-
"""v11 开训（带重试）：上传校验 → 依赖 → 预检 → 训练。链路不稳时反复重试。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAR = os.path.join(YH, "dist", "retrain_pkg_gemma_v11.tar.gz")
WANT = os.path.getsize(TAR)
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
PKG = "/root/yh/retrain_pkg_gemma_v11"
LOG = "/root/autodl-tmp/logs/train_v11.log"
REMOTE_TAR = "/root/yh/retrain_pkg_gemma_v11.tar.gz"

import paramiko  # noqa: E402


def conn(t=60):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=t,
              banner_timeout=30, auth_timeout=30)
    c.get_transport().set_keepalive(15)
    return c


def sh(c, cmd, t=7200, show=True):
    _i, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8", "replace").rstrip()
    err = e.read().decode("utf-8", "replace").rstrip()
    if show:
        print(((out + "\n" + err).strip())[:1000], flush=True)
    return out, err


# ── 1. 上传（重试 + 校验大小）──
print("[1] 上传 %d 字节，最多试 6 次" % WANT, flush=True)
ok = False
for attempt in range(1, 7):
    try:
        c = conn()
        s = c.open_sftp()
        s.get_channel().settimeout(120)
        s.put(TAR, REMOTE_TAR)
        s.close()
        o, _ = sh(c, "stat -c %%s %s" % REMOTE_TAR, show=False)
        have = int(o.strip() or 0)
        print("    第 %d 次：%d/%d %s" % (attempt, have, WANT,
                                         "OK" if have == WANT else "不完整"), flush=True)
        if have == WANT:
            ok = True
            break
    except Exception as ex:  # noqa: BLE001
        print("    第 %d 次失败：%s" % (attempt, type(ex).__name__), flush=True)
    time.sleep(5)

if not ok:
    sys.exit("上传 6 次都没成功")

c = conn()
print("\n[2] 解包", flush=True)
sh(c, "cd /root/yh && rm -rf retrain_pkg_gemma_v11 && tar -xzf retrain_pkg_gemma_v11.tar.gz "
      "&& wc -l retrain_pkg_gemma_v11/*.jsonl")

print("\n[3] 依赖", flush=True)
sh(c, "/root/miniconda3/bin/pip install -q 'transformers==5.20.2' 'peft==0.21.2' "
      "'datasets==5.1.0' 'accelerate==1.15.0' 'bitsandbytes==0.50.2' 2>&1 | tail -2", t=3600)

print("\n[4] 预检", flush=True)
o, e = sh(c, "cd %s && /root/miniconda3/bin/python preflight_mlp.py %s" % (PKG, BASE), t=1800)
if "PASS" not in (o + e):
    sys.exit("预检没过")

print("\n[5] 开训", flush=True)
sh(c, "mkdir -p /root/autodl-tmp/logs && cd %s && "
      "TOKENIZERS_PARALLELISM=false setsid nohup /root/miniconda3/bin/python -u finetune_train.py "
      "--config config/finetune.gemma4.v11.json --base %s > %s 2>&1 < /dev/null & echo LAUNCHED"
      % (PKG, BASE, LOG), t=120)
time.sleep(120)
sh(c, "grep -aE 'trainable params|编码后保留|权重重采样|已冻结|总步数' %s | tail -6; tail -2 %s"
   % (LOG, LOG))
c.close()
print("\n已启动。", flush=True)
