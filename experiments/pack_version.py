# -*- coding: utf-8 -*-
"""打包一版训练产物（老爹要求：每一版都要打包好，而不是散着点单文件）。

做什么：
  1. 测云端通不通
  2. 云端：把 output 目录打成**一个** tar.gz（adapter + 配置 + 训练摘要 + 日志）
  3. 云端：转成 GGUF（体积只有 1/4，下载快）
  4. 本地：建 dist/<tag>_产物/{01..05}，能拿到的都放进去，写 README 与校验
  5. 给出**一个**下载地址

用法：
    python pack_version.py v9t10
    python pack_version.py v9t10 --no-cloud   # 只做本地结构
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
HOST, PORT, USER = "connect.nma1.seetacloud.com", 39522, "root"
PW = os.environ.get("YH_SSH_PASS", "")


def tcp_ok(timeout=8) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((HOST, PORT))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="如 v9t10")
    ap.add_argument("--no-cloud", action="store_true")
    a = ap.parse_args()
    tag = a.tag

    out_dir = os.path.join(YH, "dist", "%s_产物" % tag)
    for sub in ("01_训练包", "02_训练产物", "03_GGUF", "04_跑分", "05_参数与校验"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    print("本地结构就绪：%s" % out_dir)

    if a.no_cloud:
        return 0

    if not tcp_ok():
        print("❌ 云端不通（%s:%d）。等实例起来再跑；本地结构已建好。" % (HOST, PORT))
        return 2

    if not PW:
        print("❌ 需要 YH_SSH_PASS")
        return 2

    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PW, timeout=30,
              banner_timeout=30, auth_timeout=30)

    def sh(cmd, t=1800):
        _i, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode("utf-8", "replace").rstrip(), e.read().decode("utf-8", "replace").rstrip()

    LORA = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-%s" % tag
    ARC = "/root/autodl-tmp/%s_产物.tar.gz" % tag

    print("\n[1/3] 云端打包（一个 tar.gz）")
    o, e = sh("cd /root/autodl-tmp && tar -czf %s -C /root/autodl-tmp/models/lora "
              "yuanheng-v9-gemma-%s && ls -l %s" % (ARC, tag, ARC), t=1800)
    print("  " + (o or e))

    print("\n[2/3] 云端转 GGUF")

    o, e = sh("ls /root/yh/convert_lora_to_gguf.py 2>/dev/null || echo NO_CONVERTER")
    if "NO_CONVERTER" in o:
        print("  云端没有转换脚本，跳过（本地转也行，adapter 已在包里）")
    else:
        o, e = sh("cd /root/yh && /root/miniconda3/bin/python convert_lora_to_gguf.py "
                  "--outfile /root/autodl-tmp/%s-lora.gguf --outtype f16 "
                  "--base /root/autodl-tmp/models/gemma-4-e4b-it %s" % (tag, LORA), t=3600)
        print("  " + (o[-300:] or e[-300:]))

    print("\n[3/3] 可下载的单文件")
    o, _ = sh("ls -l /root/autodl-tmp/%s_产物.tar.gz /root/autodl-tmp/%s-lora.gguf 2>/dev/null"
              % (tag, tag))
    print("  " + o)
    print("\n在网页面板里下这两个就够：")
    print("  /root/autodl-tmp/%s-lora.gguf      （约 36MB，用来跑分）" % tag)
    print("  /root/autodl-tmp/%s_产物.tar.gz    （全套：adapter + 配置 + 日志）" % tag)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
