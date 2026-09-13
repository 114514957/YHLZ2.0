"""Pull a QQ group's chat via the account-switch workflow (ledger 0323).

Owner rule — on any QQ pull task:
  1) check the current situation (which account is logged in, QCE online?)
  2) log in to 2258374446 (the owner's main account; it is in the groups)
  3) pull (qq.export) + process (qq.process -> KB), original text preserved
  4) switch back to 元亨 (3655185302)

Usage: python tools/qq_pull.py <群名或群号> [--keep-main] [--no-process]
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tools.qq_login as qq_login  # noqa: E402
from backend.qq_token import get_token  # noqa: E402
from backend.yhlz_paths import BOT_UIN, MASTER_UIN  # noqa: E402

QCE = "http://127.0.0.1:40653"


def _qce_headers() -> dict:
    sec = pathlib.Path.home() / ".qq-chat-exporter" / "security.json"
    try:
        tok = json.loads(sec.read_text(encoding="utf-8")).get("accessToken", "")
    except Exception:
        tok = ""
    return {"Authorization": f"Bearer {tok}"}


def qce_health() -> dict:
    try:
        req = urllib.request.Request(QCE + "/health", headers=_qce_headers())
        return json.loads(urllib.request.urlopen(req, timeout=6).read()).get("data", {})
    except Exception:
        return {}


async def current_uin() -> str:
    """Logged-in QQ uin via NapCat OneBot get_login_info."""
    import websockets

    tok = get_token()
    url = "ws://127.0.0.1:3001" + (f"?access_token={tok}" if tok else "")
    try:
        async with websockets.connect(url, open_timeout=6) as ws:
            await ws.send(json.dumps({"action": "get_login_info", "echo": "1"}))
            for _ in range(6):
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
                if str(msg.get("echo")) == "1" or msg.get("status") is not None:
                    return str((msg.get("data") or {}).get("user_id", ""))
    except Exception:
        return ""
    return ""


def wait_qce_online(timeout: float = 150.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if qce_health().get("online"):
            return True
        time.sleep(5)
    return False


def goto(uin: str) -> bool:
    qq_login.set_auto_account(uin)
    qq_login.switch(uin)
    return wait_qce_online()


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep_main = "--keep-main" in sys.argv
    no_process = "--no-process" in sys.argv
    if not args:
        print("用法: python tools/qq_pull.py <群名或群号> [--keep-main] [--no-process]")
        return 2
    group = args[0]

    uin = await current_uin()
    print(f"[1/4] 现状: 登录号={uin or '?'} QCE在线={qce_health().get('online')}")

    if uin != MASTER_UIN:
        print(f"[2/4] 切到主号 {MASTER_UIN} ...")
        if not goto(MASTER_UIN):
            print("  QCE 未在线（可能需扫码）；已停。")
            return 1
        print("  主号在线")
    else:
        print("[2/4] 已在主号")

    from backend import target_scheduler_tools as T

    r = await T._qqops_export({"group_id": group, "session_name": str(group)})
    print("[3/4] 拉取:", r)
    if not no_process:
        try:
            print("  处理:", str(await T._qqops_process({}))[:300])
        except Exception as e:  # noqa: BLE001
            print("  处理 err", type(e).__name__, str(e)[:80])

    if not keep_main:
        print("[4/4] 切回元亨 ...")
        goto(BOT_UIN)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
