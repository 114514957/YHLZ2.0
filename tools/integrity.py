# -*- coding: utf-8 -*-
"""完整性级别（Integrity Level）自检 —— 防止"低权限启动生产链"这类事故。

背景（2026-11-16，台账 1267）：
  · `NapCatWinBootMain.exe` 与 `QQ.exe` 的 manifest 都是 **asInvoker**（不要求管理员）；
  · 注册表没有 RUNASADMIN 兼容标记，也没有相关计划任务；
  · 但实测发现：**整套 YH 栈（daemon / bridge / watchdog）都跑在 Low 完整性**，
    因为我们（AI 的执行沙箱）是 Low，从里面重启的进程全部继承 Low。
  · Low 进程**注入不了** Medium 的 QQ（UIPI 拦截），也无法往受保护目录写文件
    → 表现就是"唤起失败 / 写不进去"。

用法：
    python tools/integrity.py            # 打印本进程与关键进程的级别
    from tools.integrity import level   # 代码里判断
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25

_NAMES = {"S-1-16-4096": "Low", "S-1-16-8192": "Medium",
          "S-1-16-8448": "MediumPlus", "S-1-16-12288": "High",
          "S-1-16-16384": "System"}

adv = ctypes.windll.advapi32
k32 = ctypes.windll.kernel32


class _SID_ATTR(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class _TOKEN_LABEL(ctypes.Structure):
    _fields_ = [("Label", _SID_ATTR)]


def level(pid: int = 0) -> str:
    """返回 'Low' / 'Medium' / 'High' / 'System' / '取不到'。pid=0 表示自己。"""
    if not pid:
        pid = os.getpid()
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "取不到"
    try:
        tok = wt.HANDLE()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return "取不到"
        try:
            need = wt.DWORD()
            adv.GetTokenInformation(tok, TokenIntegrityLevel, None, 0,
                                    ctypes.byref(need))
            buf = ctypes.create_string_buffer(need.value)
            if not adv.GetTokenInformation(tok, TokenIntegrityLevel, buf, need,
                                           ctypes.byref(need)):
                return "取不到"
            tml = ctypes.cast(buf, ctypes.POINTER(_TOKEN_LABEL)).contents
            adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(ctypes.c_wchar_p)]
            out = ctypes.c_wchar_p()
            if not adv.ConvertSidToStringSidW(
                    ctypes.cast(tml.Label.Sid, ctypes.c_void_p), ctypes.byref(out)):
                return "取不到"
            return _NAMES.get(out.value or "", out.value or "?")
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def is_low(pid: int = 0) -> bool:
    return level(pid) == "Low"


def main() -> int:
    print("本进程：%d → %s" % (os.getpid(), level()))
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                         text=True, encoding="mbcs", errors="replace",
                         timeout=60).stdout
    rows = []
    for ln in out.splitlines():
        parts = [p.strip('"') for p in ln.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            rows.append((int(parts[1]), parts[0]))
    want = ("python.exe", "pythonw.exe", "QQ.exe", "NapCatWinBootMain.exe",
            "node.exe")
    print("\n%-7s %-6s %-24s %s" % ("PID", "父PID", "映像", "级别"))
    for pid, img in rows:
        if img in want:
            print("%-7d %-6d %-24s %s" % (pid, _parent(pid), img, level(pid)))
    return 0


class _PBI(ctypes.Structure):
    _fields_ = [("ExitStatus", wt.LONG), ("Peb", ctypes.c_void_p),
                ("Affinity", ctypes.c_void_p), ("BasePriority", wt.LONG),
                ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


def _parent(pid: int) -> int:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        pbi = _PBI()
        ret = ctypes.c_ulong(0)
        if ctypes.windll.ntdll.NtQueryInformationProcess(
                wt.HANDLE(h), 0, ctypes.byref(pbi), ctypes.sizeof(pbi),
                ctypes.byref(ret)) != 0:
            return 0
        return int(pbi.InheritedFromUniqueProcessId or 0)
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
