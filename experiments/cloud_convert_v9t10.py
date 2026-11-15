# -*- coding: utf-8 -*-
"""云端：装 gguf → 把 v9t10 转成 GGUF → 打一个**瘦包**（只要 36MB 那种）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
CONV = os.path.join(YH, "models", "llama-cuda", "src", "llama.cpp-b10991",
                    "convert_lora_to_gguf.py")
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
TAG = "v9t10"
LORA = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-%s" % TAG

import paramiko  # noqa: E402

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
          banner_timeout=30, auth_timeout=30)


def sh(cmd, t=3600):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()


print("[1] 传转换脚本（%d 字节）" % os.path.getsize(CONV))
s = c.open_sftp()
s.put(CONV, "/root/yh/convert_lora_to_gguf.py")
s.close()

print("[2] 装 gguf")
o, e = sh("/root/miniconda3/bin/pip install -q gguf 2>&1 | tail -3; "
          "/root/miniconda3/bin/python -c 'import gguf; print(\"gguf ok\")'", t=900)
print("  " + (o or e))

print("[3] 转 GGUF")
o, e = sh("cd /root/yh && /root/miniconda3/bin/python convert_lora_to_gguf.py "
          "--outfile /root/autodl-tmp/%s-lora.gguf --outtype f16 "
          "--base /root/autodl-tmp/models/gemma-4-e4b-it %s 2>&1 | tail -5" % (TAG, LORA), t=3600)
print("  " + (o or e))

print("[4] 打瘦包（GGUF + 配置 + 摘要 + 日志，不含 adapter 与 checkpoint）")
cmd = ("cd %s && tar -czf /root/autodl-tmp/%s_瘦包.tar.gz "
       "adapter_config.json chat_template.jinja README.md "
       "train_summary.json train_summary.md train_log.csv "
       "&& cp /root/autodl-tmp/%s-lora.gguf /root/autodl-tmp/ 2>/dev/null; "
       "ls -l /root/autodl-tmp/%s-lora.gguf /root/autodl-tmp/%s_瘦包.tar.gz" % (LORA, TAG, TAG, TAG, TAG))
o, e = sh(cmd, t=900)
print("  " + (o or e))
c.close()
