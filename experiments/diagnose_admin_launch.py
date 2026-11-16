# -*- coding: utf-8 -*-
"""查"为什么唤起会变成管理员终端"：
1. 注入器 / QQ 的 manifest 里 requestedExecutionLevel 是什么
2. 开机自启 .lnk 指向哪、有没有"以管理员身份运行"标记
"""
from __future__ import annotations

import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TARGETS = [
    r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell\NapCatWinBootMain.exe",
    r"C:\Program Files\Tencent\QQNT\QQ.exe",
    r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell\launcher-user.bat",
]
PATTERNS = ("requireAdministrator", "asInvoker", "highestAvailable",
            "requestedExecutionLevel")

for p in TARGETS:
    print("=" * 66)
    print(os.path.basename(p), "存在" if os.path.exists(p) else "❌ 不存在")
    if not os.path.exists(p):
        continue
    raw = open(p, "rb").read()
    for pat in PATTERNS:
        for enc in ("utf-8", "utf-16-le"):
            try:
                hit = raw.find(pat.encode(enc))
            except Exception:  # noqa: BLE001
                hit = -1
            if hit >= 0:
                s = max(0, hit - 90)
                chunk = raw[s:hit + 90]
                try:
                    txt = chunk.decode(enc, "ignore")
                except Exception:  # noqa: BLE001
                    txt = ""
                txt = re.sub(r"[\x00-\x1f]", " ", txt).strip()
                print("  ★ %-22s (%s) …%s…" % (pat, enc, txt[-140:]))
                break

print("\n" + "=" * 66)
print("开机自启目录的 .lnk")
startup = os.path.join(os.environ.get("APPDATA", ""),
                       "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
for p in glob.glob(os.path.join(startup, "*")):
    print("  %s  %d B" % (os.path.basename(p), os.path.getsize(p)))
    if not p.lower().endswith(".lnk"):
        continue
    raw = open(p, "rb").read()
    # 从 .lnk 里捞路径（UTF-16 / ASCII 两路）
    cands = set()
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){8,}", raw):
        try:
            t = m.group().decode("utf-16-le", "ignore")
        except Exception:  # noqa: BLE001
            continue
        if re.search(r"\.(exe|bat|ps1|vbs|cmd)$", t, re.I):
            cands.add(t)
    for c in sorted(cands)[:4]:
        print("      → %s" % c)
    for flag in ("RunAsAdmin", "runas", "highest"):
        if flag.lower().encode() in raw.lower():
            print("      ⚠ 含疑似提权标记：%s" % flag)
