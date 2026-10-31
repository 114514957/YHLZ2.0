#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 云端远程执行（paramiko 版）。

为什么不用 ssh/scp 命令行：本机 OpenSSH 不支持密码参数，非交互环境下无法输密码；
paramiko 可以程序化密码登录，也能装公钥后转密钥。

密码**不写进任何文件**：从环境变量 `YH_SSH_PASS` 读，或用 `--password-stdin`。

用法：
    # 1) 装公钥（之后免密）
    set YH_SSH_PASS=xxx
    python tools/v9_remote_run.py --host H --port P --install-key

    # 2) 上传训练包
    python tools/v9_remote_run.py --host H --port P --upload

    # 3) 远程跑训练（实时回显）
    python tools/v9_remote_run.py --host H --port P --train

    # 4) 拉回产物 + 日志
    python tools/v9_remote_run.py --host H --port P --fetch

    # 一次做完 1-4
    python tools/v9_remote_run.py --host H --port P --all
"""
from __future__ import annotations

import argparse
import os
import posixpath
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                   ".ssh", "id_ed25519_yh")
REMOTE = "/root/autodl-tmp/yh"
TAR = "dist/v9_bundle_upload.tar.gz"


def connect(host, port, user, password=None, use_key=False, timeout=20):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(hostname=host, port=int(port), username=user, timeout=timeout,
              banner_timeout=timeout, auth_timeout=timeout)
    if use_key and os.path.exists(KEY):
        kw["key_filename"] = KEY
        kw["look_for_keys"] = False
        kw["allow_agent"] = False
    else:
        kw["password"] = password
        kw["look_for_keys"] = False
        kw["allow_agent"] = False
    c.connect(**kw)
    return c


def exec_stream(c, cmd, quiet=False):
    """执行并实时回显，返回 (rc, out)。"""
    tr = c.get_transport()
    ch = tr.open_session()
    ch.exec_command(cmd)
    buf = []
    last = time.time()
    while True:
        if ch.recv_ready():
            d = ch.recv(4096).decode("utf-8", "replace")
            buf.append(d)
            if not quiet:
                sys.stdout.write("    " + d)
                sys.stdout.flush()
            last = time.time()
        if ch.recv_stderr_ready():
            d = ch.recv_stderr(4096).decode("utf-8", "replace")
            buf.append(d)
            if not quiet:
                sys.stdout.write("    " + d)
                sys.stdout.flush()
            last = time.time()
        if ch.exit_status_ready() and not ch.recv_ready():
            break
        if time.time() - last > 1800:      # 半小时没输出就认超时
            buf.append("\n[超时] 30 分钟无输出\n")
            break
        time.sleep(0.05)
    rc = ch.recv_exit_status()
    ch.close()
    return rc, "".join(buf)


def do_install_key(c):
    pub = KEY + ".pub"
    if not os.path.exists(pub):
        print("❌ 没有公钥 %s" % pub)
        return 1
    key = open(pub, encoding="utf-8").read().strip()
    cmd = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
           "grep -qF '%s' ~/.ssh/authorized_keys 2>/dev/null || "
           "echo '%s' >> ~/.ssh/authorized_keys; "
           "chmod 600 ~/.ssh/authorized_keys; echo KEY_INSTALLED" % (key, key))
    rc, out = exec_stream(c, cmd, quiet=True)
    ok = "KEY_INSTALLED" in out
    print(("  ✅ " if ok else "  ❌ ") + "公钥已装" if ok else "  ❌ 装公钥失败")
    return 0 if ok else 1


def do_upload(c, remote=REMOTE, local_tar=TAR):
    tar = os.path.join(ROOT, local_tar)
    if not os.path.exists(tar):
        print("❌ 找不到 %s" % tar)
        return 1
    sz = os.path.getsize(tar)
    print("  上传 %s（%.2f MB）…" % (local_tar, sz / 1048576))
    exec_stream(c, "mkdir -p %s/meta" % remote, quiet=True)
    t0 = time.time()
    sftp = c.open_sftp()
    sftp.put(tar, remote + "/meta/bundle.tar.gz")
    sftp.close()
    print("  ✅ 上传完成，用时 %.1f 秒" % (time.time() - t0))
    rc, out = exec_stream(
        c, "cd %s/meta && rm -rf app && mkdir -p app && "
           "tar -xzf bundle.tar.gz -C app && ls app", quiet=True)
    print("  远端解压：" + out.strip().replace("\n", " "))
    return 0 if rc == 0 else 1


def do_train(c, remote=REMOTE, config="config/finetune_v9_cloud.json",
             epochs="", background=False):
    e = ""
    if epochs:
        e = ("sed -i 's/\"epochs\": [0-9]*/\"epochs\": %s/' %s && "
             % (epochs, config))
    cmd = ("cd %s/meta/app && %s nohup bash run.sh %s "
           "> train_console.log 2>&1 & echo STARTED $!" % (remote, e, config)) \
        if background else \
        ("cd %s/meta/app && %s bash run.sh %s" % (remote, e, config))
    if background:
        rc, out = exec_stream(c, cmd, quiet=True)
        print("  " + out.strip())
        return 0
    t0 = time.time()
    rc, out = exec_stream(c, cmd)
    print("\n  训练结束 rc=%s，用时 %.1f 分钟" % (rc, (time.time() - t0) / 60))
    return 0 if rc == 0 else rc


def do_fetch(c, remote=REMOTE):
    sftp = c.open_sftp()
    out_dir = os.path.join(ROOT, "dist", "cloud_out")
    os.makedirs(out_dir, exist_ok=True)
    # 找产物包与日志
    rc, out = exec_stream(
        c, "ls -1t %s/meta/app/v9_train_artifacts_*.tar.gz 2>/dev/null | head -1; "
           "echo '---'; "
           "ls -1t %s/meta/app/train_*.log 2>/dev/null | head -1; "
           "echo '---'; "
           "ls -1t %s/meta/app/train_console.log 2>/dev/null | head -1"
        % (remote, remote, remote), quiet=True)
    parts = [p.strip() for p in out.split("---")]
    got = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        fn = posixpath.basename(p)
        local = os.path.join(out_dir, fn)
        try:
            sftp.get(p, local)
            got.append((fn, os.path.getsize(local)))
        except Exception as e:  # noqa: BLE001
            print("  ⚠ 拉取 %s 失败：%s" % (fn, str(e)[:60]))
    sftp.close()
    if not got:
        print("  ❌ 没拉到任何产物")
        return 1
    for fn, sz in got:
        print("  ✅ %s（%.1f MB）" % (fn, sz / 1048576))
    # 自动校验产物包
    for fn, _ in got:
        if fn.endswith(".tar.gz") and fn.startswith("v9_train_artifacts"):
            import subprocess
            subprocess.call([sys.executable,
                             os.path.join(ROOT, "tools", "v9_collect_training.py"),
                             "--verify", os.path.join(out_dir, fn)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="", help="不推荐；优先用环境变量 YH_SSH_PASS")
    ap.add_argument("--use-key", action="store_true", help="已有公钥时用密钥登录")
    ap.add_argument("--install-key", action="store_true")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--train-bg", action="store_true", help="后台跑，立刻返回")
    ap.add_argument("--epochs", default="")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--probe", action="store_true", help="只探测环境")
    a = ap.parse_args()

    pw = a.password or os.environ.get("YH_SSH_PASS", "")
    if not a.use_key and not pw:
        print("❌ 需要密码：设环境变量 YH_SSH_PASS，或传 --password；"
              "已装公钥则加 --use-key")
        return 2

    print("连接 %s@%s:%s（%s）…" % (a.user, a.host, a.port,
                                   "密钥" if a.use_key else "密码"))
    try:
        c = connect(a.host, a.port, a.user, pw, a.use_key)
    except Exception as e:  # noqa: BLE001
        print("❌ 连接失败：%s" % str(e)[:160])
        return 1
    print("  ✅ 已连接")

    try:
        if a.probe or a.all:
            print("\n== 环境探测 ==")
            rc, out = exec_stream(
                c, "nvidia-smi --query-gpu=name,memory.total,driver_version "
                   "--format=csv,noheader 2>&1; echo '---'; "
                   "python3 -V 2>&1; echo '---'; "
                   "python3 -c 'import torch;print(\"torch\",torch.__version__,"
                   "torch.cuda.is_available())' 2>&1 | tail -3; echo '---'; "
                   "df -h /root | tail -1", quiet=True)
            for ln in out.strip().split("\n"):
                if ln.strip():
                    print("  " + ln.strip())
        if a.install_key or a.all:
            print("\n== 装公钥 ==")
            if do_install_key(c) != 0:
                return 1
        if a.upload or a.all:
            print("\n== 上传 ==")
            if do_upload(c) != 0:
                return 1
        if a.train or a.all:
            print("\n== 训练 ==")
            do_train(c, epochs=a.epochs)
        if a.train_bg:
            print("\n== 后台训练 ==")
            do_train(c, epochs=a.epochs, background=True)
        if a.fetch or a.all:
            print("\n== 拉回产物 ==")
            do_fetch(c)
    finally:
        c.close()
        print("\n连接已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
