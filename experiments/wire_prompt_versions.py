# -*- coding: utf-8 -*-
"""把「保存即快照」接进 prompt_overrides，并加版本/回滚接口与界面。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"

# ① prompt_overrides.set_block 里保存前先快照
P1 = os.path.join(ROOT, "backend", "prompt_overrides.py")
t1 = io.open(P1, encoding="utf-8").read()
if "prompt_versions" not in t1:
    import re
    m = re.search(r"def set_block\((.+?)\n(    .+?)\n", t1, re.S)
    # 在 set 写盘之前插入快照：找函数体里的写文件处
    hook = '''
def _snapshot_before(key: str = "", note: str = "") -> None:
    """保存前留一份快照（台账 1256：改坏了要能回去）。"""
    try:
        from backend import prompt_versions as _pv
        _pv.snapshot(key=key, note=note)
    except Exception:
        pass

'''
    t1 = t1.replace("def set_block(", hook + "def set_block(", 1)
    # 在 set_block 里最前面调用
    t1 = t1.replace("def set_block(", "def set_block(", 1)
    idx = t1.find("def set_block(")
    seg_end = t1.find("\n\n", idx)
    seg = t1[idx:seg_end]
    if "_snapshot_before(" not in seg:
        lines = seg.splitlines()
        # 找到函数体的第一行（缩进 4 且不是 docstring 起）
        for i, ln in enumerate(lines):
            if i > 0 and ln.startswith("    ") and not ln.strip().startswith('"""'):
                lines.insert(i, '    _snapshot_before(key, "set")')
                break
        t1 = t1[:idx] + "\n".join(lines) + t1[seg_end:]
    io.open(P1, "w", encoding="utf-8").write(t1)
    print("prompt_overrides 已接快照")
else:
    print("prompt_overrides 已接")

# ② daemon 接口
D = os.path.join(ROOT, "backend", "target_daemon.py")
d = io.open(D, encoding="utf-8").read()
if "/api/prompt_versions" not in d:
    anchor = '        if method == "GET" and p == "/api/eval_status":'
    add = '''        if method == "GET" and p.startswith("/api/prompt_versions"):
            # 提示词历史（台账 1256）
            try:
                from backend import prompt_versions as _pv
                key = ""
                if "?" in self.path:
                    import urllib.parse as _up
                    key = (_up.parse_qs(self.path.split("?", 1)[1]).get("key") or [""])[0]
                self._send(200, {"ok": True, "versions": _pv.versions(40, key)})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc)[:140]})
            return True
'''
    assert anchor in d
    d = d.replace(anchor, add + anchor, 1)

    anchor2 = '        if self.path == "/api/eval_run":'
    add2 = '''        if self.path == "/api/prompt_restore":
            # 回滚某块（或整份）。台账 1256。
            try:
                from backend import prompt_versions as _pv
                key = str(payload.get("key") or "")
                ts = str(payload.get("ts") or "")
                if not ts:
                    self._send(400, {"ok": False, "error": "缺 ts"})
                    return
                res = _pv.restore_all(ts) if key in ("", "*") else _pv.restore_block(key, ts)
                self._send(200 if res.get("ok") else 400, res)
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc)[:140]})
            return
        if self.path == "/api/prompt_snapshot":
            try:
                from backend import prompt_versions as _pv
                ts = _pv.snapshot(key=str(payload.get("key") or ""), note="manual")
                self._send(200, {"ok": bool(ts), "ts": ts})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc)[:140]})
            return
'''
    assert anchor2 in d
    d = d.replace(anchor2, add2 + anchor2, 1)
    # POST 例外
    d = d.replace('("/api/try_turn", "/api/eval_run")',
                  '("/api/try_turn", "/api/eval_run", "/api/prompt_restore",\n'
                  '                 "/api/prompt_snapshot")', 1)
    io.open(D, "w", encoding="utf-8").write(d)
    print("daemon 接口已加")
else:
    print("daemon 接口已存在")
