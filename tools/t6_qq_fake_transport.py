"""T6①：QQ 假传输——真实 DeliveryManager + scripted 假 request（不连真实 QQ）。

覆盖：ack ok→confirmed；发送后断连→unknown（不重发）；发送前失败→有限重试。
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.qq_delivery import DeliveryManager, DeliveryTransportError  # noqa: E402


async def main() -> int:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    # A：正常 ack
    script = [{"status": "ok", "retcode": 0}]

    def req_ok(action, params):
        return script.pop(0)

    mgrA = DeliveryManager(request=req_ok, status_path=None, sleep=fake_sleep)
    rA = await mgrA.send(kind="reply", target={"type": "private", "id": "1"},
                         params={"message": "hi"})
    print("A(ack ok) ->", rA["status"])

    # B：发送后断连 → unknown，不重发
    async def req_after(action, params):
        raise DeliveryTransportError("disconnected after send", stage="after_send")

    mgrB = DeliveryManager(request=req_after, status_path=None, sleep=fake_sleep)
    rB = await mgrB.send(kind="reply", target={"type": "private", "id": "1"},
                         params={"message": "x"})
    print("B(after_send 断连) ->", rB["status"], "| counters:", mgrB.counters())

    # C：发送前失败 → 有限重试（max_retries=2）
    n = {"c": 0}

    async def req_before(action, params):
        n["c"] += 1
        raise DeliveryTransportError("connect refused", stage="before_send")

    mgrC = DeliveryManager(request=req_before, status_path=None, sleep=fake_sleep, max_retries=2)
    rC = await mgrC.send(kind="reply", target={"type": "private", "id": "1"},
                         params={"message": "y"})
    print("C(before_send 失败) ->", rC["status"], "| 尝试次数:", n["c"], "| 退避:", sleeps)

    ok = (rA["status"] == "confirmed" and rB["status"] == "unknown"
          and rC["status"] == "retryable" and n["c"] == 3)
    print("\nVERDICT:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


raise SystemExit(asyncio.run(main()))
