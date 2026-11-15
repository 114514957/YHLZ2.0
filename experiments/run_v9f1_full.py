# -*- coding: utf-8 -*-
"""上传 v9f1 全量包 → 量训练前 PPL → 开训 → 报日志。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
PKG = os.path.join(YH, "dist", "retrain_pkg_gemma_v9f1")

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=14400):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


o, _ = sh("df -h /root/autodl-tmp | tail -1; nvidia-smi --query-gpu=memory.free --format=csv,noheader")
print("环境：%s" % o)

s = c.open_sftp()
s.put(os.path.join(YH, "experiments", "ppl_probe.py"), "/root/yh/ppl_probe.py")
sh("mkdir -p /root/yh/retrain_pkg_gemma_v9f1/config")
for f in ("finetune_train.py", "preflight_mlp.py",
          "sft_persona_v9f1_train.jsonl", "sft_persona_v9f1_val.jsonl"):
    s.put(os.path.join(PKG, f), "/root/yh/retrain_pkg_gemma_v9f1/" + f)
s.put(os.path.join(PKG, "config", "finetune.gemma4.v9f1full.json"),
      "/root/yh/retrain_pkg_gemma_v9f1/config/finetune.gemma4.v9f1full.json")
s.close()
print("\n包已上传")
o, _ = sh("wc -l /root/yh/retrain_pkg_gemma_v9f1/*.jsonl")
print(o)

print("\n== 训练前 PPL（遗忘基线）==")
o, e = sh("cd /root/yh && /root/miniconda3/bin/python -u ppl_probe.py "
          "--model /root/autodl-tmp/models/gemma-4-e4b-it --tag base "
          "2>&1 | grep -v 'Loading weights' | tail -3", t=1800)
print(o or e)

print("\n== 开训（全量，949 步）==")
o, e = sh("cd /root/yh/retrain_pkg_gemma_v9f1 && "
          "nohup /root/miniconda3/bin/python -u finetune_train.py "
          "--config config/finetune.gemma4.v9f1full.json "
          "--base /root/autodl-tmp/models/gemma-4-e4b-it "
          "> /root/autodl-tmp/logs/full_v9f1.log 2>&1 & echo LAUNCHED", t=120)
print(o or e)
time.sleep(120)
o, _ = sh("grep -aE '冻结|全量模式|可训练|编码后保留|权重重采样' /root/autodl-tmp/logs/full_v9f1.log | tail -8; "
          "tail -3 /root/autodl-tmp/logs/full_v9f1.log")
print("\n启动后 2 分钟日志：\n%s" % o)
c.close()
