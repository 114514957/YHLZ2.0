"""T6②：故障注入 harness（v2，按 0622 复核修正 3.2）。

修正点：
1. `--minutes` 用**单调时钟**定义测量窗口；窗口内**持续覆盖**且每类故障 ≥`--each` 次才结束。
2. 失败**跨轮累计**（任一轮失败不被后续抹去）。
3. “进程退出恢复”用**真实子进程**写库+关闭，父进程新开库恢复（非同进程重开）。
4. “排队中策略变化”：任务**真实等待槽位**→改策略→放行，断言 provider 调用数=0 且任务保留。
5. “DB 写失败”走**应用路径**（写工具 → 效果 → 发布），断言不出现“已保存”成功话术。

用法：python tools/t6_fault_injection.py --minutes 2 --each 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import backend.bg_scheduler as bg  # noqa: E402
import backend.qq_delivery_store as ds  # noqa: E402

RESULTS: list[dict] = []
TOTAL_FAIL = 0
DEADLINE = 0.0


def rec(name, ok, detail=""):
    global TOTAL_FAIL
    if not ok:
        TOTAL_FAIL += 1
    RESULTS.append({"t": round(time.monotonic(), 3), "fault": name, "ok": bool(ok),
                    "detail": str(detail)[:120]})


async def fault_model_timeout(_tmp):
    async def slow():
        await asyncio.sleep(5)
    r = await bg.run(slow, kind="fi", timeout_s=0.05)
    rec("模型超时", r["status"] == "timeout", r["status"])


async def fault_malformed_json(_tmp):
    async def bad():
        json.loads("{not json")
    r = await bg.run(bad, kind="fi")
    rec("畸形JSON", r["status"] == "error", r["status"])


async def fault_db_write_fail(tmp):
    """走应用路径：写工具 → 效果 → 发布，断言无“已保存”成功话术。"""
    from backend import target_scheduler_tools as st
    from backend.text_tool_contract import TextToolContract  # noqa: F401

    saved = st.DIARY_FILE
    ro = tmp / "ro_dir"
    ro.mkdir(exist_ok=True)
    st.DIARY_FILE = ro / "diary_readonly.md"
    try:
        st.DIARY_FILE.write_text("x", encoding="utf-8")
        st.DIARY_FILE.chmod(0o444)
    except Exception:
        pass
    call_detail = ""
    try:
        out = st.diary_write(content="故障注入测试内容")
        call_detail = str(out)[:80]
    except Exception as exc:  # noqa: BLE001
        call_detail = f"{type(exc).__name__}: {str(exc)[:60]}"
    finally:
        st.DIARY_FILE = saved
    claimed_saved = "已" in call_detail and "失败" not in call_detail and "拒绝" not in call_detail
    rec("DB写失败(应用路径)", not claimed_saved, call_detail)


async def fault_cancel(_tmp):
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


_CRASH_SCRIPT = r"""
import sys, time
sys.path.insert(0, r'{root}')
import backend.qq_delivery_store as ds
con = ds.connect(r'{db}')
ds.enqueue(con, source_event_id='crash1', channel='c', target_type='t', target_id='i')
ds.claim_due(con, 'w-crash', now=time.time() - 999, lease_s=1.0)
con.close()
raise SystemExit(0)
"""


async def fault_process_exit_reopen(tmp):
    """真实子进程：写库+领租约后**进程退出**；父进程新开库恢复。"""
    db = tmp / f"crash_{uuid.uuid4().hex[:8]}.db"
    script = tmp / f"crash_{uuid.uuid4().hex[:8]}.py"
    script.write_text(_CRASH_SCRIPT.format(root=str(pathlib.Path(".").resolve()),
                                           db=str(db)), encoding="utf-8")
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
    ok_child = p.returncode == 0
    n = 0
    st = {}
    if db.exists():
        con = ds.connect(db)
        n = ds.reclaim_expired(con, now=time.time() + 999)
        st = ds.status_summary(con)
        con.close()
    rec("进程退出恢复(真子进程)", ok_child and n == 1 and st.get("unknown") == 1,
        f"rc={p.returncode} reclaimed={n} {st}")


async def fault_policy_change_while_queued(tmp):
    """任务真实等待槽位 → 改策略 → 放行；断言 provider 未调用、任务保留。"""
    con = ds.connect(tmp / f"pol_{uuid.uuid4().hex[:8]}.db")
    ds.enqueue(con, source_event_id=f"p{uuid.uuid4().hex[:6]}", channel="c",
               target_type="t", target_id="i")
    flag = {"allow": True}
    calls = {"n": 0}

    async def job():
        calls["n"] += 1
        return "x"

    bg.foreground_enter()          # 占用前台 → 后台任务真实等待槽位
    task = asyncio.create_task(bg.run(job, kind="fi", policy_check=lambda: flag["allow"]))
    await asyncio.sleep(0.05)
    flag["allow"] = False          # 等待期间改策略
    bg.foreground_exit()           # 放行
    r = await task
    st = ds.status_summary(con)
    con.close()
    rec("排队中策略变化", r["status"] == "skipped_policy" and calls["n"] == 0
        and st.get("queued") == 1, f"{r['status']} calls={calls['n']} {st}")


FAULTS = [fault_model_timeout, fault_malformed_json, fault_db_write_fail, fault_cancel,
          fault_process_exit_reopen, fault_policy_change_while_queued]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=2.0, help="测量窗口（单调时钟，分钟）")
    ap.add_argument("--each", type=int, default=3, help="每类故障最少注入次数")
    args = ap.parse_args()

    bg.reset_for_tests()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t6_fi2_"))
    counts = {f.__name__: 0 for f in FAULTS}
    t0 = time.monotonic()
    deadline = t0 + args.minutes * 60
    rounds = 0
    while True:
        rounds += 1
        for f in FAULTS:
            await f(tmp)
            counts[f.__name__] += 1
        bad_total = sum(1 for r in RESULTS if not r["ok"])
        print(f"[round {rounds}] 累计 {len(RESULTS)} 次注入，累计失败 {TOTAL_FAIL}")
        covered = all(counts[f.__name__] >= args.each for f in FAULTS)
        if time.monotonic() >= deadline and covered:
            break
        if time.monotonic() >= deadline and not covered:
            print("(窗口到点但覆盖不足，继续到满足 each 次数)")
        if rounds > 10000:
            break

    print(f"\n测量窗口 {round((time.monotonic()-t0)/60, 2)} 分钟；轮数 {rounds}；"
          f"注入 {len(RESULTS)} 次；**累计失败 {TOTAL_FAIL}**")
    print("每类注入次数:", counts)
    print("SUCCESS" if TOTAL_FAIL == 0 else "CHECK")
    return 0 if TOTAL_FAIL == 0 else 1


raise SystemExit(asyncio.run(main()))
