# -*- coding: utf-8 -*-
"""查关键进程的完整性级别（Low/Medium/High/System）。

为什么：`NapCatWinBootMain.exe` 与 `QQ.exe` 的 manifest 都是 **asInvoker**（不要求管理员），
所以"唤起变成管理员终端"只能是**父进程**本身在高完整性级别 → 子进程继承。
QQ 跑在 Medium，注入器若在 High 就注不进去（UIPI 拦截）——这正是唤起失败的机制。

只用普通权限（PROCESS_QUERY_LIMITED_INFORMATION），不提权。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25

LEVELS = {"S-1-16-4096": "Low(低)", "S-1-16-8192": "Medium(中)",
          "S-1-16-8448": "MediumPlus", "S-1-16-12288": "High(管理员)",
          "S-1-16-16384": "System"}

adv = ctypes.windll.advapi32
k32 = ctypes.windll.kernel32


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def sid_to_str(sid_ptr: int) -> str:
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_wchar_p)]
    out = ctypes.c_wchar_p()
    if adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
        return out.value or ""
    return ""


def integrity(pid: int) -> str:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "取不到(权限)"
    try:
        tok = wt.HANDLE()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return "无 token"
        try:
            need = wt.DWORD()
            adv.GetTokenInformation(tok, TokenIntegrityLevel, None, 0,
                                    ctypes.byref(need))
            buf = ctypes.create_string_buffer(need.value)
            if not adv.GetTokenInformation(tok, TokenIntegrityLevel, buf,
                                           need, ctypes.byref(need)):
                return "读取失败"
            tml = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
            sid = sid_to_str(ctypes.cast(tml.Label.Sid, ctypes.c_void_p))
            return "%s %s" % (sid, LEVELS.get(sid, ""))
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def procs() -> list[tuple[int, str]]:
    """用 tasklist 取 PID/映像（wmic 在 Win11 已移除）。"""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True,
                         encoding="mbcs", errors="replace", timeout=60).stdout
    rows = []
    for ln in out.splitlines():
        parts = [p.strip('"') for p in ln.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            rows.append((int(parts[1]), parts[0]))
    return rows


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("ExitStatus", wt.LONG), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_void_p),
                ("BasePriority", wt.LONG), ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


def parent_of(pid: int) -> int:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        pbi = PROCESS_BASIC_INFORMATION()
        ret = ctypes.c_ulong(0)
        ntdll = ctypes.windll.ntdll
        st = ntdll.NtQueryInformationProcess(
            wt.HANDLE(h), 0, ctypes.byref(pbi), ctypes.sizeof(pbi),
            ctypes.byref(ret))
        if st != 0:
            return 0
        return int(pbi.InheritedFromUniqueProcessId or 0)
    except Exception:  # noqa: BLE001
        return 0
    finally:
        k32.CloseHandle(h)


WANT = ("python.exe", "pythonw.exe", "QQ.exe", "NapCatWinBootMain.exe",
        "cmd.exe", "node.exe", "WindowsTerminal.exe", "conhost.exe")

print("%-7s %-6s %-24s %s" % ("PID", "父PID", "映像", "完整性级别"))
print("-" * 78)
me = os.getpid()
targets = [(pid, img) for pid, img in procs() if img in WANT]
for pid, img in targets:
    if pid == me:
        continue
    print("%-7d %-6d %-24s %s" % (pid, parent_of(pid), img, integrity(pid)))

print("\n本进程：%d → %s" % (me, integrity(me)))
