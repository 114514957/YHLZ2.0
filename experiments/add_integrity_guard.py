# -*- coding: utf-8 -*-
"""给 restart_daemon_safe 加护栏：Low 完整性时拒绝重启生产链。

原因（台账 1267）：AI 的执行沙箱是 **Low** 完整性；从这里重启 daemon，
整条链（daemon→watchdog→bridge→QQ 注入）都会继承 Low，
而 QQ 跑在 Medium → **注入必然失败**，且写入受保护目录也会被拒。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "tools", "restart_daemon_safe.py")
t = io.open(P, encoding="utf-8").read()

if "integrity" not in t:
    # 在 main() 之前插一个检查函数，并在文件入口处调用
    anchor = "def main("
    guard = '''def _integrity_guard() -> None:
    """Low 完整性下不要重启生产链（会把整条链降级，QQ 就注入不了）。

    2026-11-16（台账 1267）：实测沙箱是 Low；QQ/NapCat 是 Medium。
    设 YHLZ_ALLOW_LOW_INTEGRITY=1 可强行跳过（不建议）。
    """
    if (os.getenv("YHLZ_ALLOW_LOW_INTEGRITY") or "").strip() in ("1", "true", "yes"):
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.integrity import level
        lv = level()
        if lv == "Low":
            print("⛔ 拒绝重启：当前进程是 Low 完整性，重启会把整条链降级，"
                  "QQ 将无法注入。\\n"
                  "   请在**普通终端（非管理员、非 AI 沙箱）**里运行：\\n"
                  "     python tools\\\\restart_daemon_safe.py\\n"
                  "   或设 YHLZ_ALLOW_LOW_INTEGRITY=1 强行继续（不建议）。")
            raise SystemExit(3)
        print("完整性级别：%s（允许重启）" % lv)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        return            # 取不到级别就不拦，避免误伤


'''
    if anchor in t:
        t = t.replace(anchor, guard + anchor, 1)
    else:
        t = guard + t
    # 在 __main__ 入口调用
    if '__main__' in t:
        t = t.replace('if __name__ == "__main__":',
                      'if __name__ == "__main__":\n    _integrity_guard()', 1)
    io.open(P, "w", encoding="utf-8").write(t)
    r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
    print("已加完整性护栏；编译:", "OK" if r.returncode == 0 else "失败")
else:
    print("护栏已存在")
