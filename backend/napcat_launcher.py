"""Launch NapCat through `qqwatch/shell/launcher-user.bat` (the non-admin entry).

Rolled back 2026-10-29 to the pre-admin-terminal arrangement the owner asked for:
the QQ bridge uses the same entry as `backend/yhlz_paths.NAPCAT_LAUNCHER`
(`launcher-user.bat <uin>`), never `launcher.bat` (which restarts itself with
`-Verb runAs`).

Two properties matter and are easy to break:

* `launcher-user.bat` builds every path from `%cd%`, so the child must start with
  its working directory set to the shell folder (台账 0793: an earlier `start /d`
  experiment broke exactly this).
* the login QR lives in that console window; the bridge only starts once QQ has
  finished logging in, which is why success is reported from TCP 3001 rather
  than from the launcher's exit code.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from backend.yhlz_paths import BOT_UIN, NAPCAT_WEBUI, QQWATCH_SHELL

ONEBOT_PORT = int(os.getenv("YHLZ_ONEBOT_PORT", "3001"))
# How long the workbench waits for the QR login before reporting "not yet online".
LOGIN_WAIT_S = float(os.getenv("YHLZ_NAPCAT_WAIT", "20"))


def is_elevated() -> bool:
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def launcher_bat() -> Path:
    """The non-admin NapCat entry (same value as yhlz_paths.NAPCAT_LAUNCHER)."""
    return Path(QQWATCH_SHELL) / "launcher-user.bat"


def onebot_online(port: int = ONEBOT_PORT, timeout: float = 0.4) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def wait_online(timeout_s: float = LOGIN_WAIT_S, port: int = ONEBOT_PORT) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        if onebot_online(port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def _kill_stale() -> None:
    """Remove a half-dead launcher/QQ left by a failed boot before relaunching.

    A stuck NapCatWinBootMain.exe keeps `tasklist` looking busy while nothing is
    listening, and a QQ without injection cannot log in either. Same effect as
    the old KillQQ.bat, scoped to these two images.
    """
    for image in ("NapCatWinBootMain.exe", "QQ.exe"):
        try:
            subprocess.run(["taskkill", "/f", "/im", image],
                           capture_output=True, timeout=15)
        except Exception:
            pass


def launch_napcat(uin: str = BOT_UIN) -> dict:
    uin = str(uin).strip()
    if not uin.isascii() or not uin.isdigit():
        raise ValueError("QQ 账号必须是数字")
    if is_elevated():
        raise PermissionError("NapCat 必须从非管理员工作台或普通 CMD 启动")
    if onebot_online():
        return {"started": True, "already": True, "elevated": False,
                "method": "none", "online": True,
                "note": f"NapCat 已在线（{ONEBOT_PORT} 在监听），无需重复启动"}

    launcher = launcher_bat()
    if not launcher.is_file():
        raise FileNotFoundError(f"找不到 NapCat 入口：{launcher}")
    # 3001 没在听：清掉卡住的 NapCatWinBootMain / 没注入的 QQ，再拉起新的。
    _kill_stale()
    # webui.json drives NapCat's own quick login; keep it in sync with the uin.
    if NAPCAT_WEBUI.is_file():
        data = json.loads(NAPCAT_WEBUI.read_text(encoding="utf-8-sig"))
        if str(data.get("autoLoginAccount")) != uin:
            data["autoLoginAccount"] = uin
            tmp = NAPCAT_WEBUI.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(NAPCAT_WEBUI)

    env = dict(os.environ)
    # A failed ticket must not trigger the local password fallback or another
    # automatic attempt. Only the account number enters this child.
    for key in ("NAPCAT_QUICK_PASSWORD", "NAPCAT_QUICK_PASSWORD_MD5"):
        env.pop(key, None)
    env["YHLZ_QUICK_UIN"] = uin

    proc = subprocess.Popen(
        [os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/c",
         f'call "{launcher}" {uin}'],
        cwd=str(QQWATCH_SHELL), env=env, close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    online = wait_online(LOGIN_WAIT_S)
    if not online:
        # A console created by the daemon is not the "regular terminal" QQ
        # needs to finish the injection; hand the entry to the user instead of
        # pretending it worked.
        try:
            subprocess.Popen(["explorer", "/select,", str(launcher)], close_fds=True)
        except Exception:
            pass
    return {"started": True, "already": False, "elevated": False,
            "method": "launcher_user", "pid": proc.pid, "online": online,
            "note": ("NapCat 已上线（3001 在监听）" if online else
                     "已尝试拉起；若窗口里没有二维码，请在已打开的文件夹里"
                     "双击 launcher-user.bat 用常规终端登录")}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--uin", default=BOT_UIN)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the resolved command and status without launching")
    options = parser.parse_args()
    if options.dry_run:
        print(json.dumps({
            "launcher": str(launcher_bat()),
            "cwd": str(QQWATCH_SHELL),
            "command": f'call "{launcher_bat()}" {options.uin}',
            "online": onebot_online(),
            "elevated": is_elevated(),
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(launch_napcat(options.uin), ensure_ascii=False))
