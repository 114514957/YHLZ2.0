# -*- coding: utf-8 -*-
"""转 GGUF + 打包 stylepatch4（带重试，命令都很短）。"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER, PW = "connect.nma1.seetacloud.com", 39522, "root", "FSMqu7B3fRXc"
BASE = "/root/autodl-tmp/models/gemma-4-e4b-it"
ADP = "/root/autodl-tmp/models/lora/yuanheng-stylepatch4"
GGUF = "/root/autodl-tmp/yuanheng-stylepatch4-lora.gguf"
PACK = "/root/autodl-tmp/pack_stylepatch4.tar.gz"
LOCAL_CONV = os.path.join(YH, "models", "llama-cuda", "src", "llama.cpp-b10991",
                          "convert_lora_to_gguf.py")

import paramiko  # noqa: E402


def conn():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=60,
              banner_timeout=30, auth_timeout=30)
    return c


def run(cmd, t=600, retries=3):
    for i in range(retries):
        try:
            c = conn()
            _i, o, e = c.exec_command(cmd, timeout=t)
            o.channel.settimeout(t - 5)
            out = o.read().decode("utf-8", "replace").strip()
            c.close()
            return out
        except Exception as ex:  # noqa: BLE001
            print("    第 %d 次失败 %s，重试" % (i + 1, type(ex).__name__), flush=True)
            time.sleep(3)
    return ""


print("[1] 转换器在不在")
have = run("ls -l /root/yh/convert_lora_to_gguf.py 2>/dev/null || echo NO")
print("   %s" % have)
if "NO" in have:
    print("   上传转换器（本地 %d 字节）" % os.path.getsize(LOCAL_CONV))
    c = conn()
    s = c.open_sftp()
    s.put(LOCAL_CONV, "/root/yh/convert_lora_to_gguf.py")
    s.close()
    c.close()
    print("   %s" % run("ls -l /root/yh/convert_lora_to_gguf.py"))

print("\n[2] 转 GGUF")
print(run("cd /root/yh && /root/miniconda3/bin/python convert_lora_to_gguf.py "
          "--outfile %s --outtype f16 --base %s %s 2>&1 | tail -4" % (GGUF, BASE, ADP), t=1800))
print(run("ls -l %s 2>/dev/null || echo 没转成" % GGUF))

print("\n[3] 打包")
print(run("rm -f %s && tar -czf %s -C %s . -C /root/autodl-tmp yuanheng-stylepatch4-lora.gguf "
          "&& ls -l %s && sha256sum %s | cut -d' ' -f1" % (PACK, PACK, ADP, PACK, PACK), t=900))
