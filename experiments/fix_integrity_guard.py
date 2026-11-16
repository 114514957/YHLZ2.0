# -*- coding: utf-8 -*-
"""修护栏：`Path` 未导入导致 NameError 被 except 吞掉，护栏静默失效。"""
from __future__ import annotations

import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "tools", "restart_daemon_safe.py")
t = io.open(P, encoding="utf-8").read()

old = '        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))'
new = '        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))'
assert old in t, "定位失败"
t = t.replace(old, new, 1)
# 缩小 except 范围：只捕取不到级别，别吞真错误
t = t.replace(
    '    except Exception:  # noqa: BLE001\n        return            # 取不到级别就不拦，避免误伤',
    '    except (ImportError, OSError, AttributeError):\n'
    '        return            # 取不到级别就不拦，避免误伤\n'
    '    except Exception as exc:  # noqa: BLE001\n'
    '        print("⚠ 完整性自检异常（%s: %s），按放行处理"\n'
    '              % (type(exc).__name__, str(exc)[:80]))\n'
    '        return', 1)
io.open(P, "w", encoding="utf-8").write(t)
r = subprocess.run([sys.executable, "-m", "py_compile", P], cwd=ROOT)
print("已修护栏；编译:", "OK" if r.returncode == 0 else "失败")
