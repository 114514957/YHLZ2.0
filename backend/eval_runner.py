# -*- coding: utf-8 -*-
"""一键评测的运行器（台账 1255）：在工作台点一下，跑 152+75 的云端评测并出分。

为什么要有：今天所有关于提示词的争论，最后都卡在"没法快速量"。
这个模块把 `experiments/eval56_28.py --provider cloud` 包成一次任务：
  起 → 有 pid 与日志 → 结束有结果 json → 与上一版对比。

状态文件：`cache/eval_state.json`；日志：`cache/logs/eval_<tag>.log`
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
STATE = ROOT / "cache" / "eval_state.json"
LOGDIR = ROOT / "cache" / "logs"
SCRIPT = ROOT / "experiments" / "eval56_28.py"

__all__ = ["start", "status", "history"]


def _load_state() -> dict:
    try:
        if STATE.exists():
            return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_state(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).status() != "zombie"
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:  # noqa: BLE001
            return False


def start(tag: str = "") -> dict:
    """起一轮云端评测。已有任务在跑就拒绝。"""
    st = _load_state()
    if st.get("pid") and _alive(int(st["pid"])) and not st.get("done"):
        return {"ok": False, "busy": True, "error": "已有一轮在跑",
                "state": st}
    tag = (tag or "").strip() or ("wb_" + time.strftime("%m%d_%H%M"))
    if not re.match(r"^[\w\-]{1,40}$", tag):
        return {"ok": False, "error": "tag 只能用字母数字下划线横线"}
    LOGDIR.mkdir(parents=True, exist_ok=True)
    log = LOGDIR / ("eval_%s.log" % tag)
    cmd = [str(PY), "-u", "-X", "utf8", str(SCRIPT),
           "--tag", tag, "--provider", "cloud"]
    f = open(log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=f,
                            stderr=subprocess.STDOUT, close_fds=True,
                            creationflags=0x08000000)
    st = {"tag": tag, "pid": proc.pid, "started": time.time(),
          "log": str(log.relative_to(ROOT)), "done": False}
    _save_state(st)
    return {"ok": True, "state": st}


def _tail(path: Path, n: int = 12) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-n:]
    except Exception:  # noqa: BLE001
        return []


def status() -> dict:
    """当前任务状态 + 结果（若已出）。"""
    st = _load_state()
    if not st:
        return {"ok": True, "running": False, "state": {}}
    pid = int(st.get("pid") or 0)
    running = bool(pid) and _alive(pid) and not st.get("done")
    out: dict = {"ok": True, "running": running, "state": st,
                 "tail": _tail(ROOT / st.get("log", ""), 8) if st.get("log") else []}
    res = ROOT / "cache" / ("eval_%s.json" % st.get("tag", ""))
    if res.exists():
        try:
            d = json.loads(res.read_text(encoding="utf-8"))
            per = d.get("detail", {}).get("persona", [])
            grp = d.get("detail", {}).get("group", [])
            out["result"] = {
                "tag": st.get("tag"),
                "persona": "%d/%d" % (sum(1 for r in per if r.get("ok")), len(per)),
                "group": "%d/%d" % (sum(1 for r in grp if r.get("ok")), len(grp)),
                "persona_failed": [r["id"] for r in per if not r.get("ok")],
                "group_failed": [r["id"] for r in grp if not r.get("ok")],
                "mtime": res.stat().st_mtime,
            }
            out["state"]["done"] = not running
            _save_state(out["state"]) if not running else None
        except Exception as exc:  # noqa: BLE001
            out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    return out


def history(limit: int = 6) -> list[dict]:
    """最近的评测结果（按文件时间倒序）。"""
    rows = []
    for p in sorted(ROOT.glob("cache/eval_*.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            per = d.get("detail", {}).get("persona", [])
            grp = d.get("detail", {}).get("group", [])
            rows.append({"tag": p.stem.replace("eval_", ""),
                         "persona": sum(1 for r in per if r.get("ok")),
                         "persona_n": len(per),
                         "group": sum(1 for r in grp if r.get("ok")),
                         "group_n": len(grp),
                         "mtime": p.stat().st_mtime})
        except Exception:  # noqa: BLE001
            continue
    return rows


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(status(), ensure_ascii=False, indent=1)[:800])
    print("\n历史：")
    for r in history():
        print("  %-16s 人格 %s/%s 群聊 %s/%s"
              % (r["tag"], r["persona"], r["persona_n"], r["group"], r["group_n"]))
