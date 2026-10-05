"""T6②：故障注入 harness（真实调度器/投递存储 + 合成故障；不连真实 QQ/云）。

故障类型（合成、可控）：模型超时、畸形 JSON、DB 写失败、取消、进程退出重启、
重复消息、排队中策略变化。

用法：python tools/t6_fault_injection.py --minutes 1 [--rounds 3]
计划目标：30 分钟；默认短烟测（不占满墙钟）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import backend.bg_scheduler as bg  # noqa: E402
import backend.qq_delivery_store as ds  # noqa: E402

RESULTS = []


def rec(name, ok, detail=""):
    RESULTS.append({"fault": name, "ok": bool(ok), "detail": str(detail)[:120]})


async def fault_model_timeout():
    async def slow():
        await asyncio.sleep(5)
    r = await bg.run(slow, kind="fi", timeout_s=0.05)
    rec("模型超时", r["status"] == "timeout", r["status"])


async def fault_malformed_json():
    async def bad():
        json.loads("{not json")
    r = await bg.run(bad, kind="fi")
    rec("畸形JSON", r["status"] == "error", r["status"])


def fault_db_write_fail(tmp):
    import uuid as _uuid

    tag = _uuid.uuid4().hex[:8]
    con = ds.connect(tmp / "ro.db")
    con.execute("INSERT INTO deliveries(delivery_id,source_event_id,channel,target_type,"
                "target_id,kind,state,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (f"x{tag}", f"s{tag}", "c", "t", "i", "k", "queued", 1))
    con.commit()
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("INSERT INTO deliveries(delivery_id,source_event_id,channel,target_type,"
                    "target_id,kind,state,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (f"y{tag}", f"s2{tag}", "c", "t", "i", "k", "queued", 1))
        ok = False
    except sqlite3.OperationalError:
        ok = True
    rec("DB写失败", ok)
    con.close()


async def fault_cancel():
    async def slow():
        await asyncio.sleep(5)
    task = asyncio.create_task(bg.run(slow, kind="fi", timeout_s=30))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
        ok = False
    except asyncio.CancelledError:
        ok = True
    rec("取消", ok)


def fault_process_exit_reopen(tmp):
    import uuid as _uuid

    p = tmp / f"restart_{_uuid.uuid4().hex[:8]}.db"
    con = ds.connect(p)
    a = ds.enqueue(con, source_event_id="r1", channel="c", target_type="t", target_id="i")
    ds.claim_due(con, "w1", now=time.time() - 999, lease_s=1.0)
    con.close()
    con2 = ds.connect(p)  # 进程退出后重开
    n = ds.reclaim_expired(con2, now=time.time() + 999)
    st = ds.status_summary(con2)
    con2.close()
    rec("进程退出重启", n == 1 and st.get("unknown") == 1, st)


def fault_duplicate_message(tmp):
    con = ds.connect(tmp / "dup.db")
    a = ds.enqueue(con, source_event_id="d1", channel="c", target_type="t", target_id="i", kind="reply")
    b = ds.enqueue(con, source_event_id="d1", channel="c", target_type="t", target_id="i", kind="reply")
    rec("重复消息", a["delivery_id"] == b["delivery_id"] and b["idempotent"] is True,
        f"same={a['delivery_id'] == b['delivery_id']}")
    con.close()


async def fault_policy_change_while_queued(tmp):
    con = ds.connect(tmp / "pol.db")
    ds.enqueue(con, source_event_id="p1", channel="c", target_type="t", target_id="i")
    flag = {"allow": False}
    r = await bg.run(lambda: asyncio.sleep(0, result="x"), kind="fi",
                     policy_check=lambda: flag["allow"])
    st = ds.status_summary(con)
    con.close()
    rec("排队中策略变化", r["status"] == "skipped_policy" and st.get("queued") == 1,
        f"{r['status']}/{st}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=1.0,
                    help="墙钟上限（计划目标 30）；到点即停")
    ap.add_argument("--rounds", type=int, default=3, help="每类故障重复轮数（计划每类≥3）")
    args = ap.parse_args()

    bg.reset_for_tests()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_fi_"))
    deadline = time.time() + args.minutes * 60
    final_bad = 0
    rounds = 0
    while rounds < args.rounds:
        rounds += 1
        RESULTS.clear()
        await fault_model_timeout()
        await fault_malformed_json()
        fault_db_write_fail(tmp)
        await fault_cancel()
        fault_process_exit_reopen(tmp)
        fault_duplicate_message(tmp)
        await fault_policy_change_while_queued(tmp)
        bad = [r for r in RESULTS if not r["ok"]]
        final_bad = len(bad)
        print(f"[round {rounds}] {len(RESULTS)} 类故障，失败 {len(bad)}")
        for r in RESULTS:
            print(f"   {'PASS' if r['ok'] else 'FAIL'} {r['fault']} | {r['detail']}")
        if time.time() >= deadline:
            print("(墙钟到点，提前结束)")
            break

    print(f"\n总轮数 {rounds}；最终轮失败 {final_bad}")
    print("SUCCESS" if final_bad == 0 else "CHECK")
    return 0 if final_bad == 0 else 1


raise SystemExit(asyncio.run(main()))
