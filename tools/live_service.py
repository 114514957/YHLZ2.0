"""L1 直播音频服务 CLI（台账 0679/0680）。

用法：
  python tools/live_service.py serve            # 常驻本机音频服务（按需启动）
  python tools/live_service.py url              # 打印 OBS 浏览器源地址（含 token）
  python tools/live_service.py status           # 查看状态/队列/回执
  python tools/live_service.py arm              # 武装出口（默认 obs_browser/监听关闭）
  python tools/live_service.py disarm           # 解除武装（停播，不增代际）
  python tools/live_service.py stop             # 急停：取消全部、增代际、撤租约
  python tools/live_service.py say "文本"        # 合成一句入队
  python tools/live_service.py say-batch        # 固定 10 句（或 --file 每行一句）
  python tools/live_service.py replay a.wav b.wav --arm   # 重放缓存 WAV（不重新合成）
  python tools/live_service.py probe            # 生成 route_probe.json 证据
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.audio_sink import (  # noqa: E402
    DEFAULT_CONFIG_PATH, load_config, make_server, token_fingerprint,
)

FIXED_TEN = [
    "大家好，我是元亨。",
    "这是第一次在直播间里出声。",
    "现在是本地合成，不经过电脑扬声器。",
    "如果你能听到我，说明音频已经进入 OBS。",
    "这一句用来测试连续播放。",
    "中途停止时，不应该留下残音。",
    "断线重连之后，不应该重复播放。",
    "采样率保持二十四千赫兹。",
    "音量以 OBS 混音器电平为准。",
    "第十段结束，本轮测试完成。",
]


def base_url(config) -> str:
    return f"http://{config.host}:{config.port}"


def request_json(method: str, url: str, payload=None, timeout: float = 300.0):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return {"_http_status": exc.code, **json.loads(body)}
        except json.JSONDecodeError:
            return {"_http_status": exc.code, "error": body}


def print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2), flush=True)


def control(config, action: str, **extra) -> dict:
    payload = {"token": config.lease_token, "action": action, **extra}
    return request_json("POST", f"{base_url(config)}/control", payload)


def unwrap(resp: dict) -> dict:
    if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
        return resp["result"]
    return resp


def cmd_serve(config, args) -> int:
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    server = make_server(config)
    port = server.server_address[1]
    obs_url = (f"http://{config.host}:{port}/player"
               f"?token={config.lease_token}&client_id=obs-browser")
    print_json({
        "listening": f"http://{config.host}:{port}",
        "token_sha256_16": token_fingerprint(config.lease_token),
        "obs_browser_source_url": obs_url,
        "obs_setup": [
            "添加浏览器源 YuanhengVoice，粘贴上面的 URL",
            "勾选“通过 OBS 控制音频”，高级音频属性中“监听关闭”，勿静音",
            "不要用系统扬声器/Windows侦听/Desktop Audio 重复捕获",
        ],
        "note": "未武装(arm)时不派发音频；/audio 校验 token 且要求已武装",
    })
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_url(config, args) -> int:
    print(base_url(config) + "/player?token="
          + config.lease_token + "&client_id=obs-browser")
    return 0


def cmd_status(config, args) -> int:
    print_json(request_json("GET", f"{base_url(config)}/status", timeout=15))
    return 0


def cmd_arm(config, args) -> int:
    print_json(control(config, "arm", route=args.route, monitor=args.monitor))
    return 0


def cmd_disarm(config, args) -> int:
    print_json(control(config, "disarm"))
    return 0


def cmd_stop(config, args) -> int:
    print_json(control(config, "stop", reason=args.reason))
    return 0


def cmd_say(config, args) -> int:
    text = " ".join(args.text).strip()
    print_json(unwrap(control(config, "say", text=text, client_id="control")))
    return 0


def cmd_say_batch(config, args) -> int:
    if args.file:
        lines = [ln.strip() for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
    else:
        lines = FIXED_TEN
    results = []
    started = time.monotonic()
    for index, text in enumerate(lines, 1):
        raw = control(config, "say", text=text, client_id="control")
        inner = unwrap(raw)
        ok = bool(inner.get("segment_id"))
        results.append({"i": index, "text": text, "ok": ok,
                        "segment_id": inner.get("segment_id"),
                        "synth_ms": inner.get("synth_ms"),
                        "error": raw.get("error") or inner.get("error")})
        if not ok:
            break
    print_json({"count": len(results), "elapsed_s": round(time.monotonic() - started, 2),
                "items": results})
    return 0


def _obs_checks() -> dict:
    checks = {}
    checks["obs_exe"] = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe").exists()
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace").stdout
        checks["obs_process_running"] = "obs64.exe" in out.lower()
    except Exception as exc:  # noqa: BLE001
        checks["obs_process_running"] = None
        checks["obs_process_error"] = str(exc)
    ws_config = Path(os.environ.get("APPDATA", "")) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    try:
        data = json.loads(ws_config.read_text(encoding="utf-8"))
        checks["obs_websocket_enabled"] = bool(data.get("server_enabled"))
        checks["obs_websocket_port"] = data.get("server_port")
        checks["obs_websocket_auth_required"] = bool(data.get("auth_required"))
    except (OSError, json.JSONDecodeError):
        checks["obs_websocket_enabled"] = None
    return checks


def cmd_replay(config, args) -> int:
    if args.arm:
        control(config, "arm", route="obs_browser", monitor="off")
    results = []
    for name in args.files:
        raw = control(config, "enqueue_audio", filename=name, client_id="control")
        inner = unwrap(raw)
        results.append({"file": name, "ok": bool(inner.get("segment_id")),
                        "segment_id": inner.get("segment_id"),
                        "duration_s": inner.get("duration_s"),
                        "source": inner.get("source"),
                        "error": raw.get("error") or inner.get("error")})
    print_json({"count": len(results), "items": results})
    return 0


def cmd_probe(config, args) -> int:
    status = request_json("GET", f"{base_url(config)}/status", timeout=15)
    report = {
        "probed_at_ms": int(time.time() * 1000),
        "service": base_url(config),
        "token_sha256_16": token_fingerprint(config.lease_token),
        "checks": _obs_checks(),
        "status": status,
        "limits": [
            "obs-websocket 未启用时无法自动验证“监听关闭/通过OBS控制音频”",
            "监听/路由的最终判定以 OBS 界面 + 本地录制 + 扬声器实听为准",
        ],
    }
    out = Path(args.out) if args.out else ROOT / "artifacts" / "live_l1" / "route_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_json({"out": str(out), "obs": report["checks"],
                "armed": status.get("armed"), "generation": status.get("generation"),
                "queue_len": len(status.get("queue") or [])})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YHLZ L1 直播音频服务")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve")
    p.add_argument("--host")
    p.add_argument("--port", type=int)

    sub.add_parser("url")
    sub.add_parser("status")

    p = sub.add_parser("arm")
    p.add_argument("--route", default="obs_browser")
    p.add_argument("--monitor", default="off")

    sub.add_parser("disarm")

    p = sub.add_parser("stop")
    p.add_argument("--reason", default="owner")

    p = sub.add_parser("say")
    p.add_argument("text", nargs="+")

    p = sub.add_parser("say-batch")
    p.add_argument("--file")

    p = sub.add_parser("replay")
    p.add_argument("files", nargs="+")
    p.add_argument("--arm", action="store_true", help="先武装再重放")

    p = sub.add_parser("probe")
    p.add_argument("--out")
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    args = build_parser().parse_args()
    config = load_config(Path(args.config))
    commands = {
        "serve": cmd_serve, "url": cmd_url, "status": cmd_status,
        "arm": cmd_arm, "disarm": cmd_disarm, "stop": cmd_stop,
        "say": cmd_say, "say-batch": cmd_say_batch, "replay": cmd_replay,
        "probe": cmd_probe,
    }
    return commands[args.command](config, args)


if __name__ == "__main__":
    raise SystemExit(main())
