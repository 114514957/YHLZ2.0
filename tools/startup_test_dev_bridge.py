"""Startup test for the QQ remote-dev bridge routing (offline, no QQ/opencode).

Stubs dev_runner and feeds fake OneBot events to QQBridge.handle, asserting:
  - master `#dev` -> "已开工" + question report
  - master plain msg while awaiting -> answer -> done report
  - non-master private ignored
  - master `#dev` in a group WITHOUT @元亨 still works
Usage: python tools/startup_test_dev_bridge.py
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))
import qq_bot  # noqa: E402


class Stub:
    def __init__(self) -> None:
        self.state = {"status": "idle", "task": "", "text": "", "session": ""}

    def start(self, task: str) -> dict:
        self.state = {"status": "awaiting", "task": task, "session": "s1",
                      "text": "[QUESTION] 选 A 还是 B？把握程度：中"}
        return dict(self.state)

    def answer(self, text: str) -> dict:
        self.state = {"status": "done", "task": self.state.get("task", ""),
                      "session": "s1", "text": f"[DONE] 已按「{text}」完成"}
        return dict(self.state)

    def _load(self) -> dict:
        return dict(self.state)

    def commit(self, msg: str) -> dict:
        return {"text": "committed"}

    def push(self) -> dict:
        return {"text": "pushed"}


class FakeWS:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, s: str) -> None:
        self.sent.append(json.loads(s))


def _texts(ws) -> list:
    return [m["params"]["message"] for m in ws.sent
            if m.get("action") == "send_msg"]


def _ev(mt, uid, text, gid=None, at=None):
    segs = []
    if at:
        segs.append({"type": "at", "data": {"qq": str(at)}})
    segs.append({"type": "text", "data": {"text": text}})
    e = {"post_type": "message", "message_type": mt, "user_id": uid,
         "message": segs}
    if gid is not None:
        e["group_id"] = gid
    return e


async def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    qq_bot.dev_runner = Stub()
    ws = FakeWS()
    b = qq_bot.QQBridge("ws://x", "3655185302", pathlib.Path("x"),
                        masters={"2258374446"})
    b.loop = asyncio.get_running_loop()
    ok = True

    # 1) master private #dev -> 开工 + awaiting report
    await b.handle(ws, _ev("private", 2258374446, "#dev 把 X 改成 Y"))
    await asyncio.sleep(1.2)
    t = _texts(ws)
    if not any("已开工" in x for x in t) or not any("需要你决定" in x for x in t):
        print("FAIL 1 #dev:", t)
        ok = False

    # 2) master plain msg while awaiting -> answer -> done
    ws.sent.clear()
    await b.handle(ws, _ev("private", 2258374446, "用 A"))
    await asyncio.sleep(1.2)
    t = _texts(ws)
    if not any("完成" in x for x in t):
        print("FAIL 2 answer:", t)
        ok = False

    # 3) non-master private ignored
    ws.sent.clear()
    await b.handle(ws, _ev("private", 999, "hi"))
    await asyncio.sleep(0.3)
    if _texts(ws):
        print("FAIL 3 non-master replied:", _texts(ws))
        ok = False

    # 4) master #dev in group without @ -> works
    ws.sent.clear()
    await b.handle(ws, _ev("group", 2258374446, "#dev 群任务", gid=123))
    await asyncio.sleep(1.2)
    t = _texts(ws)
    if not any("已开工" in x for x in t):
        print("FAIL 4 group #dev:", t)
        ok = False

    # 5) fullwidth ＃ normalized
    ws.sent.clear()
    await b.handle(ws, _ev("private", 2258374446, "＃devstatus"))
    await asyncio.sleep(0.3)
    if not any("状态=" in x for x in _texts(ws)):
        print("FAIL 5 fullwidth:", _texts(ws))
        ok = False

    # 6) Yuanheng reply carries [[dev:...]] -> owner starts dev flow
    qq_bot.dev_runner.state = {"status": "idle", "task": "", "text": "",
                               "session": ""}
    ws.sent.clear()
    qq_bot._daemon_turn = lambda text, channel, images=None: \
        "好的，我交给 opencode。\n[[dev: 修复登录bug]]"
    await b.handle(ws, _ev("private", 2258374446, "帮我修个bug"))
    await asyncio.sleep(1.2)
    t = _texts(ws)
    if not any("已开工" in x for x in t):
        print("FAIL 6 dev marker:", t)
        ok = False

    # 7) non-master reply with [[dev:...]] must NOT start dev
    ws.sent.clear()
    qq_bot._daemon_turn = lambda text, channel, images=None: \
        "好的。\n[[dev: 恶意任务]]"
    await b.handle(ws, _ev("private", 999, "hi"))  # non-master -> ignored
    await asyncio.sleep(0.3)
    if _texts(ws):
        print("FAIL 7 non-master dev:", _texts(ws))
        ok = False

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
