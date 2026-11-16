# -*- coding: utf-8 -*-
"""普通终端一键启动元亨 QQ（2026-11-16）。

为什么要有这个：
  · `launcher-user.bat` 末尾有 `pause`，在**非交互/重定向**环境下必然报
    "Input redirection is not supported" 并立刻退出；
  · 实测：`NapCatWinBootMain.exe` 打印完 argv[1] 就**卡住等 stdin**——
    给它 `stdin=DEVNULL` 才会往下走。

用法（普通 CMD，不要管理员）：
    python tools\qq_login_terminal.py
    python tools\qq_login_terminal.py --wait 180

它会：写 loadNapCat.js → 设注入环境 → 清残留 → 起注入器 → 等 QQ.exe 与 3001 → 报状态。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHELL = r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell"
QQ_CANDIDATES = (
    r"C:\Program Files\Tencent\QQNT\QQ.exe",
    r"C:\Program Files (x86)\Tencent\QQNT\QQ.exe",
)
UIN = "3655185302"
WORK = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\cache\tmp"


def find_qq() -> str:
    for p in QQ_CANDIDATES:
        if os.path.exists(p):
            return p
    # 退路：注册表
    try:
        out = subprocess.run(
            ["reg", "query",
             r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows"
             r"\CurrentVersion\Uninstall\QQ", "/v", "UninstallString"],
            capture_output=True, text=True, timeout=10).stdout
        for tok in out.split():
            if tok.lower().endswith("uninstall.exe"):
                cand = os.path.join(os.path.dirname(tok.strip('"')), "QQ.exe")
                if os.path.exists(cand):
                    return cand
    except Exception:  # noqa: BLE001
        pass
    return ""


def state_q() -> dict:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open("http://127.0.0.1:8321/state", timeout=6) as f:
            return (json.loads(f.read().decode()) or {}).get("qq") or {}
    except Exception:  # noqa: BLE001
        return {}


def pids(name: str) -> int:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name],
                             capture_output=True, text=True, timeout=15).stdout
        return sum(1 for ln in out.splitlines() if name.lower() in ln.lower())
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=150, help="等登录的秒数")
    a = ap.parse_args()

    qq = find_qq()
    print("[1] QQ.exe: %s" % (qq or "❌ 找不到"))
    for f in ("NapCatWinBootMain.exe", "NapCatWinBootHook.dll", "napcat.mjs", "qqnt.json"):
        p = os.path.join(SHELL, f)
        print("    %s %s" % ("✅" if os.path.exists(p) else "❌", f))
    if not qq:
        return 1

    os.makedirs(WORK, exist_ok=True)
    load_js = os.path.join(WORK, "loadNapCat.js")
    open(load_js, "w", encoding="utf-8").write(
        '(async () => {await import("file:///%s")})()\n'
        % os.path.join(SHELL, "napcat.mjs").replace("\\", "/"))
    print("[2] loadNapCat.js 已写：%s" % load_js)

    print("[3] 清残留…")
    for n in ("QQ.exe", "NapCatWinBootMain.exe"):
        subprocess.run(["taskkill", "/F", "/IM", n], capture_output=True)
    time.sleep(2)

    env = dict(os.environ)
    env.update({
        "NAPCAT_PATCH_PACKAGE": os.path.join(SHELL, "qqnt.json"),
        "NAPCAT_LOAD_PATH": load_js,
        "NAPCAT_INJECT_PATH": os.path.join(SHELL, "NapCatWinBootHook.dll"),
        "NAPCAT_LAUNCHER_PATH": os.path.join(SHELL, "NapCatWinBootMain.exe"),
        "NAPCAT_MAIN_PATH": os.path.join(SHELL, "napcat.mjs").replace("\\", "/"),
    })
    print("[4] 起注入器（stdin=空，避免它等键盘）…")
    subprocess.Popen(
        [os.path.join(SHELL, "NapCatWinBootMain.exe"), qq,
         os.path.join(SHELL, "NapCatWinBootHook.dll"), UIN],
        cwd=SHELL, env=env,
        stdin=subprocess.DEVNULL,          # ★ 关键：它卡在等 stdin
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, creationflags=0x00000010)   # CREATE_NEW_CONSOLE
    time.sleep(6)
    print("    QQ.exe 进程数：%d｜注入器：%d" % (pids("QQ.exe"), pids("NapCatWinBootMain.exe")))

    print("[5] 等登录（最多 %d 秒）…" % a.wait)
    for i in range(max(1, a.wait // 5)):
        time.sleep(5)
        q = state_q()
        socks = 0
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, timeout=15).stdout
            socks = sum(1 for ln in out.splitlines()
                        if ":3001" in ln and "LISTENING" in ln)
        except Exception:  # noqa: BLE001
            pass
        print("    [%3ds] online=%s ws=%s｜3001=%d｜QQ=%d"
              % ((i + 1) * 5, q.get("online"), q.get("ws"), socks, pids("QQ.exe")))
        if q.get("online") and q.get("ws"):
            print("✅ 已登录")
            return 0
        if socks and not q.get("ws"):
            print("   ⏳ 3001 已起，QQ 已开窗口 —— 需要扫码登录")
            return 0
    print("⚠ 超时。若弹出 QQ 登录窗口，扫码即可；没窗口就说明注入未生效。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
