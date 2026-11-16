# -*- coding: utf-8 -*-
"""接管登录：用 quick_login.env 里的账号密码走 NapCat 快速登录（不扫码、不打印密码）。

流程：
  1. 读 quick_login.env（只把键值放进环境变量，**不回显**）
  2. 杀掉现有 QQ / NapCat（避免第二个实例）
  3. 用 launcher-user.bat <uin> 带环境变量重启（NapCat 读 env 走快速登录）
  4. 轮询 /state，等 online && ws
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN"
PROJ = os.path.join(ROOT, "---PROJECT") if False else r"C:\Users\ACE_WAN——PROJECT"
SHELL = os.path.join(PROJ, "qqwatch", "shell")
ENVF = os.path.join(SHELL, "config", "quick_login.env")

vals: dict[str, str] = {}
if not os.path.exists(ENVF):
    sys.exit("找不到 quick_login.env")
for ln in io.open(ENVF, encoding="utf-8", errors="replace"):
    ln = ln.strip()
    if not ln or ln.startswith("#") or "=" not in ln:
        continue
    k, v = ln.split("=", 1)
    vals[k.strip()] = v.strip()

acct = vals.get("NAPCAT_QUICK_ACCOUNT") or vals.get("ACCOUNT") or ""
has_pwd = bool(vals.get("NAPCAT_QUICK_PASSWORD") or vals.get("NAPCAT_QUICK_PASSWORD_MD5"))
print("账号：%s…（长度 %d）｜密码变量：%s"
      % (acct[:4], len(acct), "有" if has_pwd else "无"))
if not (acct and has_pwd):
    sys.exit("快速登录信息不全，无法自动登录")

env = dict(os.environ)
env["NAPCAT_QUICK_ACCOUNT"] = acct
if vals.get("NAPCAT_QUICK_PASSWORD"):
    env["NAPCAT_QUICK_PASSWORD"] = vals["NAPCAT_QUICK_PASSWORD"]
if vals.get("NAPCAT_QUICK_PASSWORD_MD5"):
    env["NAPCAT_QUICK_PASSWORD_MD5"] = vals["NAPCAT_QUICK_PASSWORD_MD5"]

print("① 清掉旧 QQ / NapCat 进程…")
for name in ("NapCatWinBootMain.exe", "QQ.exe"):
    subprocess.run(["taskkill", "/F", "/IM", name],
                   capture_output=True, text=True)
time.sleep(3)

print("② 启动 NapCat（等价于双击 bat，自带真控制台）…")
# 老爹 2026-11-16：QQ 桥必须用**普通终端**登录（管理员注入不进 QQ）。
# 而且 launcher-user.bat 末尾有 pause：stdin 被重定向就会
# "Input redirection is not supported" 立刻退出。
# 所以：写一个只含 call 的包装 bat，交给 os.startfile（= 资源管理器双击），
# 这样拿到的是真正的控制台，且不继承我们的 stdio。
wrapper = os.path.join(PROJ, "YHLZ", "YH", "cache", "tmp", "_yhlz_login_%s.bat" % acct)
os.makedirs(os.path.dirname(wrapper), exist_ok=True)
# qqwatch\shell 目录不可写（ACL），所以包装 bat 放在 cache，里面 cd 过去再 call。
io.open(wrapper, "w", encoding="gbk", errors="replace").write(
    '@echo off\r\nchcp 65001 >nul\r\ncd /d "%s"\r\ncall launcher-user.bat %s\r\n'
    % (SHELL, acct))
os.startfile(wrapper)          # noqa: S606 — Windows shell 执行，普通权限
print("   已开登录窗口：%s" % os.path.basename(wrapper))
print("   （窗口里若出现二维码，扫一下；我在后台等登录）")

print("③ 等登录（最多 90 秒）…")
import json
import urllib.request

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
last = ""
for i in range(18):
    time.sleep(5)
    try:
        with op.open("http://127.0.0.1:8321/state", timeout=8) as f:
            q = (json.loads(f.read().decode()) or {}).get("qq") or {}
        last = "online=%s ws=%s bridge=%s" % (q.get("online"), q.get("ws"), q.get("bridge"))
        print("   [%2ds] %s" % ((i + 1) * 5, last))
        if q.get("online") and q.get("ws"):
            print("✅ 登录成功（无需扫码）")
            sys.exit(0)
    except Exception as ex:  # noqa: BLE001
        print("   [%2ds] /state 取不到（%s）" % ((i + 1) * 5, type(ex).__name__))
print("⚠ 90 秒内未登录：%s" % last)
sys.exit(1)
