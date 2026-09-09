"""YHLZ QQ bot bridge (ledger 0226): OneBot11 forward WebSocket -> daemon.

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
import time
import urllib.request

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))

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
        if msg_type == "private":
            if user_id not in self.masters:
                self.log(f"忽略非主人私聊 {user_id}")
                return
            channel = f"qq_p{user_id}"
        elif msg_type == "group":
            if self.uin not in ats:
                return
            channel = f"qq_g{ev.get('group_id', user_id)}"
        else:
            return
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
    masters = set(a.master or ["2258374446"])
    bridge = QQBridge(url, s["uin"], cfg, masters=masters)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
