# -*- coding: utf-8 -*-
"""修 napcat_window：改用 explorer 打开 bat（在你的桌面会话里 = 双击，有真控制台）。

原因（2026-11-16 实测）：
  · daemon / 命令行都是**非交互进程**，`cmd /c start` 出来的批处理会因为没有真控制台
    在 `pause` 处直接退出（报 "Input redirection is not supported"），QQ 根本起不来；
  · `explorer.exe <bat>` 由**你的桌面会话**启动，等价于双击，控制台是真实的。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "backend", "console_server.py")
t = io.open(P, encoding="utf-8").read()

start = t.find('        if action == "napcat_window":')
end = t.find('        if action in ("napcat_login", "qq_switch"):', start)
assert start > 0 and end > start, "定位失败"

new_block = '''        if action == "napcat_window":
            # 2026-11-16（台账 1266）：用 explorer 在**用户桌面会话**里打开 launcher，
            # 等价于双击 —— daemon 是非交互进程，自己 start 出来的窗口没有真控制台，
            # bat 会在 pause 处退出（实测 QQ 根本起不来）。
            try:
                import subprocess as _sp
                shell = None
                for c in (_PROJECT_ROOT.parent.parent / "qqwatch" / "shell",
                          _PROJECT_ROOT.parent / "qqwatch" / "shell"):
                    if (c / "launcher-user.bat").exists():
                        shell = c
                        break
                if shell is None:
                    return {"ok": False, "error": "找不到 launcher-user.bat"}
                uin = str(body.get("uin", "") or BOT_UIN)
                # 包装一层：把 uin 传进去（explorer 不能带参数）
                wrap_dir = _PROJECT_ROOT / "cache" / "tmp"
                wrap_dir.mkdir(parents=True, exist_ok=True)
                wrap = wrap_dir / ("_login_%s.bat" % uin)
                wrap.write_text(
                    '@echo off\\r\\nchcp 65001 >nul\\r\\ncd /d "%s"\\r\\n'
                    'call launcher-user.bat %s\\r\\n' % (shell, uin),
                    encoding="gbk", errors="replace")
                _sp.Popen(["explorer.exe", str(wrap)], close_fds=True)
                _log("control", "napcat_window %s (explorer)" % uin)
                return {"ok": True,
                        "note": "已在桌面打开登录窗口（元亨号 %s）；窗口里扫码登录，"
                                "登录后再点「检查登录状态」" % uin}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": "%s: %s"
                        % (type(exc).__name__, str(exc)[:120])}
'''
t = t[:start] + new_block + t[end:]
io.open(P, "w", encoding="utf-8").write(t)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已改 napcat_window → explorer；编译:", "OK" if r.returncode == 0 else "失败")
