# -*- coding: utf-8 -*-
"""提交：完整性自检 + 启链护栏 + 普通终端一键启链，并记文档。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
DOC = os.path.join(ROOT, "docs", "方案", "完整性级别与QQ登录_20261116.md")

io.open(DOC, "w", encoding="utf-8").write("""# 为什么会变成“管理员终端”，以及怎么彻底用普通终端

> 2026-11-16。老爹问：「研究清楚为什么唤起总是变成管理员终端」。

## 一、先排除系统层面的“强制提权”

| 检查项 | 结果 | 说明 |
|---|---|---|
| `NapCatWinBootMain.exe` manifest | **asInvoker** | 不要求管理员 |
| `QQ.exe` manifest | **asInvoker** | 不要求管理员 |
| 注册表 `AppCompatFlags\\Layers` 的 RUNASADMIN | **无** | 没人给它们打“以管理员运行”的兼容标记 |
| 计划任务（含提权运行） | **无** | 没有相关任务 |
| 开机自启 | 三个 `.lnk.disabled` | 目前是**禁用**状态 |

→ **没有任何系统设置强迫它提权。**

## 二、那“管理员终端”从哪来

**来自父进程继承**：Windows 子进程默认继承父进程的完整性级别。
如果启动器（或工作台、或 daemon）本身跑在管理员终端里，
它 `start` 出来的窗口就是“管理员: …”，NapCat/QQ 也随之在高权限下运行。

而 QQ 本体是普通权限，**高权限进程注入普通权限进程会被 UIPI 拦**——
所以“用管理员启动反而登录失败”，这和老爹的经验完全一致。

## 三、更隐蔽的反向问题：Low（低）完整性

实测发现：**整套 YH 栈（daemon / QQ 桥 / 看门狗）都跑在 Low**，
因为它们的父进程是 AI 的执行沙箱（沙箱本身是 Low）。
Low 进程**注入不了** Medium 的 QQ，写受保护目录也会被拒。

| 进程 | 级别 |
|---|---|
| daemon / bridge / watchdog（由沙箱重启过的） | **Low** |
| QQ（正常双击启动） | Medium |

→ 所以“唤起失败”有两个相反的原因：**要么父进程太高（High），要么太低（Low）**。
只有 **Medium（普通用户）** 才对。

## 四、彻底解决

1. **`tools/start_chain.bat`**：双击即用，内含自检
   - High → 拒绝，并提示关掉管理员窗口重开
   - Low → 拒绝，提示去普通终端
   - Medium → 起 daemon → 起 QQ 桥 → 报状态
2. **`tools/integrity.py`**：随时查任意进程的完整性级别
   （`python tools\\integrity.py`）
3. **`tools/restart_daemon_safe.py` 加了护栏**：Low 时**拒绝重启**，
   防止 AI 再把整条链降级（`YHLZ_ALLOW_LOW_INTEGRITY=1` 可强行跳过）。
4. **`tools/qq_login_terminal.py`**：普通终端里启动 QQ 注入（stdin 接空，
   因为它会卡在等键盘；这是 `launcher-user.bat` 的 `pause` 之外的另一处坑）。

## 五、一句话结论

**不是 NapCat 要管理员，是启动它的父进程是什么级别，它就继承什么级别。**
QQ 登录必须 **Medium + 普通终端**：双击 `tools\\start_chain.bat`。
""")

MSG = os.path.join(ROOT, "cache", "cm_integrity.txt")
io.open(MSG, "w", encoding="utf-8").write(
    "fix(chain): 查清「唤起变成管理员终端」+ 完整性护栏 + 普通终端一键启链\n\n"
    "排查结论：\n"
    "  · NapCatWinBootMain.exe / QQ.exe manifest 都是 asInvoker（不要求提权）\n"
    "  · 注册表 AppCompatFlags 无 RUNASADMIN，无相关计划任务，自启 lnk 全 disabled\n"
    "  · → 管理员终端只能来自**父进程继承**（谁在管理员里启动，子进程就是管理员）\n"
    "  · 反向问题：实测整套 YH 栈是 **Low**（AI 沙箱重启的），Low 注入不了 Medium 的 QQ\n\n"
    "新增/修改：\n"
    "  · tools/integrity.py：查任意进程完整性级别（Low/Medium/High）\n"
    "  · tools/restart_daemon_safe.py：Low 时**拒绝重启**（防止把生产链降级）\n"
    "  · tools/start_chain.py + start_chain.bat：双击普通终端启链，High/Low 都拒绝\n"
    "  · tools/qq_login_terminal.py：普通终端起 QQ 注入（stdin 接空，绕开等键盘的坑）\n"
    "  · docs/方案/完整性级别与QQ登录_20261116.md：完整排查记录\n"
)
for cmd in (["git", "add", "-A"], ["git", "commit", "-q", "-F", MSG]):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("$ %s → %d %s" % (cmd[1], r.returncode, (r.stderr or "")[-60:]))
r = subprocess.run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push",
                    "origin", "main"], cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("push:", (r.stdout or r.stderr or "").strip()[-110:])
