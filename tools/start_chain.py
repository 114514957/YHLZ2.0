# -*- coding: utf-8 -*-
"""普通终端一键启链（元亨）：daemon → QQ 桥 → 看门狗。

**必须在普通终端跑（不要管理员）**，双击 `tools\\start_chain.bat` 即可。
本脚本会先自检完整性级别：

  · High（管理员）→ **拒绝**并说明原因：管理员进程注入不进 QQ，
    而且会让整条链继承高权限，登录窗口反而变成"管理员终端"。
  · Low（AI 沙箱）→ **拒绝**：会让 daemon/桥全部降级，QQ 注入必失败。
  · Medium（普通用户）→ 正常启动。

这也是"为什么唤起总是变成管理员终端"的答案：不是 NapCat/QQ 要求提权
（两者 manifest 都是 asInvoker、注册表也没有 RUNASADMIN），
而是**启动它的父进程本身就是管理员**，子进程原样继承。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# 2026-11-16（台账 1270）：**用当前解释器**，不要写死 .venv 的 python.exe。
# 原因：`.venv\Scripts\python.exe` 带着 Low 强制标签，由它启动的子进程会一路 Low；
# 而系统 Python（`…\Programs\Python\Python312\python.exe`）没有标签，
# 从普通终端启动就是 Medium —— 这才是能注入 QQ 的级别。
# 依赖仍然来自 .venv\Lib\site-packages（由 start_chain_outside.bat 设 PYTHONPATH）。
PY = sys.executable


def _level() -> str:
    try:
        import integrity  # tools/integrity.py
        return integrity.level()
    except Exception:  # noqa: BLE001
        return "未知"


def main() -> int:
    lv = _level()
    print("完整性级别：%s" % lv)
    if lv == "High":
        print()
        print("⛔ 这是**管理员**终端，不能用来登录 QQ。")
        print("   原因：NapCatWinBootMain.exe 与 QQ.exe 的 manifest 都是 asInvoker，")
        print("   并不要求提权；一旦用管理员启动，子进程继承高权限，")
        print("   QQ 以普通权限运行时就会注入失败——这就是「唤起变成管理员终端」的来源。")
        print("   请关掉这个窗口，直接**双击** tools\\start_chain.bat（普通权限）。")
        return 2
    if lv == "Low":
        print()
        print("⛔ 当前是 Low（低）完整性 —— **不是你的操作问题，是项目的目录标签**。")
        # 2026-11-16（台账 1268）：实测 `…\YHLZ` 本身带着
        #   Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)
        # 也就是说：**从这棵树里启动的任何 exe 都会以 Low 运行**，
        # 包括 .venv 的 python。Low 无法注入 Medium 的 QQ、也无法写 Medium 目录
        # （qqwatch\shell 写不进去就是这个原因）。
        # 低权限进程只能降不能升，所以必须从**普通终端**改标签。
        print()
        print("   根因：目录 YHLZ 带 Low 强制标签，子文件全部继承 → exe 全以 Low 跑。")
        print("   修复：在你的**普通终端**（不是管理员、不是 AI 窗口）里执行一次：")
        print()
        print('     icacls "C:\\Users\\ACE_WAN——PROJECT\\YHLZ" '
              '/setintegritylevel (OI)(CI)Medium /T')
        print()
        print("   然后**重新双击** tools\\start_chain.bat（新开的进程才会是 Medium）。")
        return 3

    print("\n[1/3] 起 daemon（8321）…")
    subprocess.Popen([PY, "-B", "-m", "backend.target_daemon", "--port", "8321"],
                     cwd=ROOT, close_fds=True,
                     creationflags=0x00000008)  # DETACHED_PROCESS
    time.sleep(8)

    print("[2/3] 起 QQ 桥（lite）…")
    subprocess.run([PY, "-X", "utf8", os.path.join("tools", "qq_bridge_control.py"),
                    "start", "--profile", "lite",
                    "--config", os.path.join("config", "qq_bridge_lite.json")],
                   cwd=ROOT, timeout=240)

    print("[3/3] 状态：")
    try:
        import json
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open("http://127.0.0.1:8321/state", timeout=10) as f:
            q = (json.loads(f.read().decode()) or {}).get("qq") or {}
        print("   QQ：online=%s ws=%s bridge=%s"
              % (q.get("online"), q.get("ws"), q.get("bridge")))
        if not (q.get("online") and q.get("ws")):
            print("   → 还没登录：窗口里扫码，或点工作台「QQ」页的「打开登录窗口」")
    except Exception as ex:  # noqa: BLE001
        print("   取不到 /state：%s" % type(ex).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
