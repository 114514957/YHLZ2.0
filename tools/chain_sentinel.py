# -*- coding: utf-8 -*-
"""链路哨兵：每小时自检一次，把问题写进 sentinel.json（工作台显示红条）。

查六件事（都是今天/昨天真实踩过的坑）：
  1. daemon 8321 是否在听
  2. QQ 是否登录（online）、桥是否连上（ws）
  3. **群历史是否在长**（QQ 在线却 N 小时没新行 → 数据源死了）
  4. **lite 桥是否只有一个实例**（出现两个会抢会话）
  5. NapCat 进程是否在
  6. daemon 是否会写盘（cache 可写）

输出：cache/sustain/sentinel.json {ts, problems[], metrics{}}
用法：python tools\\chain_sentinel.py [--json]
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
OUT = os.path.join(ROOT, "cache", "sustain", "sentinel.json")
LOG = os.path.join(ROOT, "cache", "logs", "sentinel.log")
GH = os.path.join(ROOT, "cache", "qq_bridge", "lite", "group_history.db")
HIST_STALE_MIN = 180          # 3 小时没新群消息就提醒（群里通常很活跃）

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


def port_open(p: int) -> bool:
    s = socket.socket()
    s.settimeout(0.8)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def qq_state() -> dict:
    try:
        with OP.open("http://127.0.0.1:8321/state", timeout=6) as f:
            return (json.loads(f.read().decode()) or {}).get("qq") or {}
    except Exception:  # noqa: BLE001
        return {}


def bridge_instances() -> int:
    """lite 桥的**根实例**数量（父子 re-exec 只算一个）。

    2026-11-18：之前直接数进程，把 service 及其 re-exec 子进程当两个实例，
    误报"重复桥"；按父子关系过滤后才准。
    """
    try:
        import psutil
    except ImportError:
        return 0
    procs = {}
    for p in psutil.process_iter(["pid", "ppid", "cmdline"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "qq_bridge_service.py" in cmd:
            procs[p.info["pid"]] = p.info.get("ppid") or 0
    roots = [pid for pid, ppid in procs.items() if ppid not in procs]
    return len(roots)


def history_metrics() -> tuple[float, int]:
    """返回 (最新消息距今分钟, 近 1 小时行数)。"""
    try:
        con = sqlite3.connect(GH, timeout=5)
        mx, cnt = con.execute("select max(at), count(*) from group_messages").fetchone()
        hour = con.execute("select count(*) from group_messages where at > ?",
                           (time.time() - 3600,)).fetchone()[0]
        con.close()
        return (time.time() - float(mx or 0)) / 60.0, int(hour or 0)
    except Exception:  # noqa: BLE001
        return 9999.0, 0


def napcat_alive() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NapCatWinBootMain.exe"],
                             capture_output=True, text=True, encoding="mbcs",
                             errors="replace", timeout=20).stdout
        return "NapCatWinBootMain" in out
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    problems: list[str] = []
    daemon_ok = port_open(8321)
    if not daemon_ok:
        problems.append("daemon 8321 没在听")

    q = qq_state() if daemon_ok else {}
    if daemon_ok and not q.get("online"):
        problems.append("QQ 未登录（online=False）")
    if daemon_ok and q.get("online") and not q.get("ws"):
        problems.append("QQ 在线但桥没连上（ws=False）→ 该扫码或桥挂了")

    nb = bridge_instances()
    if nb > 1:
        problems.append("lite 桥有 %d 个实例（应只有 1 个）" % nb)

    if not napcat_alive():
        problems.append("NapCat 进程不在")

    age_min, hour_rows = history_metrics()
    if q.get("online") and q.get("ws") and age_min > HIST_STALE_MIN:
        problems.append("群历史 %.0f 分钟没新行（QQ 在线，怀疑写入路径坏了）" % age_min)

    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
    except Exception:  # noqa: BLE001
        problems.append("cache 不可写")

    payload = {
        "ts": time.time(),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "problems": problems,
        "metrics": {"daemon_ok": daemon_ok, "qq_online": bool(q.get("online")),
                    "ws": bool(q.get("ws")), "bridge_instances": nb,
                    "napcat": napcat_alive(),
                    "history_age_min": round(age_min, 1),
                    "history_rows_1h": hour_rows},
    }
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass

    msg = "正常" if not problems else "；".join(problems)
    log(msg)
    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print("哨兵：", msg)
        print("指标：", payload["metrics"])
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
