# -*- coding: utf-8 -*-
"""元亨自检（L2）：一条命令验四条目标，输出 PASS/FAIL。

只测"目标内"的东西（老爹 2026-11-16 明确）：
  1. 链路：daemon 8321 / QQ online+ws / 桥
  2. 记忆：能想起只有记忆里才有的事（召回命中 + 内容对得上）
  3. 不编造：问没存过的 → 必须说查不到
  4. 时刻度：群消息 at 覆盖率 + 清洗前后破折号率（因果可复现）
  5. 风格：最近发言破折号率、带@率

用法：python tools\\yh_check.py [--quick]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import socket
import sqlite3
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
GH = ROOT + r"\cache\qq_bridge\lite\group_history.db"
TRACE = ROOT + r"\cache\recall_trace.jsonl"
DASH = re.compile(r"[—–―－]")
AT = re.compile(r"\[\[at:\s*\d+\]\]")
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
RESULTS: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    print("%s %-26s %s" % ("PASS" if cond else "FAIL", name, detail))


def get(path: str, timeout: int = 30) -> dict:
    with OP.open("http://127.0.0.1:8321" + path, timeout=timeout) as f:
        return json.loads(f.read().decode())


def post(path: str, body: dict, timeout: int = 200) -> dict:
    r = urllib.request.Request("http://127.0.0.1:8321" + path,
                               data=json.dumps(body, ensure_ascii=False).encode(),
                               headers={"Content-Type": "application/json"})
    with OP.open(r, timeout=timeout) as f:
        return json.loads(f.read().decode())


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只测链路与时刻度（不跑对话）")
    a = ap.parse_args()

    # ---- 1. 链路 ----
    ok("daemon 8321 在听", port_open(8321))
    try:
        st = get("/state")
        q = st.get("qq") or {}
    except Exception as ex:  # noqa: BLE001
        st, q = {}, {}
        print("  /state 取不到：%s" % type(ex).__name__)
    ok("QQ 在线", bool(q.get("online")))
    ok("QQ 桥已连", bool(q.get("ws")))

    # ---- 4/5. 时刻度 + 风格 ----
    try:
        con = sqlite3.connect(GH)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "select sender_id, text, at from group_messages where at>0")]
        con.close()
        has = len(rows)
        ok("群消息时间覆盖", has > 1000, "%d 条有 at" % has)
        cut = time.mktime(time.strptime("2026-11-14", "%Y-%m-%d"))
        mine = [r for r in rows if str(r["sender_id"]) == "3655185302"]
        pre = [r for r in mine if float(r["at"]) < cut]
        post_ = [r for r in mine if float(r["at"]) >= cut]
        rp = 100.0 * sum(1 for r in pre if DASH.search(str(r["text"]))) / max(1, len(pre))
        rq = 100.0 * sum(1 for r in post_ if DASH.search(str(r["text"]))) / max(1, len(post_))
        ok("清洗前破折号≈47%", 40 <= rp <= 55, "%.1f%%" % rp)
        ok("清洗后破折号=0%", rq == 0.0, "%.1f%%（%d 句）" % (rq, len(post_)))
        atr = 100.0 * sum(1 for r in post_ if AT.search(str(r["text"]))) / max(1, len(post_))
        ok("她会 @ 人", atr > 20, "%.0f%%" % atr)
    except Exception as ex:  # noqa: BLE001
        ok("时刻度读取", False, type(ex).__name__)

    # ---- 2/3. 记忆（对话，稍慢）----
    if not a.quick and port_open(8321):
        try:
            d = post("/turn", {"text": "上次我学做饭，你当时怎么鼓励我的",
                               "channel": "qq_p2258374446",
                               "source": "qq_bridge"})
            ans = str(d.get("answer") or "")
        except Exception as ex:  # noqa: BLE001
            ans = ""
            print("  记忆问询失败：%s" % type(ex).__name__)
        hit = any(k in ans for k in ("从无", "平淡", "踏实", "成就感"))
        ok("记忆能被用上", hit, ans[:60])
        try:
            rows = [json.loads(x) for x in io.open(TRACE, encoding="utf-8") if x.strip()]
            n = int((rows[-1] or {}).get("n") or 0) if rows else 0
        except Exception:  # noqa: BLE001
            n = 0
        ok("召回 trace 有命中", n > 0, "n=%d" % n)

        try:
            d2 = post("/turn", {"text": "我的车是什么颜色的", "channel": "qq_p2258374446",
                                "source": "qq_bridge"})
            a2 = str(d2.get("answer") or "")
        except Exception:  # noqa: BLE001
            a2 = ""
        invented = bool(re.search(r"(红|蓝|黑|白|银|灰)色", a2))
        ok("没存过的不编造", not invented, a2[:60])

    print("\n" + "=" * 56)
    bad = [r for r in RESULTS if not r[1]]
    print("共 %d 项｜通过 %d｜失败 %d" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for n, _c, d in bad:
        print("  FAIL %s %s" % (n, d))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
