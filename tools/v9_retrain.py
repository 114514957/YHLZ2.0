#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V9 重训一键脚本（2026-10-25）。

**复用旧链路**，不重造：
  · `.tmp/sshx.py` 的连接方式（paramiko 密码登录）
  · `.tmp/autopull.py` 的多流断点续传拉取（7.5 GB 单流跑不完）
  · `.tmp/setup_all.sh` + `fix_launch.sh` 的步骤（装依赖→下模型→patch sliding_window→启动）

与上次的差别只有两处：
  1. 数据换 **v9t（5,959 条）**，不是 v9y（6,765 条）
  2. **epoch 3 → 1**（上次 eval_loss 在 step 400 触底 2.2432 后回升到 2.4116，后 869 步白训）

用法：
    set YH_SSH_PASS=xxx
    python tools/v9_retrain.py --host H --port P --setup      # 装环境+下模型+启动训练
    python tools/v9_retrain.py --host H --port P --status     # 看进度
    python tools/v9_retrain.py --host H --port P --pull       # 拉产物（断点续传）
"""
from __future__ import annotations

import argparse
import os
import posixpath
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".tmp"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PKG_TAR = os.path.join(ROOT, "dist", "retrain_pkg.tar.gz")
REMOTE_WORK = "/root/yh/retrain_pkg"
REMOTE_OUT = "/root/autodl-tmp/models/full/qwen3-4b-yuanheng-v9t"
REMOTE_LOG = "/root/autodl-tmp/logs/train_v9t.log"


def conn(a):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(a.host, port=int(a.port), username=a.user,
              password=a.password, timeout=40,
              banner_timeout=40, auth_timeout=40, look_for_keys=False)
    return c


def run(c, cmd, quiet=False, timeout=1800):
    tr = c.get_transport()
    ch = tr.open_session()
    ch.exec_command(cmd)
    buf, last = [], time.time()
    while True:
        if ch.recv_ready():
            d = ch.recv(8192).decode("utf-8", "replace")
            buf.append(d)
            if not quiet:
                sys.stdout.write("    " + d)
                sys.stdout.flush()
            last = time.time()
        if ch.recv_stderr_ready():
            d = ch.recv_stderr(8192).decode("utf-8", "replace")
            buf.append(d)
            if not quiet:
                sys.stdout.write("    " + d)
                sys.stdout.flush()
            last = time.time()
        if ch.exit_status_ready() and not ch.recv_ready():
            break
        if time.time() - last > timeout:
            buf.append("\n[超时]\n")
            break
        time.sleep(0.05)
    rc = ch.recv_exit_status()
    ch.close()
    return rc, "".join(buf)


def do_upload(c):
    if not os.path.exists(PKG_TAR):
        print("❌ 缺 %s（先跑打包）" % PKG_TAR)
        return 1
    print("  上传 %.2f MB …" % (os.path.getsize(PKG_TAR) / 1048576))
    run(c, "mkdir -p /root/yh /root/autodl-tmp/logs", quiet=True)
    s = c.open_sftp()
    s.put(PKG_TAR, "/root/yh/retrain_pkg.tar.gz")
    s.close()
    rc, out = run(c, "cd /root/yh && rm -rf retrain_pkg && mkdir retrain_pkg && "
                     "tar -xzf retrain_pkg.tar.gz -C retrain_pkg && ls retrain_pkg",
                  quiet=True)
    print("  远端解压：" + out.strip().replace("\n", " "))
    return 0 if rc == 0 else 1


def do_setup(c, skip_download=False):
    steps = []
    steps.append(("环境", "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; "
                          "df -h /root/autodl-tmp | tail -1; "
                          "/root/miniconda3/bin/python -V"))
    if not skip_download:
        steps.append(("装依赖",
                      "/root/miniconda3/bin/python -c 'import transformers,peft,datasets,accelerate' 2>/dev/null || "
                      "/root/miniconda3/bin/pip install -q 'transformers==5.20.2' 'peft==0.21.2' 'datasets==5.1.0' 'accelerate==1.15.0' "
                      "-i https://mirrors.aliyun.com/pypi/simple/ ; "
                      "/root/miniconda3/bin/python -c 'import bitsandbytes' 2>/dev/null || "
                      "/root/miniconda3/bin/pip install -q bitsandbytes==0.50.2 -i https://mirrors.aliyun.com/pypi/simple/ ; "
                      "/root/miniconda3/bin/python -c 'import modelscope' 2>/dev/null || "
                      "/root/miniconda3/bin/pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ ; "
                      "/root/miniconda3/bin/python -c "
                      "'import transformers,peft,datasets,accelerate,torch;"
                      "print(\"tf\",transformers.__version__,\"torch\",torch.__version__,torch.cuda.is_available())'"))
        steps.append(("下 Qwen3-4B",
                      "[ -f /root/autodl-tmp/models/Qwen3-4B/config.json ] || "
                      "/root/miniconda3/bin/modelscope download --model Qwen/Qwen3-4B "
                      "--local_dir /root/autodl-tmp/models/Qwen3-4B ; "
                      "ls /root/autodl-tmp/models/Qwen3-4B | head -8"))
        steps.append(("patch sliding_window",
                      "/root/miniconda3/bin/python - <<'EOF'\n"
                      "import json\n"
                      "p='/root/autodl-tmp/models/Qwen3-4B/config.json'\n"
                      "cfg=json.load(open(p))\n"
                      "print('before',cfg.get('sliding_window'))\n"
                      "if cfg.get('sliding_window') is None: cfg.pop('sliding_window',None)\n"
                      "json.dump(cfg,open(p,'w'),indent=2,ensure_ascii=False)\n"
                      "from transformers import AutoConfig\n"
                      "c=AutoConfig.from_pretrained('/root/autodl-tmp/models/Qwen3-4B')\n"
                      "print('OK sliding_window=',getattr(c,'sliding_window','<absent>'))\n"
                      "EOF"))
    steps.append(("数据核对",
                  "/root/miniconda3/bin/python - <<'EOF'\n"
                  "import io,json\n"
                  "for sp in ('train','val'):\n"
                  "    p='/root/yh/retrain_pkg/sft_persona_v9t_%s.jsonl'%sp\n"
                  "    rows=[json.loads(x) for x in io.open(p,encoding='utf-8') if x.strip()]\n"
                  "    print(sp,len(rows),'条')\n"
                  "    assert rows[0]['messages'][0]['role']=='system'\n"
                  "print('DATA_OK')\n"
                  "EOF"))
    steps.append(("dry-run",
                  "cd /root/yh/retrain_pkg && /root/miniconda3/bin/python finetune_train.py "
                  "--config config/finetune.qwen3-4b.v9t.1ep.json "
                  "--base /root/autodl-tmp/models/Qwen3-4B --dry-run"))
    for name, cmd in steps:
        print("\n== %s ==" % name)
        rc, out = run(c, cmd, quiet=False)
        if rc != 0:
            print("  ❌ %s 失败 rc=%d，停止" % (name, rc))
            return 1
    print("\n== 启动训练（后台）==")
    rc, out = run(c, "cd /root/yh/retrain_pkg && "
                     "TOKENIZERS_PARALLELISM=false nohup /root/miniconda3/bin/python "
                     "finetune_train.py --config config/finetune.qwen3-4b.v9t.1ep.json "
                     "--base /root/autodl-tmp/models/Qwen3-4B "
                     "> %s 2>&1 & echo TRAIN_PID=$!" % REMOTE_LOG, quiet=True)
    print("  " + out.strip())
    return 0


def do_status(c):
    rc, out = run(c, "pgrep -f 'finetune_train.py' >/dev/null && echo ALIVE || echo DEAD; "
                     "echo ---LOSS---; grep -a \"'loss'\" %s | tail -4; "
                     "echo ---EVAL---; grep -a eval_loss %s | tail -4; "
                     "echo ---TAIL---; tail -c 600 %s | tr '\\r' '\\n' | grep -a . | tail -6; "
                     "echo ---GPU---; nvidia-smi --query-gpu=memory.used,utilization.gpu "
                     "--format=csv,noheader; "
                     "echo ---OUT---; ls -la %s 2>/dev/null | head -8"
                     % (REMOTE_LOG, REMOTE_LOG, REMOTE_LOG, REMOTE_OUT), quiet=True)
    print(out)
    return 0


def do_pull(c):
    """模型 7.5 GB，单流约 0.12 MB/s → 必须多流 + 断点续传（沿用 autopull 的结论）。"""
    local = os.path.join(ROOT, "models", "full", "qwen3-4b-yuanheng-v9t")
    os.makedirs(local, exist_ok=True)
    s = c.open_sftp()
    try:
        files = s.listdir(REMOTE_OUT)
    except IOError as e:
        print("❌ 远端产物目录读不到：%s" % e)
        s.close()
        return 1
    want = [f for f in files if f.endswith((".json", ".safetensors", ".jinja", ".csv", ".md"))]
    print("  远端 %d 个文件，要拉 %d 个" % (len(files), len(want)))
    import threading
    lock = threading.Lock()
    total = {"done": 0, "bytes": 0}

    def grab(fn):
        remote = posixpath.join(REMOTE_OUT, fn)
        dst = os.path.join(local, fn)
        try:
            sz = s.stat(remote).st_size
            if os.path.exists(dst) and os.path.getsize(dst) == sz:
                with lock:
                    total["done"] += 1
                    total["bytes"] += sz
                print("  ⏭ %s（已存在且大小一致）" % fn)
                return
            s.get(remote, dst)
            with lock:
                total["done"] += 1
                total["bytes"] += sz
            print("  ✅ %-28s %8.1f MB" % (fn, sz / 1048576))
        except Exception as e:  # noqa: BLE001
            print("  ❌ %s：%s" % (fn, str(e)[:80]))

    # 小文件先串行（快），大权重单拉（SFTP 不能并发同一连接）
    small = [f for f in want if not f.endswith(".safetensors")]
    big = [f for f in want if f.endswith(".safetensors")]
    for fn in small:
        grab(fn)
    for fn in big:
        print("  拉权重 %s（大文件，慢）…" % fn)
        grab(fn)
    s.close()
    print("\n  合计 %.2f MB → %s" % (total["bytes"] / 1048576, local))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.environ.get("YH_SSH_PASS", ""))
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--skip-model", action="store_true", help="模型已下好，跳过下载")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if not a.password:
        print("❌ 需要密码：set YH_SSH_PASS=xxx 或 --password")
        return 2
    print("连接 %s@%s:%s …" % (a.user, a.host, a.port))
    try:
        c = conn(a)
    except Exception as e:  # noqa: BLE001
        print("❌ 连接失败：%s" % str(e)[:160])
        return 1
    print("  ✅ 已连接")
    try:
        if a.upload or a.all:
            print("\n== 上传 ==")
            if do_upload(c) != 0:
                return 1
        if a.setup or a.all:
            print("\n== 建环境 + 启动 ==")
            if do_setup(c, skip_download=a.skip_model) != 0:
                return 1
        if a.status or a.all:
            print("\n== 状态 ==")
            do_status(c)
        if a.pull:
            print("\n== 拉产物 ==")
            do_pull(c)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
