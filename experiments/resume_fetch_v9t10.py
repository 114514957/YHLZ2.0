# -*- coding: utf-8 -*-
"""断点续传下载 v9t10 的 adapter（链路会断，所以必须能续）。

用法：
    python resume_fetch_v9t10.py            # 续传到完整
    python resume_fetch_v9t10.py --status   # 只看进度

原理：SFTPFile 支持 seek，本地文件有多大就从哪儿接着读；
每次断线自动重连、最多重试 30 次，每轮 30 秒。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST, PORT, USER = "connect.nma1.seetacloud.com", 39522, "root"
PW = os.environ.get("YH_SSH_PASS", "")
REMOTE = "/root/autodl-tmp/models/lora/yuanheng-v9-gemma-v9t10"
LOCAL = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\lora\yuanheng-v9-gemma-v9t10"
FILES = [("adapter_model.safetensors", 139602808),
         ("adapter_config.json", 1168),
         ("chat_template.jinja", 18569),
         ("README.md", 5230),
         ("train_summary.json", 772),
         ("train_summary.md", 3488),
         ("train_log.csv", 3375)]


def size(p):
    return os.path.getsize(p) if os.path.exists(p) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        for n, want in FILES:
            have = size(os.path.join(LOCAL, n))
            print("  %-28s %12d / %12d  %5.1f%%" % (n, have, want, 100 * have / want))
        return 0

    if not PW:
        sys.exit("需要 YH_SSH_PASS")

    import paramiko
    os.makedirs(LOCAL, exist_ok=True)

    for name, want in FILES:
        lp = os.path.join(LOCAL, name)
        for attempt in range(1, 31):
            have = size(lp)
            if have >= want:
                print("  ✓ %-28s %d 字节（完整）" % (name, have))
                break
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(HOST, port=PORT, username=USER, password=PW,
                          timeout=30, banner_timeout=30, auth_timeout=30)
                s = c.open_sftp()
                rf = s.open(REMOTE + "/" + name, "rb")
                rf.seek(have)
                with open(lp, "ab") as f:
                    while True:
                        chunk = rf.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                rf.close()
                s.close()
                c.close()
            except Exception as ex:  # noqa: BLE001
                got = size(lp)
                print("  [重试 %2d] %-24s %d/%d（%s）"
                      % (attempt, name, got, want, type(ex).__name__), flush=True)
                time.sleep(5)
        else:
            print("  ✗ %s 30 次没下完（%d/%d）" % (name, size(lp), want))
            return 3

    print("\n全部就绪：")
    for n, _ in FILES:
        print("  %-28s %d" % (n, size(os.path.join(LOCAL, n))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
