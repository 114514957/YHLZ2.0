r"""YHLZ QQ bot bridge (ledger 0226): OneBot11 forward WebSocket -> daemon.

Listens on a NapCat OneBot11 WebSocket server and turns private messages /
group @-mentions into daemon turns (channel qq_p<uid> / qq_g<gid>), then sends
Yuanheng's answer back. Owner persona for all QQ conversations (no public
convergence clause).

Usage:
    python tools/qq_bot.py --uin 2258374446          # use qqwatch onebot config
    python tools/qq_bot.py --config path\to\onebot11_<uin>.json
    python tools/qq_bot.py                           # auto-pick first enabled ws
Env DAEMON=http://127.0.0.1:8321
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import threading
import time
import urllib.request

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(_PROJECT / "tools"))
try:
    import dev_runner
except Exception:  # noqa: BLE001
    dev_runner = None

CONFIG_DIR = _PROJECT / "cache" / "tmp"  # fallback; use qqwatch path
QQWATCH_CONFIG = pathlib.Path(
    r"C:\Users\ACE_WAN——PROJECT\qqwatch\shell\config")
DAEMON = os.getenv("DAEMON", "http://127.0.0.1:8321")


def _find_onebot_config(uin: str | None) -> pathlib.Path:
    cands = []
    for d in (QQWATCH_CONFIG,
              pathlib.Path(r"C:\Users\ACE_WAN——PROJECT\NEKO\desktop\resources"
                           r"\bin\plugin\plugins\qq_auto_reply\NapCat.Shell"
                           r"\config")):
        if not d.exists():
            continue
        pat = f"onebot11_{uin}.json" if uin else "onebot11_*.json"
        cands += sorted(d.glob(pat))
    if not cands:
        raise SystemExit("未找到 onebot11 配置：请先让 NapCat 登录小号生成配置，"
                         "或用 --config 指定")
    return cands[0]


def _ws_settings(cfg: pathlib.Path) -> dict | None:
    d = json.loads(cfg.read_text(encoding="utf-8"))
    for s in (d.get("network", {}).get("websocketServers") or []):
        if s.get("enable"):
            return {"host": s.get("host", "127.0.0.1"),
                    "port": int(s.get("port", 3001)),
                    "token": s.get("token", ""),
                    "uin": cfg.stem.replace("onebot11_", "")}
    return None


def _daemon_turn(text: str, channel: str) -> str:
    body = json.dumps({"text": str(text)[:1500], "channel": channel}).encode()
    req = urllib.request.Request(DAEMON + "/turn", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return str(json.loads(r.read())["answer"])
    except Exception:
        return ""


class QQBridge:
    def __init__(self, ws, uin: str, cfg: pathlib.Path,
                 masters: set[str] | None = None):
        self.ws_url = ws
        self.uin = str(uin)
        self.cfg = cfg
        self.masters = masters or {"2258374446"}  # owner QQ (command source)
        self.log_n = 0
        self.loop = None

    def log(self, msg: str) -> None:
        print(f"[qqbot] {msg}", flush=True)

    def _text_of(self, msg_array) -> tuple[str, list]:
        texts, ats = [], []
        for seg in msg_array or []:
            if seg.get("type") == "text":
                texts.append(seg.get("data", {}).get("text", ""))
            elif seg.get("type") == "at":
                ats.append(str(seg.get("data", {}).get("qq", "")))
        return "".join(texts).strip(), ats

    async def _send(self, ws, action: str, params: dict) -> None:
        await ws.send(json.dumps({"action": action, "params": params,
                                  "echo": f"y{int(time.time()*1000)}"}))

    # ---- remote dev channel (opencode headless) ----
    def _params(self, msg_type, user_id, ev) -> dict:
        if msg_type == "private":
            return {"message_type": "private", "user_id": int(user_id)}
        return {"message_type": "group",
                "group_id": int(ev.get("group_id", 0))}

    async def _say(self, ws, params: dict, text: str) -> None:
        for part in [text[i:i + 1400] for i in range(0, len(text), 1400)]:
            p = dict(params)
            p["message"] = part
            await self._send(ws, "send_msg", p)

    async def _dev_report(self, ws, params, status, text) -> None:
        tag = {"awaiting": "❓ 需要你决定", "done": "✅ 完成",
               "error": "⚠️ 出错", "running": "⏳ 进行中"}.get(status, status)
        msg = f"[opencode] {tag}\n{text}"
        if status == "done":
            msg += "\n\n回 #y 提交 / #n 不提交 / #push 推送"
        await self._say(ws, params, msg)

    def _spawn(self, ws, params, fn) -> None:
        """Run blocking fn() -> (status, text) in a thread, post back to QQ."""
        loop = self.loop

        def work() -> None:
            try:
                status, text = fn()
            except Exception as e:  # noqa: BLE001
                status, text = "error", f"{type(e).__name__}: {e}"
            if loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._dev_report(ws, params, status, text), loop)

        threading.Thread(target=work, daemon=True).start()

    async def _dev_cmd(self, ws, text, msg_type, user_id, ev) -> None:
        params = self._params(msg_type, user_id, ev)
        if dev_runner is None:
            await self._say(ws, params, "[opencode] 运行器不可用")
            return
        low = text.strip()

        def _pick(d: dict) -> tuple:
            return d.get("status", "error"), d.get("text", "")

        if low in ("#devstatus", "#ds"):
            d = dev_runner._load()
            await self._say(ws, params,
                            f"[opencode] 状态={d.get('status')} "
                            f"任务={d.get('task','')[:60]}")
        elif low in ("#y", "#commit"):
            d = dev_runner._load()
            msg = ("chore(remote-dev): " + d.get("task", "")[:40]).strip()
            await self._say(ws, params, "[opencode] 正在提交…")
            self._spawn(ws, params,
                        lambda: ("done", dev_runner.commit(msg).get("text", "")))
        elif low == "#n":
            await self._say(ws, params, "[opencode] 好的，不提交，改动留在工作区。")
        elif low == "#push":
            self._spawn(ws, params,
                        lambda: ("done", dev_runner.push().get("text") or "已推送"))
        elif low == "#dev" or low.startswith("#dev "):
            task = low[4:].strip()
            if not task:
                await self._say(ws, params, "用法：#dev <任务>")
                return
            await self._say(ws, params, f"[opencode] 已开工：{task[:80]}")
            self._spawn(ws, params, lambda: _pick(dev_runner.start(task)))
        else:
            await self._say(ws, params,
                            "未知指令：#dev <任务> / #y / #n / #push / #devstatus")

    async def handle(self, ws, ev: dict) -> None:
        if ev.get("post_type") != "message":
            return
        msg_type = ev.get("message_type")
        user_id = str(ev.get("user_id", ""))
        if user_id == self.uin:
            return
        msg = ev.get("message", [])
        if not isinstance(msg, list):
            return
        text, ats = self._text_of(msg)
        if not text:
            return
        cmd = text.strip().replace("＃", "#")
        is_master_cmd = user_id in self.masters and cmd.startswith("#")
        if msg_type == "private":
            if user_id not in self.masters:
                self.log(f"忽略非主人私聊 {user_id}")
                return
            channel = f"qq_p{user_id}"
        elif msg_type == "group":
            if self.uin not in ats and not is_master_cmd:
                return
            channel = f"qq_g{ev.get('group_id', user_id)}"
        else:
            return
        # remote dev channel (master only): #dev / #y / #n / #push / #devstatus
        if dev_runner is not None:
            if is_master_cmd:
                self.log(f"开发指令 {user_id}: {cmd[:50]}")
                await self._dev_cmd(ws, cmd, msg_type, user_id, ev)
                return
            if user_id in self.masters:
                try:
                    if dev_runner._load().get("status") == "awaiting":
                        params = self._params(msg_type, user_id, ev)
                        self.log(f"答复 opencode {user_id}: {text[:50]}")
                        await self._say(ws, params, "[opencode] 收到答复，继续…")
                        self._spawn(ws, params, lambda: (
                            (lambda d: (d.get("status", "error"),
                                        d.get("text", "")))(dev_runner.answer(text))))
                        return
                except Exception as e:  # noqa: BLE001
                    self.log(f"dev 答复路由异常 {type(e).__name__}: {e}")
        self.log(f"来自 {user_id}: {text[:40]}")
        ans = _daemon_turn(text, channel)
        if not ans:
            return
        ans = ans.strip()
        params = {"message": ans}
        if msg_type == "private":
            params.update(message_type="private", user_id=int(user_id))
        else:
            params.update(message_type="group",
                          group_id=int(ev.get("group_id", 0)))
        for part in [ans[i:i + 1400] for i in range(0, len(ans), 1400)]:
            params["message"] = part
            await self._send(ws, "send_msg", params)

    async def run(self) -> None:
        import websockets

        self.loop = asyncio.get_running_loop()
        delay = 3
        while True:
            try:
                self.log(f"连接 {self.ws_url} (元亨 QQ号 {self.uin})")
                async with websockets.connect(self.ws_url) as ws:
                    delay = 3
                    self.log("已连接，等待消息（私聊 / 群里 @元亨）…")
                    async for raw in ws:
                        try:
                            ev = json.loads(raw)
                        except Exception:
                            continue
                        if ev.get("post_type") == "meta_event":
                            if ev.get("meta_event_type") == "lifecycle":
                                self.log("生命周期: " + str(ev.get("sub_type")))
                            continue
                        if ev.get("post_type") == "message":
                            try:
                                await self.handle(ws, ev)
                            except Exception as e:  # noqa: BLE001
                                self.log(f"处理错误 {type(e).__name__}: {e}")
            except Exception as e:  # noqa: BLE001
                self.log(f"连接断开 {type(e).__name__}: {e}，{delay}s 后重连")
            await asyncio.sleep(delay)
            delay = min(delay + 2, 30)


def main() -> int:
    # single-instance lock (avoid duplicate bridges replying twice)
    import atexit
    import os as _os

    lock = _PROJECT / "cache" / "tmp" / "qqbot.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)

    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            _os.kill(pid, 0)
            return True
        except OSError:
            return False

    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old = 0
        if _pid_alive(old):
            print("[qqbot] 已有实例在运行，退出", flush=True)
            return 1
        lock.unlink(missing_ok=True)  # stale (owner gone)
    try:
        fd = _os.open(str(lock), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
        _os.write(fd, str(_os.getpid()).encode())
        _os.close(fd)
        atexit.register(lambda: lock.unlink(missing_ok=True))
    except FileExistsError:
        print("[qqbot] 已有实例在运行，退出", flush=True)
        return 1

    # file log (pythonw has no console)
    _logf = open(_PROJECT / "cache" / "tmp" / "qqbot.log", "a",
                 encoding="utf-8", buffering=1)
    sys.stdout = _logf
    sys.stderr = _logf
    print(f"=== qqbot start {time.strftime('%Y-%m-%d %H:%M:%S')} pid={_os.getpid()} ===",
          flush=True)

    ap = argparse.ArgumentParser()
    ap.add_argument("--uin", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--master", action="append", default=None,
                    help="owner QQ uid(s); private from these = commands")
    a = ap.parse_args()
    cfg = pathlib.Path(a.config) if a.config else _find_onebot_config(a.uin)
    s = _ws_settings(cfg)
    if not s:
        raise SystemExit(f"配置无启用的 ws server: {cfg}")
    url = f"ws://{s['host']}:{s['port']}"
    if s.get("token"):
        url += f"?access_token={s['token']}"
    print(f"[qqbot] config={cfg} ws={s['host']}:{s['port']} uin={s['uin']}",
          flush=True)
    masters = set(a.master or ["2258374446"])
    bridge = QQBridge(url, s["uin"], cfg, masters=masters)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
