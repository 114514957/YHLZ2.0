# -*- coding: utf-8 -*-
"""v9t7 云端驱动：探测 / 上传 / 开训 / 盯日志 / 收回 adapter。

密码只从环境变量 YH_SSH_PASS 读，不落任何文件（站规）。
用法：
    set YH_SSH_PASS=xxx
    python cloud_v9t7.py --host HOST --port PORT --probe
    python cloud_v9t7.py ... --upload
    python cloud_v9t7.py ... --run --watch 40
    python cloud_v9t7.py ... --fetch
"""
from __future__ import annotations

import argparse
import io
import os
import posixpath
import stat
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
LOCAL_TGZ = os.path.join(YH, "dist", "retrain_pkg_gemma_v9t7.tar.gz")
REMOTE_DIR = "/root/yh"
REMOTE_TGZ = "/root/yh/retrain_pkg_gemma_v9t7.tar.gz"
PKG = "/root/yh/retrain_pkg_gemma_v9t7"
LOG = "/root/autodl-tmp/logs/train_v9t7.log"
OUT = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t7"
LOCAL_LORA = os.path.join(YH, "models", "lora", "yuanheng-v9-gemma-v9t7")


def conn(a):
    import paramiko
    pw = a.password or os.environ.get("YH_SSH_PASS", "")
    if not pw:
        sys.exit("❌ 需要密码：先 set YH_SSH_PASS=xxx")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=int(a.port), username=a.user, password=pw,
              timeout=30, banner_timeout=30, auth_timeout=30)
    return c


def sh(c, cmd, timeout=300):
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o.rstrip(), e.rstrip()


PROBE = "; ".join([
    "echo '== GPU =='; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader",
    "echo '== 磁盘 =='; df -h /root/autodl-tmp | tail -1",
    "echo '== 基座 =='; ls -l /root/autodl-tmp/models/gemma-4-e4b-it/model.safetensors 2>/dev/null || echo '  缺基座'",
    "echo '== 包 =='; ls -l /root/yh/retrain_pkg_gemma_v9t7 2>/dev/null | head -6 || echo '  还没传'",
    "echo '== 显存占用 =='; nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader",
    "echo '== 进程 =='; ps aux | grep -c '[f]inetune_train'",
])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--run", action="store_true", help="解包 + 起训练（后台）")
    ap.add_argument("--watch", type=int, default=0, help="跑完盯多少轮日志（每 30 秒）")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--fetch-meta", action="store_true",
                    help="只拉 train_summary.json/md 与 train_log.csv")
    ap.add_argument("--exec", default="", help="直接跑一条远程命令")
    a = ap.parse_args()

    c = conn(a)
    try:
        if a.exec:
            o, e = sh(c, a.exec, timeout=1800)
            print(o)
            if e:
                print("[stderr]", e)
        if a.probe:
            o, e = sh(c, PROBE)
            print(o or e)

        if a.upload:
            size = os.path.getsize(LOCAL_TGZ)
            print("上传 %s（%.2f MB）→ %s" % (os.path.basename(LOCAL_TGZ),
                                              size / 1048576, REMOTE_TGZ))
            sh(c, "mkdir -p /root/yh")
            sftp = c.open_sftp()
            t0 = time.time()
            sftp.put(LOCAL_TGZ, REMOTE_TGZ)
            sftp.close()
            o, _ = sh(c, "ls -l %s" % REMOTE_TGZ)
            print("%s（%.1fs）" % (o, time.time() - t0))

        if a.run:
            cmd = ("cd /root/yh && tar -xzf %s && cd %s && "
                   "ls -l /root/autodl-tmp/models/gemma-4-e4b-it/model.safetensors && "
                   "bash run_v9t7.sh" % (REMOTE_TGZ, PKG))
            print("解包并启动训练…")
            o, e = sh(c, cmd, timeout=600)
            print(o)
            if e:
                print("[stderr]", e)

        if a.watch:
            for i in range(a.watch):
                time.sleep(30)
                o, _ = sh(c, "tail -c 600 %s 2>/dev/null | tr '\\r' '\\n' | grep -a . | tail -4" % LOG)
                print("[%3ds] %s" % ((i + 1) * 30, o.replace("\n", " | ")[:300]), flush=True)

        if a.poll:
            o, _ = sh(c, "tail -c 800 %s 2>/dev/null | tr '\\r' '\\n' | grep -a . | tail -6; "
                         "echo '---'; ls -l %s 2>/dev/null | head -5" % (LOG, OUT))
            print(o)

        if a.fetch:
            os.makedirs(LOCAL_LORA, exist_ok=True)
            sftp = c.open_sftp()
            names = ["adapter_model.safetensors", "adapter_config.json",
                     "chat_template.jinja", "README.md"]
            for n in names:
                rp = posixpath.join(OUT, n)
                lp = os.path.join(LOCAL_LORA, n)
                try:
                    sftp.get(rp, lp)
                    print("  ↓ %-28s %d 字节" % (n, os.path.getsize(lp)))
                except Exception as ex:  # noqa: BLE001
                    print("  ✗ %-28s %s" % (n, ex))
            sftp.close()

        if a.fetch_meta:
            os.makedirs(LOCAL_LORA, exist_ok=True)
            sftp = c.open_sftp()
            for n in ("train_summary.json", "train_summary.md", "train_log.csv"):
                try:
                    sftp.get(posixpath.join(OUT, n), os.path.join(LOCAL_LORA, n))
                    print("  ↓ %-24s %d 字节" % (n, os.path.getsize(os.path.join(LOCAL_LORA, n))))
                except Exception as ex:  # noqa: BLE001
                    print("  ✗ %-24s %s" % (n, ex))
            sftp.close()
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
