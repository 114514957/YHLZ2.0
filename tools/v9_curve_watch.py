#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量微调曲线盯盘（老爹 2026-10-25：「全量的时候盯紧曲线」）。

为什么专门盯：上次全参微调 3 epoch，train loss 一路降到 0.98，但 **eval_loss 在
step 400 触底 2.2432 后回升到 2.4116**——过拟合没及时看出来，白训 869 步。

盯这四件事：
  1. **eval_loss 走势**：必须单调向下（允许小波动）。连续 2 次上升 = 报警
  2. **train/eval 差距**：train 猛降而 eval 不动/上升 = 过拟合
  3. **grad_norm**：持续 >50 说明不稳（lr 偏大）
  4. **loss 尖峰**：单点跳 >1.5 倍 = 数据有问题

用法：
    set YH_SSH_PASS=xxx
    python tools/v9_curve_watch.py --host H --port P --every 60
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOG = "/root/autodl-tmp/logs/train_v9t.log"

RE_LOSS = re.compile(r"\{'loss': '([\d.]+)'.*?'grad_norm': '([\d.]+)'.*?'learning_rate': '([\d.e-]+)'.*?'epoch': '([\d.]+)'\}")
RE_EVAL = re.compile(r"\{'eval_loss': '([\d.]+)'.*?'epoch': '([\d.]+)'\}")
RE_STEP = re.compile(r"\|\s*(\d+)/(\d+)\s*\[")


def connect(host, port, user, pw):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=int(port), username=user, password=pw,
              timeout=40, banner_timeout=40, auth_timeout=40, look_for_keys=False)
    return c


def sh(c, cmd, timeout=90):
    _i, so, se = c.exec_command(cmd, timeout=timeout)
    out = so.read().decode("utf-8", "replace")
    return out


def parse(c):
    txt = sh(c, "grep -a \"'loss'\" %s; echo '===EVAL==='; "
                "grep -a eval_loss %s; echo '===STEP==='; "
                "tail -c 800 %s | tr '\\r' '\\n' | grep -a '|'; echo '===PROC==='; "
                "pgrep -f finetune_train.py >/dev/null && echo ALIVE || echo DEAD; "
                "echo '===DISK==='; df -h /root/autodl-tmp | tail -1"
                % (LOG, LOG, LOG), timeout=120)
    losses, evals, step = [], [], None
    proc, disk = "?", "?"
    sect = "loss"
    for ln in txt.split("\n"):
        if "===EVAL===" in ln:
            sect = "eval"
            continue
        if "===STEP===" in ln:
            sect = "step"
            continue
        if "===PROC===" in ln:
            sect = "proc"
            continue
        if "===DISK===" in ln:
            sect = "disk"
            continue
        m = RE_LOSS.search(ln)
        if m and sect == "loss":
            losses.append((float(m.group(1)), float(m.group(2)),
                           float(m.group(3)), float(m.group(4))))
            continue
        m = RE_EVAL.search(ln)
        if m and sect == "eval":
            evals.append((float(m.group(1)), float(m.group(2))))
            continue
        if sect == "step":
            m = RE_STEP.search(ln)
            if m:
                step = (int(m.group(1)), int(m.group(2)))
        elif sect == "proc" and ln.strip():
            proc = ln.strip()
        elif sect == "disk" and "autodl-tmp" in ln:
            disk = ln.strip()
    return losses, evals, step, proc, disk


def judge(losses, evals):
    """返回 (状态, 报警列表)。"""
    alerts = []
    if len(evals) >= 2:
        cur, prev = evals[-1][0], evals[-2][0]
        if cur > prev:
            alerts.append("eval_loss 上升：%.4f → %.4f（+%.1f%%）"
                          % (prev, cur, 100 * (cur - prev) / prev))
        if len(evals) >= 3 and evals[-1][0] > evals[-2][0] > evals[-3][0]:
            alerts.append("eval_loss **连续 2 次上升** → 过拟合前兆，考虑停")
        best = min(e for e, _ in evals)
        if cur > best * 1.03:
            alerts.append("当前 eval %.4f 已比最佳 %.4f 高 %.1f%%"
                          % (cur, best, 100 * (cur - best) / best))
    if len(losses) >= 3:
        r = [x[0] for x in losses[-3:]]
        if r[2] > r[0] * 1.5:
            alerts.append("train loss 尖峰：%.3f → %.3f" % (r[0], r[2]))
    if len(losses) >= 6:
        half = len(losses) // 2
        a = sum(x[0] for x in losses[:half]) / half
        b = sum(x[0] for x in losses[half:]) / (len(losses) - half)
        if b > a * 1.05:
            alerts.append("train loss 后半段高于前半段（%.3f → %.3f）" % (a, b))
    gn = [x[1] for x in losses[-6:]]
    if gn and max(gn) > 50:
        alerts.append("grad_norm 偏大（近 6 次最大 %.1f）→ lr 可能偏大" % max(gn))
    if evals and len(losses) >= 4:
        tl = sum(x[0] for x in losses[-4:]) / 4
        el = evals[-1][0]
        if el > tl * 1.5 and tl < 1.5:
            alerts.append("train(%.3f) 远低于 eval(%.3f) → 过拟合特征" % (tl, el))
    if not alerts:
        return "正常", []
    severe = any(("过拟合" in a) or ("连续 2 次上升" in a) for a in alerts)
    return ("**过拟合预警**" if severe else "注意"), alerts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default=os.environ.get("YH_SSH_PASS", ""))
    ap.add_argument("--every", type=int, default=60, help="轮询间隔秒")
    ap.add_argument("--rounds", type=int, default=0, help="0=一直盯到训练结束")
    a = ap.parse_args()
    if not a.password:
        print("❌ 需要 YH_SSH_PASS")
        return 2
    c = connect(a.host, a.port, a.user, a.password)
    print("已连接，开始盯曲线（间隔 %ds）\n" % a.every)
    rnd = 0
    prev_state = None
    try:
        while True:
            rnd += 1
            losses, evals, step, proc, disk = parse(c)
            st, alerts = judge(losses, evals)
            print("=" * 70)
            print("[第 %d 轮 %s] 进程=%s  进度=%s" % (
                rnd, time.strftime("%H:%M:%S"), proc,
                ("%d/%d (%.0f%%)" % (step[0], step[1], 100 * step[0] / step[1])) if step else "?"))
            print("  " + disk)
            if losses:
                print("  train loss 最近 6 次：%s" % ", ".join("%.3f" % x[0] for x in losses[-6:]))
                print("  grad_norm 最近 3 次：%s   lr=%.3e"
                      % (", ".join("%.1f" % x[1] for x in losses[-3:]), losses[-1][2]))
            if evals:
                print("  eval_loss：%s" % ", ".join("%.4f(ep%.2f)" % (e, ep) for e, ep in evals))
                best = min(e for e, _ in evals)
                print("  eval 最佳 %.4f｜当前 %.4f" % (best, evals[-1][0]))
            print("  判定：%s" % st)
            for x in alerts:
                print("    ⚠ " + x)
            if proc == "DEAD":
                print("\n训练进程已结束。")
                break
            if a.rounds and rnd >= a.rounds:
                break
            time.sleep(a.every)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
