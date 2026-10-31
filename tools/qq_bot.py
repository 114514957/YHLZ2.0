# QQ 机器人相关功能（OneBot11 桥接）
r"""YHLZ QQ bot bridge (ledger 0226): OneBot11 forward WebSocket -> daemon.

Listens on a NapCat OneBot11 WebSocket server and turns private messages /
group @-mentions into daemon turns (channel qq_p<uid> / qq_g<gid>), then sends
Yuanheng's answer back. Owner private chat and public groups have separate memory/persona boundaries.

Usage:
    python tools/qq_bot.py --uin 2258374446          # use qqwatch onebot config
    python tools/qq_bot.py --config path\to\onebot11_<uin>.json
    python tools/qq_bot.py                           # auto-pick first enabled ws
Env DAEMON=http://127.0.0.1:8321
"""
from __future__ import annotations

import argparse
from collections import OrderedDict, deque
import asyncio
import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.request
import uuid

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(_PROJECT / "tools"))
from backend.yhlz_paths import EXTERNAL, MASTER_UIN, QQWATCH_CONFIG  # noqa: E402
from backend.qq_bridge_state import path as _bridge_path  # noqa: E402
from backend.qq_bridge_state import profile as _bridge_profile  # noqa: E402
from backend.qq_bridge_state import state_dir as _bridge_state_dir  # noqa: E402
from backend.qq_connection import (  # noqa: E402
    ConnectionSnapshot, heartbeat_loop, websocket_options,
)
from backend.qq_delivery import DeliveryManager, DeliveryTransportError  # noqa: E402

try:
    import dev_runner
except Exception:  # noqa: BLE001
    dev_runner = None

CONFIG_DIR = _PROJECT / "cache" / "tmp"  # fallback; use qqwatch path
DAEMON = os.getenv("DAEMON", "http://127.0.0.1:8321")
MEDIA_DIR = _bridge_path("media", _PROJECT / "cache" / "qq_media")
MEDIA_KEEP_DAYS = 7
IMG_MAX_BYTES = 8 * 1024 * 1024        # group/private image cap
AUDIO_MAX_BYTES = 10 * 1024 * 1024
AUDIO_MAX_SECONDS = 60                 # voice clip cap
_LITE_PROFILE = _bridge_profile() != "full"
# 参与频率（2026-10-06）：Lite 默认更克制；主人指令/主人私聊不受此限。
GROUP_USER_COOLDOWN = float(os.getenv(
    "YHLZ_QQ_GROUP_USER_COOLDOWN", "30" if _LITE_PROFILE else "8"))
GROUP_CHAN_PER_MIN = int(os.getenv(
    "YHLZ_QQ_GROUP_CHAN_PER_MIN", "6" if _LITE_PROFILE else "20"))
GROUP_CHAN_GAP = float(os.getenv(
    "YHLZ_QQ_GROUP_CHAN_GAP", "20" if _LITE_PROFILE else "0"))
GROUP_DAILY_LIMIT = int(os.getenv(
    "YHLZ_QQ_GROUP_DAILY_LIMIT", "120" if _LITE_PROFILE else "400"))
PRIVATE_USER_COOLDOWN = float(os.getenv(
    "YHLZ_QQ_PRIVATE_USER_COOLDOWN", "30" if _LITE_PROFILE else "8"))
MESSAGE_DEDUP_TTL = 15 * 60           # process-local reconnect replay protection
MESSAGE_DEDUP_LIMIT = 2048
INBOX_LIMIT = int(os.getenv("YHLZ_QQ_INBOX_LIMIT", "128"))
CHAT_CONCURRENCY = int(os.getenv("YHLZ_QQ_CHAT_CONCURRENCY", "2"))
QQ_PING_INTERVAL = float(os.getenv("YHLZ_QQ_PING_INTERVAL", "25"))
QQ_PONG_TIMEOUT = float(os.getenv("YHLZ_QQ_PONG_TIMEOUT", "10"))
QQ_CONNECT_TIMEOUT = float(os.getenv("YHLZ_QQ_CONNECT_TIMEOUT", "10"))
QQ_STATUS = _bridge_path("bridge_status.json",
                         _PROJECT / "cache" / "tmp" / "qq_bridge_status.json")


def _voice_mode() -> str:
    """full = warm ASR at start; lazy = load on first record; text_only."""
    flag = os.getenv("YHLZ_QQ_ENABLE_VOICE", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return "lazy"
    if flag in ("0", "false", "no", "off"):
        return "text_only" if _bridge_profile() != "full" else "full"
    return "full" if _bridge_profile() == "full" else "text_only"


def _wake_gate_enabled() -> bool:
    """群唤醒闸门（2026-10-08）：默认只在 @/名字/已知知识/主人 时唤醒。"""
    return os.getenv("YHLZ_QQ_WAKE", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _wake_names() -> tuple:
    raw = os.getenv("YHLZ_QQ_WAKE_NAMES", "元亨,利贞")
    out: list[str] = []
    for part in re.split(r"[,，;；\s]+", str(raw or "")):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return tuple(out)


def _wake_topics_enabled() -> bool:
    return os.getenv("YHLZ_QQ_WAKE_TOPICS", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _wake_topic_min_chars() -> int:
    try:
        return max(1, int(float(os.getenv("YHLZ_QQ_WAKE_TOPIC_MIN", "4"))))
    except Exception:  # noqa: BLE001
        return 4


def _wake_master_always() -> bool:
    return os.getenv("YHLZ_QQ_WAKE_MASTER", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _wake_at_only_groups() -> frozenset:
    """仅 @ 才唤醒的群（2026-10-10，逗号分隔；空 = 无）。"""
    raw = os.getenv("YHLZ_QQ_WAKE_AT_ONLY_GROUPS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip() for p in re.split(r"[,，;；\s]+", raw)
                     if p.strip())


MODE_LABELS = {"lively": "活泼", "reserved": "内敛", "silent": "缄默"}


def _wake_mode() -> str:
    """对话档位（2026-10-11）：活泼 lively / 内敛 reserved / 缄默 silent。

    运行时由主人 # 指令切换并持久化（qq_state.json）；缺省读环境/配置。
    - 活泼：现行唤醒闸门（@/名字/知识/引用/主人始终）——默认。
    - 内敛：群里只有 @ 或叫名字才回；私聊正常。
    - 缄默：群里彻底沉默（@ 也不回）；私聊也静默；# 指令与系统通知不受影响。
    """
    raw = ""
    try:
        raw = str(_load_state().get("wake_mode") or "")
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw:
        raw = os.getenv("YHLZ_QQ_WAKE_MODE", "lively")
    v = str(raw).strip().lower()
    if v in ("内敛", "reserved"):
        return "reserved"
    if v in ("缄默", "silent", "mute"):
        return "silent"
    return "lively"


def _set_wake_mode(mode: str) -> None:
    st = _load_state()
    st["wake_mode"] = mode
    _save_state(st)


def _profile_inject_enabled() -> bool:
    """群友档案卡注入当前轮上下文（2026-10-09，默认开）。"""
    return os.getenv("YHLZ_QQ_PROFILE_INJECT", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _wake_memory_enabled() -> bool:
    """知识唤醒是否带上记忆库（经历/偏好/决定，2026-10-08）。"""
    return os.getenv("YHLZ_QQ_WAKE_MEMORY", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _silence_enabled() -> bool:
    """被唤醒后的“不接”出口（模型可输出 [[silence]]）。"""
    return os.getenv("YHLZ_QQ_WAKE_SILENCE", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _allowed_groups():
    """群白名单（YHLZ_QQ_GROUPS，逗号分隔）；空 = 不限制。"""
    raw = os.getenv("YHLZ_QQ_GROUPS", "").strip()
    if not raw:
        return None
    out = {p.strip() for p in re.split(r"[,，;；\s]+", raw) if p.strip()}
    return frozenset(out) if out else None


_SILENCE_RE = re.compile(r"\[\[(?:silence|沉默)\]\][。.!！?？～~\s]*", re.I)
SENT_MSG_ID_LIMIT = 2048


def _redact_url(url: str) -> str:
    """Never log access_token query strings or credentials."""
    try:
        from urllib.parse import urlsplit, urlunsplit

        p = urlsplit(str(url))
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    except Exception:
        return "ws://***"


def _process_create_time() -> float:
    try:
        import psutil

        return float(psutil.Process(os.getpid()).create_time())
    except Exception:
        return 0.0


_lite_dev = None


def _dev_mod():
    """Full keeps the legacy runner; Lite uses the profile-scoped dev runner."""
    global _lite_dev
    if _bridge_profile() == "full":
        return dev_runner
    if _lite_dev is not None:
        return _lite_dev
    try:
        import importlib

        _lite_dev = importlib.import_module("qq_dev_runner")
    except Exception as exc:  # noqa: BLE001
        print(f"[qqbot] lite dev runner 不可用: {type(exc).__name__}", flush=True)
        _lite_dev = dev_runner
    return _lite_dev


# 群聊可发的媒体只允许来自这些“授权发布目录”（模型输出的 `[[img:]]/[[file:]]`
# 只在群里按此放行；主人 `#img/#file` 仍可指定非危险文件）。可用环境变量
# YHLZ_QQ_PUBLISH_DIRS（os.pathsep 分隔）覆盖。
_PUBLISH_ENV = os.getenv("YHLZ_QQ_PUBLISH_DIRS", "").strip()
PUBLISH_DIRS = tuple(
    pathlib.Path(p) for p in _PUBLISH_ENV.split(os.pathsep) if p.strip()
) or (
    _PROJECT / "音频素材" / "发布",
    _PROJECT / "cache" / "qq_publish",
)
# QQ 群参与（2026-09-30）：无需 @ 也接话；向上 20 条上下文；每天群聊上限 400 条。
GROUP_HISTORY_TURNS = 20
GROUP_DAILY_STATE = _bridge_path("qq_group_daily.json",
                                 _PROJECT / "cache" / "tmp" / "qq_group_daily.json")
STICKER_DIR = _bridge_path("stickers", _PROJECT / "cache" / "qq_stickers")


def _save_media(data: bytes, ext: str, max_bytes: int = 0) -> str:
    import hashlib

    if max_bytes and len(data) > max_bytes:
        return ""
    day = time.strftime("%Y%m%d")
    d = MEDIA_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(data).hexdigest()[:16]
    p = d / f"{h}.{ext or 'jpg'}"
    p.write_bytes(data)
    return str(p)


def _cleanup_media(days: int = MEDIA_KEEP_DAYS) -> None:
    cutoff = time.time() - days * 86400
    try:
        for f in MEDIA_DIR.rglob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


async def _napcat_call(ws_url: str, action: str, params: dict,
                       timeout: float = 15.0) -> dict | None:
    """One-shot OneBot API call over a short-lived WS connection."""
    import websockets

    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            echo = f"n{int(time.time()*1000)}"
            await ws.send(json.dumps({"action": action, "params": params,
                                      "echo": echo}))
            end = time.time() + timeout
            while time.time() < end:
                raw = await asyncio.wait_for(ws.recv(),
                                             timeout=max(1.0, end - time.time()))
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                if ev.get("echo") == echo:
                    return ev
    except Exception:
        return None
    return None


# ---- voice (inbound) ----
_ASR = None
_ASR_DEVICE = os.getenv("YHLZ_ASR_DEVICE", "cpu")
_SENSEVOICE_DIR = _PROJECT / "models" / "voice" / "asr" / "SenseVoiceSmall"


def _decode_to_pcm16k(path: str):
    """Local audio file -> float32 mono 16k numpy (silk via pilk, else ffmpeg).

    Never deletes the source file (writes converted audio to a temp dir).
    """
    import tempfile

    import numpy as np

    p = pathlib.Path(path)
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_aud_"))
    try:
        if p.suffix.lower() == ".silk":
            import pilk

            out = tmpdir / "a.pcm"
            pilk.decode(str(p), str(out), 16000)
            return np.fromfile(str(out), dtype="<i2").astype("float32") / 32768.0
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        out = tmpdir / "a16.wav"
        import subprocess

        subprocess.run([exe, "-y", "-i", str(p), "-ac", "1", "-ar", "16000",
                        str(out)], capture_output=True)
        import wave

        with wave.open(str(out), "rb") as w:
            frames = w.readframes(w.getnframes())
        return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def _transcribe_audio(audio) -> str:
    """SenseVoiceSmall (device=YHLZ_ASR_DEVICE, default cpu) -> clean text."""
    global _ASR
    import re

    try:
        if _ASR is None:
            from funasr import AutoModel

            os.chdir(str(_PROJECT))  # funasr/sentencepiece relative-path quirk
            _ASR = AutoModel(
                model=str(_SENSEVOICE_DIR.relative_to(_PROJECT)),
                device=_ASR_DEVICE, disable_update=True,
                disable_pbar=True, disable_log=True)
        r = _ASR.generate(input=audio, language="zh", use_itn=True,
                          batch_size_s=60)
        text = str((r[0] or {}).get("text") or "") if r else ""
    except Exception:
        return ""
    text = re.sub(r"\b(SIL|MM|UM|UH|SPK|SPEAKER|NOISE|MUSIC|LAUGH)\b", " ",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"[\[<].*?[\]>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _warm_asr() -> None:
    """Load SenseVoice in the background so the first voice msg isn't slow."""
    try:
        _transcribe_audio(__import__("numpy").zeros(8000, dtype="float32"))
    except Exception:
        pass


# ---- outbound (TTS voice / image / file) ----
QQ_STATE = _bridge_path("qq_state.json",
                        _PROJECT / "cache" / "tmp" / "qq_state.json")
NOTICES = _bridge_path("notices.jsonl",
                       _PROJECT / "cache" / "tmp" / "qq_notices.jsonl")


def _load_state() -> dict:
    try:
        return json.loads(QQ_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    try:
        QQ_STATE.parent.mkdir(parents=True, exist_ok=True)
        QQ_STATE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _voice_intent(text: str) -> bool:
    t = str(text or "")
    return any(k in t for k in ("用语音", "发语音", "语音回", "语音说",
                                "说给我听", "念给我听", "说给我听"))


def _extract_markers(ans: str) -> tuple:
    import re

    imgs = re.findall(r"\[\[img:\s*(.+?)\]\]", ans)
    files = re.findall(r"\[\[file:\s*(.+?)\]\]", ans)
    faces = re.findall(r"\[\[face:\s*(\d+)\]\]", ans)
    devs = re.findall(r"\[\[dev:\s*(.+?)\]\]", ans)
    mfaces = re.findall(r"\[\[mface:\s*([^\]]+?)\]\]", ans)
    stickers = re.findall(r"\[\[sticker:\s*([^\]]+?)\]\]", ans)
    ats = re.findall(r"\[\[at:\s*(\d+)\]\]", ans)
    replies = re.findall(r"\[\[reply:\s*([^\]\s]+?)\]\]", ans)
    voice = "[[voice]]" in ans
    ans = re.sub(r"\[\[(?:img|file):.*?\]\]", "", ans)
    ans = re.sub(r"\[\[face:\s*\d+\]\]", "", ans)
    ans = re.sub(r"\[\[(?:mface|sticker):.*?\]\]", "", ans)
    ans = re.sub(r"\[\[dev:\s*.*?\]\]", "", ans)
    ans = re.sub(r"\[\[at:\s*\d+\]\]", "", ans)
    ans = re.sub(r"\[\[reply:.*?\]\]", "", ans)
    ans = ans.replace("[[voice]]", "")
    return (ans.strip(), imgs, files, faces, voice, devs, mfaces, stickers,
            ats, replies)


def _tts_wav(text: str) -> str:
    """Text -> wav (24k mono). edge-tts (natural, needs net); SAPI fallback."""
    import subprocess
    import tempfile

    text = str(text or "").strip()
    if not text:
        return ""
    d = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_tts_"))
    wav = d / "t.wav"
    # 0) A4b (ledger 0454): daemon clone voice (Edge/Xiaoyi timbre, local GPU)
    if os.getenv("YHLZ_QQ_TTS", "clone").lower() != "edge":
        try:
            req = urllib.request.Request(
                DAEMON + "/tts",
                data=json.dumps({"text": text, "model": os.getenv(
                    "YHLZ_QQ_TTS", "clone")}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as r:
                data = r.read()
            if data[:4] == b"RIFF" and len(data) > 44:
                wav.write_bytes(data)
                return str(wav)
        except Exception:
            pass
    engine = os.getenv("YHLZ_TTS_ENGINE", "edge").lower()
    # 1) edge-tts (neural, primary; needs network)
    if engine != "sapi":
        try:
            import asyncio as _a

            import edge_tts

            mp3 = d / "t.mp3"
            voice = os.getenv("YHLZ_TTS_VOICE", "zh-CN-XiaoyiNeural")
            rate = os.getenv("YHLZ_TTS_RATE", "+8%")

            async def _go() -> None:
                await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))

            _a.run(_go())
            if mp3.exists() and mp3.stat().st_size > 0:
                import imageio_ffmpeg

                exe = imageio_ffmpeg.get_ffmpeg_exe()
                subprocess.run([exe, "-y", "-i", str(mp3), "-ac", "1", "-ar",
                                "24000", str(wav)], capture_output=True)
                if wav.exists() and wav.stat().st_size > 44:
                    return str(wav)
        except Exception:
            pass
    # 2) SAPI fallback (offline)
    import base64 as _b64

    b64 = _b64.b64encode(text.encode("utf-8")).decode()
    ps = ("Add-Type -AssemblyName System.Speech; "
          f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')); "
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak($t); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps], capture_output=True, timeout=60)
    except Exception:
        return ""
    return str(wav) if wav.exists() else ""


def _wav_to_silk(wav: str) -> str:
    """wav -> QQ silk (24k mono) via ffmpeg + pilk. Empty on failure."""
    import subprocess
    import tempfile

    try:
        import imageio_ffmpeg
        import pilk

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        d = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_silk_"))
        w24 = d / "a24.wav"
        subprocess.run([exe, "-y", "-i", str(wav), "-ac", "1", "-ar", "24000",
                        str(w24)], capture_output=True)
        silk = d / "a.silk"
        pilk.encode(str(w24), str(silk), 24000, tencent=True)
        return str(silk) if silk.exists() else ""
    except Exception:
        return ""


def _find_onebot_config(uin: str | None) -> pathlib.Path:
    cands = []
    for d in (QQWATCH_CONFIG,
              EXTERNAL / "NEKO" / "desktop" / "resources" / "bin" / "plugin"
              / "plugins" / "qq_auto_reply" / "NapCat.Shell" / "config"):
        if not d.exists():
            continue
        pat = f"onebot11_{uin}.json" if uin else "onebot11_*.json"
        cands += sorted(d.glob(pat))
    if not cands:
        raise SystemExit("未找到 onebot11 配置：请先让 NapCat 登录小号生成配置，"
                         "或用 --config 指定")
    if not uin and len(cands) > 1:
        # 2026-09-29 fix: default must be the BOT account, not the master's.
        # onebot11_*.json sorts the master (2258...) first; pick a non-master
        # config so private messages are received as the bot.
        non_master = [c for c in cands if str(MASTER_UIN) not in c.stem]
        if non_master:
            return non_master[0]
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


def _daemon_turn(text: str, channel: str, images: list | None = None) -> dict:
    # ChannelAuth (Step 1, 2026-09-29): the daemon now requires a matching
    # `source`; QQ channels must declare qq_bridge or they get 403.
    source = "qq_bridge" if str(channel).startswith("qq_") else "console"
    body: dict = {"text": str(text)[:1500], "channel": channel, "source": source}
    if images:
        body["images"] = [str(p) for p in images][:4]
    data = json.dumps(body).encode()
    req = urllib.request.Request(DAEMON + "/turn", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        # long tool-using tasks must not lose the reply halfway (daemon allows
        # up to 240s); ledger 0443
        with urllib.request.urlopen(req, timeout=280) as r:
            # Full info dict: answer + attachments (file.share, 2026-10-06).
            return json.loads(r.read())
    except Exception as exc:
        # Do not turn transport errors into a successful-looking silent reply.
        raise RuntimeError("daemon turn failed") from exc


class _DeliveryTransport:
    """Adapter letting DeliveryManager send over the *current* socket.

    The manager owns delivery state; the bridge owns the socket.  Holding the
    live socket here (updated per connection) keeps the manager free of ws
    lifecycle and lets it label a pre-submit failure as retryable.
    """

    def __init__(self, bridge: "QQBridge") -> None:
        self._bridge = bridge
        self.ws = None

    async def __call__(self, action: str, params: dict):
        ws = self.ws
        if ws is None:
            raise DeliveryTransportError("no live socket", stage="before_send")
        return await self._bridge._request(ws, action, params)


class QQBridge:
    def __init__(self, ws, uin: str, cfg: pathlib.Path,
                 masters: set[str] | None = None):
        self.ws_url = ws
        self.uin = str(uin)
        self.cfg = cfg
        self.masters = set(masters) if masters is not None else {MASTER_UIN}
        self.log_n = 0
        self.loop = None
        self._last_reply: dict = {}
        self._chan_reply: dict = {}
        self._last_chan_reply: dict = {}
        self._seen_events: OrderedDict[tuple, float] = OrderedDict()
        self.duplicate_events = 0
        self.backend_errors = 0
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}
        self.connection = ConnectionSnapshot()
        self._last_connection_state = ""
        # Phase 2: every outbound send_msg goes through one delivery manager so
        # the bridge knows confirmed / rejected / retryable / unknown.
        self._transport = _DeliveryTransport(self)
        self.delivery = DeliveryManager(self._transport)
        # QQ 群参与状态：每群向上 20 条上下文 + 每天群聊回复配额。
        self._group_history: dict[str, deque] = {}
        self._group_daily = self._load_group_daily()
        # P1 (2026-10-06): reader/inbox separation + control channel.
        self.conversation = "optional"
        self.instance_id = uuid.uuid4().hex[:12]
        self.started_at = time.time()
        self.proc_create_time = _process_create_time()
        self.inbox: asyncio.Queue | None = None
        self.inbox_busy = 0
        self.inbox_processed = 0
        self._inbox_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None
        self._profile_task: asyncio.Task | None = None
        self._profile_store = None
        self._ws = None
        self._ws_ready = asyncio.Event()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._control_lock = asyncio.Lock()
        self._chat_sem = asyncio.Semaphore(max(1, CHAT_CONCURRENCY))
        self._tasks: set[asyncio.Task] = set()
        self._dev_busy = False
        self._dev_state_cache: dict = {"status": "unknown", "task": ""}
        self._dev_state_ts = 0.0
        # P4: profile-scoped group history / sticker library / chat degrade.
        self._social_store = None
        self._group_store = None
        self._sticker_store = None
        self._daemon_health_cache: tuple[float, bool] = (0.0, False)
        self._degrade_sent: dict[str, float] = {}
        # 唤醒闸门（2026-10-08）：记录本桥发出的群消息 ID，用于“引用回复她”判定。
        self._sent_msg_ids: OrderedDict[str, float] = OrderedDict()

    def _load_group_daily(self) -> dict:
        import datetime as _dt

        today = _dt.date.today().isoformat()
        try:
            data = json.loads(GROUP_DAILY_STATE.read_text(encoding="utf-8"))
            if str(data.get("date")) == today:
                return {"date": today, "count": int(data.get("count", 0) or 0)}
        except Exception:
            pass
        return {"date": today, "count": 0}

    def _save_group_daily(self) -> None:
        try:
            GROUP_DAILY_STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = GROUP_DAILY_STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._group_daily, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(GROUP_DAILY_STATE)
        except Exception:
            pass

    def _group_daily_ok(self) -> bool:
        """每天群聊回复上限（默认 400）；跨天自动归零。"""
        import datetime as _dt

        today = _dt.date.today().isoformat()
        if self._group_daily.get("date") != today:
            self._group_daily = {"date": today, "count": 0}
        if int(self._group_daily.get("count", 0)) >= GROUP_DAILY_LIMIT:
            return False
        self._group_daily["count"] = int(self._group_daily.get("count", 0)) + 1
        self._save_group_daily()
        return True

    def _note_group_history(self, channel: str, user_id: str, text: str) -> None:
        hist = self._group_history.get(channel)
        if hist is None:
            hist = deque(maxlen=GROUP_HISTORY_TURNS)
            self._group_history[channel] = hist
        label = "元亨" if str(user_id) == self.uin else f"user{user_id}"
        hist.append(f"{label}: {text}")

    def _group_context(self, channel: str) -> str:
        hist = self._group_history.get(channel)
        if not hist:
            return ""
        return "\n".join(hist)

    def _group_db(self):
        if self._group_store is None:
            from backend.qq_group_store import GroupHistoryStore

            default_turns = "20" if _bridge_profile() == "full" else "50"
            turns = int(os.getenv("YHLZ_QQ_GROUP_TURNS", default_turns))
            self._group_store = GroupHistoryStore(
                _bridge_path("group_history.db",
                             _PROJECT / "cache" / "tmp" / "qq_group_history.db"),
                bot_uin=self.uin, turns=turns)
        return self._group_store

    def _stickers_db(self):
        if self._sticker_store is None:
            from backend.qq_stickers import StickerStore

            self._sticker_store = StickerStore(
                _bridge_path("stickers.db",
                             _PROJECT / "cache" / "tmp" / "qq_stickers.db"),
                media_dir=STICKER_DIR)
        return self._sticker_store

    def _profiles_db(self):
        if getattr(self, "_profile_store", None) is None:
            from backend.qq_profiles import MemberProfileStore

            self._profile_store = MemberProfileStore(
                _bridge_path("profiles.db",
                             _PROJECT / "cache" / "tmp" / "qq_profiles.db"))
        return self._profile_store

    def _rebuild_profiles(self, min_messages: int) -> int:
        return self._profiles_db().rebuild(
            self._group_db(), min_messages=min_messages,
            masters=self.masters, bot_uin=self.uin)

    @staticmethod
    def _scope_of(params: dict) -> str:
        if str(params.get("message_type")) == "group":
            return "group:" + str(params.get("group_id"))
        return "private:" + str(params.get("user_id"))

    def _daemon_ok(self, ttl: float = 5.0) -> bool:
        """Short daemon health probe; never starts or loads anything."""
        now = time.time()
        ts, ok = self._daemon_health_cache
        if now - ts < ttl:
            return ok
        ok = False
        try:
            import socket
            from urllib.parse import urlsplit

            parts = urlsplit(DAEMON)
            host = parts.hostname or "127.0.0.1"
            port = parts.port or (443 if parts.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=2.0):
                ok = True
        except Exception:
            ok = False
        self._daemon_health_cache = (now, ok)
        return ok

    def log(self, msg: str) -> None:
        print(f"[qqbot] {msg}", flush=True)

    def _dev_state(self) -> dict:
        now = time.time()
        if now - self._dev_state_ts < 2.0:
            return self._dev_state_cache
        self._dev_state_ts = now
        try:
            if _bridge_profile() == "full" and dev_runner is not None:
                d = dev_runner._load()
                self._dev_state_cache = {"status": str(d.get("status", "")),
                                         "task": str(d.get("task", ""))[:60]}
            else:
                # 0831：Lite 的任务在 dev_jobs.db，旧 _dev_state 读的是
                # cache/dev/state.json（另一条已退役的链），面板会显示错任务。
                from backend.target_dev_bridge import dev_status

                d = dev_status()
                self._dev_state_cache = {
                    "status": str(d.get("status") or "idle"),
                    "task": str(d.get("task") or "")[:60],
                }
        except Exception:
            self._dev_state_cache = {"status": "unknown", "task": ""}
        return self._dev_state_cache

    def _write_status(self) -> None:
        """Write redacted health only; never write tokens or message text."""
        try:
            QQ_STATUS.parent.mkdir(parents=True, exist_ok=True)
            data = self.connection.as_dict()
            data.update({
                "pid": os.getpid(),
                "create_time": self.proc_create_time,
                "started_at": self.started_at,
                "instance_id": self.instance_id,
                "profile": _bridge_profile(),
                "conversation": self.conversation,
                "voice_mode": _voice_mode(),
                "dev_state": self._dev_state(),
                "inbox": {
                    "limit": self.inbox.maxsize if self.inbox else INBOX_LIMIT,
                    "pending": self.inbox.qsize() if self.inbox else 0,
                    "busy": self.inbox_busy,
                    "processed": self.inbox_processed,
                },
            })
            tmp = QQ_STATUS.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(QQ_STATUS)
        except Exception:
            pass

    def _set_state(self, state: str, error: str = "") -> None:
        self.connection.state = state
        if error:
            self.connection.last_error = error[:120]
        if state != self._last_connection_state:
            self._last_connection_state = state
            self.log(f"连接状态: {state}")
        self._write_status()

    def _fail_pending(self, exc: BaseException) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)

    # ---- P1: bounded inbox / session-serial workers (guide 13.2) ----
    def _track_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.log(f"后台任务异常 {type(exc).__name__}: {exc}")

    @staticmethod
    def _event_channel(ev: dict) -> str:
        if ev.get("message_type") == "private":
            return f"qq_p{ev.get('user_id', '')}"
        return f"qq_g{ev.get('group_id', '')}"

    def _is_owner_command(self, ev: dict) -> bool:
        user_id = str(ev.get("user_id", ""))
        if user_id not in self.masters:
            return False
        msg = ev.get("message")
        if not isinstance(msg, list):
            return False
        text, _ats = self._text_of(msg)
        return text.strip().replace("＃", "#").startswith("#")

    def _enqueue(self, ev: dict) -> None:
        q = self.inbox
        if q is None:
            self._track_task(asyncio.create_task(
                self._process_message(ev, self._event_channel(ev),
                                      self._session_locks.setdefault(
                                          self._event_channel(ev),
                                          asyncio.Lock()),
                                      self._is_owner_command(ev))))
            return
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            self.inbox_busy += 1
            self.connection._extra["inbox_busy"] = self.inbox_busy
            self.log(f"inbox 队列已满({q.maxsize})，本轮丢弃一条，不阻塞收包")

    async def _process_message(self, ev: dict, channel: str,
                               lock: asyncio.Lock, control: bool) -> None:
        await self._ws_ready.wait()
        if control:
            # 控制通道：不等待同会话的慢模型调用，只与其它控制命令串行。
            async with self._control_lock:
                await self.handle(self._ws, ev)
        else:
            async with lock:
                async with self._chat_sem:
                    await self.handle(self._ws, ev)
        self.inbox_processed += 1

    async def _inbox_worker(self) -> None:
        assert self.inbox is not None
        while True:
            ev = await self.inbox.get()
            channel = self._event_channel(ev)
            lock = self._session_locks.setdefault(channel, asyncio.Lock())
            self._track_task(asyncio.create_task(
                self._process_message(ev, channel, lock,
                                      self._is_owner_command(ev))))

    def _text_of(self, msg_array) -> tuple[str, list]:
        texts, ats = [], []
        for seg in msg_array or []:
            if seg.get("type") == "text":
                value = seg.get("data", {}).get("text", "")
                if isinstance(value, str):
                    texts.append(value)
            elif seg.get("type") == "at":
                ats.append(str(seg.get("data", {}).get("qq", "")))
        return "".join(texts).strip(), ats

    @staticmethod
    def _media_placeholders(msg) -> list:
        out = []
        for seg in msg or []:
            kind = seg.get("type")
            data = seg.get("data") or {}
            if kind == "image":
                out.append({"type": "image"})
            elif kind in ("face", "mface"):
                out.append({"type": kind,
                            "id": str(data.get("id") or data.get("emoji_id")
                                      or "")})
            elif kind == "record":
                out.append({"type": "record"})
        return out[:4]

    async def _send_payload(self, ws, action: str, params: dict, echo: str) -> None:
        async with self._send_lock:
            await ws.send(json.dumps({"action": action, "params": params,
                                      "echo": echo}))
            self.connection.last_tx_at = time.time()
            self._write_status()

    async def _send(self, ws, action: str, params: dict) -> None:
        """Fire-and-forget API send used for ordinary replies."""
        await self._send_payload(ws, action, params, f"y{int(time.time()*1000)}")

    async def _request(self, ws, action: str, params: dict, timeout: float = 15.0) -> dict:
        """Send an API request over the existing socket and await its echo.

        Failures are labelled for the delivery manager: a socket that dies
        *before* submit is ``before_send`` (safe to retry); a timeout or a
        post-submit disconnect is ``after_send`` (never blindly resent).
        """
        echo = f"y{time.time_ns()}"
        fut = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        try:
            try:
                await self._send_payload(ws, action, params, echo)
            except Exception as exc:  # noqa: BLE001
                exc.stage = "before_send"
                raise
            resp = await asyncio.wait_for(fut, timeout=max(0.5, timeout))
            self._track_sent(action, params, resp)
            return resp
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            if getattr(exc, "stage", None) is None:
                exc.stage = "after_send"
            raise
        finally:
            self._pending.pop(echo, None)

    @staticmethod
    def _target_of(params: dict) -> dict:
        if str(params.get("message_type")) == "group":
            return {"message_type": "group", "group_id": params.get("group_id")}
        return {"message_type": "private", "user_id": params.get("user_id")}

    async def _deliver(self, params: dict, *, ws=None, kind: str = "reply",
                       action: str = "send_msg") -> dict:
        if ws is not None:
            self._transport.ws = ws
        record = await self.delivery.send(kind=kind, target=self._target_of(params),
                                          params=params, action=action)
        if record.get("status") not in ("confirmed",):
            self.log(f"投递状态={record.get('status')} id={record.get('delivery_id')}"
                     f" err={record.get('error_type', '')}")
        return record

    # ---- remote dev channel (利贞 on harness) ----
    def _params(self, msg_type, user_id, ev) -> dict:
        if msg_type == "private":
            return {"message_type": "private", "user_id": int(user_id)}
        return {"message_type": "group",
                "group_id": int(ev.get("group_id", 0))}

    async def _say(self, ws, params: dict, text: str) -> None:
        for part in [text[i:i + 1400] for i in range(0, len(text), 1400)]:
            p = dict(params)
            p["message"] = part
            await self._deliver(p, ws=ws, kind="reply")

    @staticmethod
    def _file_uri(path: str) -> str:
        return "file:///" + str(pathlib.Path(path).resolve()).replace("\\", "/")

    async def _send_segment(self, ws, params: dict, seg: dict):
        p = dict(params)
        p["message"] = [seg]
        return await self._deliver(p, ws=ws, kind=str(seg.get("type") or "reply"))

    async def _send_voice(self, ws, params, text: str) -> bool:
        wav = await asyncio.to_thread(_tts_wav, text)
        silk = await asyncio.to_thread(_wav_to_silk, wav) if wav else ""
        if not silk:
            return False
        await self._send_segment(
            ws, params, {"type": "record", "data": {"file": self._file_uri(silk)}})
        return True

    def _file_allowed(self, path: str) -> bool:
        """元亨文件策略：能发/能转发非危险文件；危险文件（凭据/密钥）一律拒绝。"""
        try:
            from backend.target_access import is_dangerous_path

            if is_dangerous_path(path):
                self.log(f"拒绝发送危险文件: {pathlib.Path(str(path)).name}")
                return False
        except Exception:
            return False
        return True

    def _is_publishable(self, path: str) -> bool:
        """群聊放行判定：非危险 + 位于授权发布目录内。"""
        if not self._file_allowed(path):
            return False
        try:
            real = pathlib.Path(str(path)).resolve()
        except Exception:
            return False
        for base in PUBLISH_DIRS:
            try:
                if real.is_relative_to(pathlib.Path(base).resolve()):
                    return True
            except Exception:
                continue
        return False

    def _resolve_sticker(self, name: str, scope: str = "") -> str:
        """Lite: `[[sticker: <asset_id>]]` resolved through the DB, never by
        model-provided paths. Full keeps the legacy directory lookup."""
        name = str(name).strip().strip('"')
        if not name:
            return ""
        if _bridge_profile() != "full" or name.startswith("stk_"):
            if not name.startswith("stk_"):
                return ""
            try:
                store = self._stickers_db()
                if not store.can_send(name, scope):
                    return ""
                return store.resolve(name, scope)
            except Exception:
                return ""
        p = pathlib.Path(name)
        if p.is_absolute() and p.exists():
            return str(p)
        for ext in ("", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
            cand = STICKER_DIR / (name + ext)
            if cand.exists():
                return str(cand)
        return ""

    def _vision_judge(self):
        if getattr(self, "_vision", None) is None:
            from backend.qq_stickers import NullVision

            self._vision = NullVision()
        return self._vision

    def _sticker_hint_lite(self, channel: str, text: str) -> str:
        try:
            scope = self._scope_of(
                {"message_type": "group" if channel.startswith("qq_g")
                 else "private",
                 "group_id": channel[4:], "user_id": channel[4:]})
            cands = self._stickers_db().search(scope, text, limit=5)
        except Exception:
            return ""
        if not cands:
            return ""
        parts = []
        for c in cands:
            label = c.get("description") or "、".join(c.get("keywords") or [])
            parts.append(f"{c['asset_id']}({label[:40]})")
        return ("（可用表情包候选： " + "、".join(parts)
                + " ；最多发一个，想发就输出 [[sticker: <asset_id>]]）")

    def _sticker_hint(self, limit: int = 20) -> str:
        """告诉元亨有哪些表情包可用（目录为空则不产生任何内容）。"""
        try:
            names = sorted(
                p.stem for p in STICKER_DIR.glob("*")
                if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"))
        except Exception:
            names = []
        if not names:
            return ""
        return ("（可用表情包：" + "、".join(names[:limit])
                + "；想发就输出 [[sticker: 名]]）")

    async def _send_image(self, ws, params, path: str):
        if not self._file_allowed(path):
            return None
        return await self._send_segment(
            ws, params, {"type": "image", "data": {"file": self._file_uri(path)}})

    async def _send_file(self, ws, params, path: str) -> None:
        if not self._file_allowed(path):
            return
        await self._send_segment(ws, params, {
            "type": "file",
            "data": {"file": self._file_uri(path),
                     "name": pathlib.Path(path).name}})

    async def _send_forward(self, ws, params, nodes: list) -> dict:
        """能转发：以 OneBot 合并转发（node 列表）发送到当前私聊/群聊。"""
        if str(params.get("message_type")) == "group":
            action = "send_group_forward_msg"
            p = {"group_id": params.get("group_id"), "messages": nodes}
        else:
            action = "send_private_forward_msg"
            p = {"user_id": params.get("user_id"), "messages": nodes}
        return await self._deliver(p, ws=ws, kind="forward", action=action)

    async def _dev_report(self, ws, params, status, text, hint: bool = True) -> None:
        tag = {"awaiting": "❓ 需要你决定", "done": "✅ 完成",
               "error": "⚠️ 出错", "running": "⏳ 进行中",
               "info": "ℹ️"}.get(status, status)
        msg = f"[利贞] {tag}\n{text}"
        if status == "done" and hint:
            msg += "\n\n回 #y 提交 / #n 不提交 / #push 推送"
            if _bridge_profile() == "full" or os.getenv(
                    "YHLZ_QQ_DEV_MEMORY", "").strip().lower() in (
                    "1", "true", "yes", "on"):
                try:
                    # P3c: internalize dev experience with source='agent'
                    from backend.target_memory import TargetMemoryService
                    from backend.target_scheduler_tools import memory_save

                    memory_save(f"开发经验（利贞）：{str(text)[:80]}",
                                kind="event", importance=4,
                                service=TargetMemoryService(), source="agent")
                except Exception:
                    pass
        await self._say(ws, params, msg)

    def _spawn(self, ws, params, fn, hint: bool = True) -> None:
        """Run blocking fn() -> (status, text) in a thread, post back to QQ."""
        loop = self.loop

        def work() -> None:
            try:
                status, text = fn()
            except Exception as e:  # noqa: BLE001
                status, text = "error", f"{type(e).__name__}: {e}"
            if loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._dev_report(ws, params, status, text, hint), loop)

        threading.Thread(target=work, daemon=True).start()

    async def _start_dev(self, ws, params, task: str) -> None:
        """Kick off a harness dev task (ask-first flow) for the owner."""
        if dev_runner is None:
            await self._say(ws, params, "[利贞] 运行器不可用")
            return
        task = str(task).strip()
        if not task:
            return
        if self._dev_busy:
            await self._say(ws, params,
                            "[利贞] 已有开发任务在执行，请等当前任务结束或 #devstatus 查看。")
            return
        self._dev_busy = True
        await self._say(ws, params, f"[利贞] 已开工：{task[:80]}")

        def work() -> tuple:
            try:
                d = dev_runner.start(task)
                return d.get("status", "error"), d.get("text", "")
            finally:
                self._dev_busy = False

        self._spawn(ws, params, work)

    def _cmd_menu(self) -> str:
        """主人指令菜单（2026-10-09）：发 # 即出；Lite/Full 按能力裁剪。"""
        lite = _bridge_profile() != "full"
        lines = [
            f"【元亨指令菜单】（发 # 随时看；仅主人可用 · 当前档位："
            f"{MODE_LABELS[_wake_mode()]}）",
            "— 派单 / 开发 —",
            "#dev <任务>  派开发任务给利贞（同 #任务派发）",
            "#devstatus  当前任务状态",
        ]
        if lite:
            lines.append("#answer <job_id> <答复>  回复杂项任务提问")
            lines.append("#y 提交 / #n 不提交 / #push 推送 / #cancel 停止 / "
                         "#退出任务 退出任务模式")
        else:
            lines.append("#y|#commit 提交 / #n 不提交 / #push 推送")
        lines.append("#backend  查看利贞后端（固定 harness；opencode 已退役）")
        if lite:
            lines.append("— 群友档案 —")
            lines.append("#profiles [n] 档案列表 / #profile <qq> 单人档案")
        lines += [
            "— 消息 / 表达 —",
            "#voice on|off 语音回复开关 / #say <文字> 语音念一句",
            "#img <路径> 发图 / #file <路径> 发文件",
            "#face <id> 发QQ表情 / #fwd <内容> 合并转发",
            "— 对话档位（发送即切换）—",
            "#活泼  恢复默认：正常参与（@/名字/知识/主人）",
            "#内敛  群里仅 @/叫名字才回；私聊正常",
            "#缄默  彻底沉默（@ 也不回，私聊同步静默；# 指令仍可用）",
            "#档位  查看当前档位",
            "#解除  解除持续工作状态；其他 # 指令进入工作状态",
        ]
        return "\n".join(lines)

    async def _dev_cmd(self, ws, text, msg_type, user_id, ev) -> None:
        params = self._params(msg_type, user_id, ev)
        low = text.strip()

        def _pick(d: dict) -> tuple:
            return d.get("status", "error"), d.get("text", "")

        # 菜单（2026-10-09）：主人发 # 即出菜单，不用记指令。
        if low in ("#", "#help", "#帮助", "#菜单", "#?"):
            await self._say(ws, params, self._cmd_menu())
            return

        # ── 媒体/工具指令：只依赖桥自身，不依赖开发运行器 ──────────────
        if low in ("#voice", "#voice on", "#voice off"):
            st = _load_state()
            arg = low.replace("#voice", "").strip()
            st["voice"] = True if arg == "on" else (
                False if arg == "off" else not st.get("voice", False))
            _save_state(st)
            await self._say(ws, params,
                            f"[元亨] 语音回复已{'开' if st['voice'] else '关'}")
        elif low in ("#活泼", "#lively"):
            _set_wake_mode("lively")
            await self._say(ws, params,
                            "[元亨] 已切换到「活泼」：正常参与（默认档）。")
        elif low in ("#内敛", "#reserved"):
            _set_wake_mode("reserved")
            await self._say(ws, params,
                            "[元亨] 已切换到「内敛」：群里只有 @ 或叫名字才回；"
                            "私聊正常。")
        elif low in ("#缄默", "#silent", "#静默"):
            _set_wake_mode("silent")
            await self._say(ws, params,
                            "[元亨] 已切换到「缄默」：群里彻底沉默（@ 也不回），"
                            "私聊同步静默；发 # 仍可管理。")
        elif low in ("#档位", "#模式"):
            await self._say(ws, params,
                            f"[元亨] 当前档位：「{MODE_LABELS[_wake_mode()]}」")
        elif low.startswith("#say"):
            t = low[4:].strip()
            if t and await self._send_voice(ws, params, t):
                pass
            else:
                await self._say(ws, params, "[元亨] 语音合成失败")
        elif low.startswith("#img"):
            p_ = low[4:].strip().strip('"')
            if pathlib.Path(p_).exists():
                await self._send_image(ws, params, p_)
            else:
                await self._say(ws, params, f"[元亨] 找不到图片：{p_[:80]}")
        elif low.startswith("#file"):
            p_ = low[5:].strip().strip('"')
            if pathlib.Path(p_).exists():
                await self._send_file(ws, params, p_)
            else:
                await self._say(ws, params, f"[元亨] 找不到文件：{p_[:80]}")
        elif low.startswith("#face"):
            fid = low[5:].strip()
            if fid.isdigit():
                await self._send_segment(
                    ws, params, {"type": "face", "data": {"id": int(fid)}})
            else:
                await self._say(ws, params,
                                "[元亨] 用法：#face <id>（4=微笑 76=赞 14=难过 …）")
        elif low.startswith("#fwd"):
            t = low[4:].strip()
            if not t:
                await self._say(ws, params, "[元亨] 用法：#fwd <要合并转发的内容>")
            else:
                node = {"type": "node", "data": {
                    "name": "元亨", "uin": int(self.uin),
                    "content": [{"type": "text", "data": {"text": t}}]}}
                await self._send_forward(ws, params, [node])
        # ── 开发指令：需要开发运行器 ────────────────────────────────
        elif _bridge_profile() != "full":
            await self._dev_cmd_lite(ws, params, low, user_id)
        elif dev_runner is None:
            await self._say(ws, params, "[利贞] 运行器不可用")
        elif low in ("#devstatus", "#ds"):
            d = dev_runner._load()
            await self._say(ws, params,
                            f"[利贞] 状态={d.get('status')} "
                            f"任务={d.get('task','')[:60]}")
        elif low in ("#y", "#commit"):
            d = dev_runner._load()
            msg = ("chore(remote-dev): " + d.get("task", "")[:40]).strip()
            await self._say(ws, params, "[利贞] 正在提交…")
            self._spawn(ws, params,
                        lambda: ("info", dev_runner.commit(msg).get("text", "")),
                        hint=False)
        elif low == "#n":
            await self._say(ws, params, "[利贞] 好的，不提交，改动留在工作区。")
        elif low == "#push":
            self._spawn(ws, params,
                        lambda: ("info", dev_runner.push().get("text") or "已推送"),
                        hint=False)
        elif low in ("#backend", "#be") or low.startswith(("#backend ", "#be ")):
            arg = low
            for pfx in ("#backend", "#be"):
                if arg.startswith(pfx):
                    arg = arg[len(pfx):].strip()
                    break
            if arg:
                await self._say(ws, params, dev_runner.set_backend(arg))
            else:
                await self._say(ws, params, dev_runner.backend_status())
        elif low == "#dev" or low.startswith("#dev "):
            task = low[4:].strip()
            if not task:
                await self._say(ws, params, "用法：#dev <任务>")
                return
            await self._start_dev(ws, params, task)
        else:
            await self._say(ws, params,
                            f"未知指令：{low[:24]}\n（发 # 看菜单）")

    async def _dev_cmd_lite(self, ws, params, low: str, user_id: str) -> None:
        """Lite dev commands: persistent job store, scope commits (P3)."""
        from backend.qq_behavior import dev_exit_command

        mod = _dev_mod()
        if mod is None:
            await self._say(ws, params, "[利贞] 运行器不可用")
            return
        channel = (f"qq_p{user_id}"
                   if str(params.get("message_type")) == "private"
                   else f"qq_g{params.get('group_id', user_id)}")

        async def _result(fn, *args, **kwargs) -> None:
            try:
                r = await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                await self._say(ws, params,
                                f"[利贞] 运行器异常：{type(exc).__name__}")
                return
            await self._say(ws, params, str(r.get("text") or r.get("status") or ""))

        if low in ("#devstatus", "#ds"):
            text = await asyncio.to_thread(mod.status_text)
            await self._say(ws, params, text)
        elif low in ("#任务", "#任务栏"):
            await self._say(ws, params,
                            "【任务栏】\n"
                            "#任务派发 <任务>（=#dev）发起开发任务\n"
                            "#devstatus 状态 / 直接回复=答复\n"
                            "#y [job] 提交 / #n 不提交 / #push [job] 推送\n"
                            "#cancel [job] 停止执行 / #退出任务 [job] 退出任务模式\n"
                            "#answer <job_id> <答复> 跨会话答复")
        elif low == "#任务派发" or low.startswith("#任务派发 "):
            task = low[len("#任务派发"):].strip()
            if not task:
                await self._say(ws, params, "用法：#任务派发 <任务>")
                return
            await _result(mod.start, task, owner=user_id, channel=channel)
        elif dev_exit_command(low):
            arg = low.split(None, 1)[1].strip() if " " in low else ""
            await _result(mod.detach, arg or None)
        elif low == "#dev" or low.startswith("#dev "):
            task = low[4:].strip()
            if not task:
                await self._say(ws, params, "用法：#dev <任务>")
                return
            await _result(mod.start, task, owner=user_id, channel=channel)
        elif low in ("#y", "#commit") or low.startswith(("#y ", "#commit ")):
            arg = low.split(None, 1)[1].strip() if " " in low else ""
            await _result(mod.commit, arg or None)
        elif low == "#n":
            await self._say(ws, params, "[利贞] 好的，不提交；工作树改动保留。")
        elif low == "#push" or low.startswith("#push "):
            await _result(mod.push, low[5:].strip() or None)
        elif low in ("#cancel", "#cancle", "#取消", "#取消任务") or low.startswith(
                ("#cancel ", "#cancle ", "#取消 ", "#取消任务 ")):
            arg = low.split(None, 1)[1].strip() if " " in low else ""
            await _result(mod.cancel, arg or None)
        elif low == "#answer" or low.startswith("#answer "):
            rest = low[7:].strip()
            job_id, _, ans = rest.partition(" ")
            if not job_id or not ans.strip():
                await self._say(ws, params, "用法：#answer <job_id> <答复>")
                return
            await _result(mod.answer, ans.strip(), owner=user_id,
                          channel=channel, job_id=job_id)
        elif low in ("#profiles", "#profile") or low.startswith(
                ("#profiles ", "#profile ")):
            from backend.qq_profiles import MemberProfileStore

            if low.startswith("#profile "):
                qq = low[9:].strip()
                if not qq.isdigit():
                    await self._say(ws, params, "用法：#profile <qq号>")
                else:
                    prof = await asyncio.to_thread(self._profiles_db().get, qq)
                    if not prof:
                        await self._say(ws, params,
                                        f"还没有 {qq} 的档案（需先在群里发过言）")
                    else:
                        await self._say(ws, params,
                                        MemberProfileStore.profile_text(prof))
            else:
                rest = low[9:].strip()
                n = int(rest) if rest.isdigit() else 20
                text = await asyncio.to_thread(self._profiles_db().list_text,
                                               min(max(n, 1), 50))
                await self._say(ws, params, text)
        elif low in ("#backend", "#be") or low.startswith(("#backend ", "#be ")):
            arg = low
            for pfx in ("#backend", "#be"):
                if arg.startswith(pfx):
                    arg = arg[len(pfx):].strip()
                    break
            if arg:
                await self._say(ws, params, mod.set_backend(arg))
            else:
                await self._say(ws, params, mod.backend_status())
        else:
            # 0830：未知 # 指令只提示，绝不再兜底派单。
            # 旧兜底把「#cancle」「#backed」这类拼错、以及
            # 「#退出任务，这不是任务指令」整句都当成任务派出去。
            await self._say(ws, params,
                            f"未知指令：{low[:24]}\n"
                            "发 # 看菜单；要派单请用 #dev <任务>")

    async def _profile_updater(self) -> None:
        """Periodically rebuild member profiles from group history (Lite)."""
        if _bridge_profile() == "full":
            return
        interval = float(os.getenv("YHLZ_QQ_PROFILE_REFRESH", "600"))
        min_msgs = int(os.getenv("YHLZ_QQ_PROFILE_MIN_MSGS", "1"))
        await asyncio.sleep(min(30.0, max(5.0, interval / 10)))
        while True:
            try:
                updated = await asyncio.to_thread(self._rebuild_profiles,
                                                  min_msgs)
                if updated:
                    self.log(f"群友档案已更新 {updated} 人")
            except Exception as exc:  # noqa: BLE001
                self.log(f"档案更新失败 {type(exc).__name__}")
            await asyncio.sleep(max(60.0, interval))

    async def _relay_dev_jobs(self, ws) -> None:
        """Relay new job results from the Lite runner to the owner private."""
        if _bridge_profile() == "full":
            return
        mod = _dev_mod()
        if mod is None:
            return
        while True:
            await asyncio.sleep(3)
            try:
                updates = await asyncio.to_thread(mod.pending_reports)
            except Exception:
                continue
            for job in updates:
                try:
                    status, text = mod.report_text(job)
                except Exception:
                    continue
                owner = str(job.get("owner_id") or "")
                if not owner.isdigit():
                    continue
                params = {"message_type": "private", "user_id": int(owner)}
                try:
                    await self._dev_report(ws, params, status, text,
                                           hint=(status == "done"))
                except Exception:
                    pass

    async def _resolve_image(self, seg) -> str:
        d = seg.get("data") or {}
        url = str(d.get("url") or "")
        if url.startswith("http"):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"})
                return _save_media(urllib.request.urlopen(req, timeout=20).read(),
                                   "jpg", IMG_MAX_BYTES)
            except Exception:
                pass
        file = str(d.get("file") or d.get("file_id") or "")
        if not file:
            return ""
        ev = await _napcat_call(self.ws_url, "get_image", {"file": file})
        r = (ev or {}).get("data") or {}
        p = str(r.get("file") or "")
        try:
            if p and pathlib.Path(p).exists():
                src = pathlib.Path(p)
                return _save_media(src.read_bytes(),
                                   src.suffix.lstrip(".") or "jpg", IMG_MAX_BYTES)
        except Exception:
            pass
        u = str(r.get("url") or "")
        if u.startswith("http"):
            try:
                return _save_media(urllib.request.urlopen(
                    urllib.request.Request(
                        u, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=20).read(), "jpg", IMG_MAX_BYTES)
            except Exception:
                pass
        self.log(f"取图失败 file={file[:40]}")
        return ""

    async def _collect_images(self, msg) -> list:
        out = []
        for seg in msg or []:
            if seg.get("type") == "image":
                p = await self._resolve_image(seg)
                if p:
                    out.append(p)
        if out:
            _cleanup_media()
        return out

    async def _resolve_record(self, seg) -> str:
        d = seg.get("data") or {}
        file = str(d.get("file") or "")
        ev = await _napcat_call(self.ws_url, "get_record",
                                {"file": file, "out_format": "wav"})
        r = (ev or {}).get("data") or {}
        p = str(r.get("file") or "")
        try:
            if p and pathlib.Path(p).exists():
                src = pathlib.Path(p)
                saved = _save_media(src.read_bytes(),
                                    src.suffix.lstrip(".") or "wav",
                                    AUDIO_MAX_BYTES)
                self.log(f"语音已存 {saved}")
                return saved
        except Exception as e:  # noqa: BLE001
            self.log(f"语音存盘异常 {type(e).__name__}: {e}")
        b64 = str(r.get("base64") or "")
        if b64:
            import base64 as _b64

            saved = _save_media(_b64.b64decode(b64), "wav", AUDIO_MAX_BYTES)
            self.log(f"语音已存(base64) {saved}")
            return saved
        u = str(r.get("url") or d.get("url") or "")
        if u.startswith("http"):
            try:
                saved = _save_media(urllib.request.urlopen(
                    urllib.request.Request(
                        u, headers={"User-Agent": "Mozilla/5.0"}),
                    timeout=20).read(), "wav", AUDIO_MAX_BYTES)
                self.log(f"语音已存(url) {saved}")
                return saved
            except Exception:
                pass
        self.log(f"取语音失败 file={file[:40]} data={str(r)[:120]}")
        return ""

    def _voice_text(self, path: str) -> str:
        try:
            audio = _decode_to_pcm16k(path)
            if len(audio) / 16000.0 > AUDIO_MAX_SECONDS:
                self.log(f"语音过长({len(audio)/16000:.0f}s) 跳过")
                return ""
            return _transcribe_audio(audio)
        except Exception as e:  # noqa: BLE001
            self.log(f"语音识别失败 {type(e).__name__}: {e}")
            return ""

    def _wake_reason(self, text: str, addressed: bool, user_id: str,
                     msg=None, group_id: str = "") -> str:
        """群唤醒闸门（2026-10-08）：@ / 名字 / 引用回复 / 已知信息 / 主人。

        2026-10-10：at_only 群（YHLZ_QQ_WAKE_AT_ONLY_GROUPS）只在 @ 时唤醒，
        其余情况一律保持安静（含主人未 @）。
        返回命中原因（"off" = 闸门关闭、按传统全量处理）；空串 = 保持安静，
        消息只入库供上下文与档案，不读上下文、不进模型。
        """
        if not _wake_gate_enabled():
            return "off"
        mode = _wake_mode()
        if mode == "silent":
            # 缄默（2026-10-11）：群里彻底沉默（含 @）；# 指令不走此路径。
            return ""
        if addressed:
            return "at"
        if str(group_id or "") in _wake_at_only_groups():
            return ""
        body = str(text or "")
        if mode == "reserved":
            # 内敛（2026-10-11）：群里只有 @ 或叫名字才回，其余触发全停。
            for name in _wake_names():
                if name and name in body:
                    return "name"
            return ""
        if _wake_master_always() and user_id in self.masters:
            return "master"
        for name in _wake_names():
            if name and name in body:
                return "name"
        if self._reply_to_bot(msg):
            return "reply"
        if _wake_topics_enabled():
            try:
                from backend import yuanheng_kb

                hit = yuanheng_kb.kb_wake_hit(
                    body, min_chars=_wake_topic_min_chars())
            except Exception:  # noqa: BLE001
                hit = None
            if hit:
                return "topic"
        if _wake_memory_enabled():
            try:
                from backend import target_memory

                hit = target_memory.memory_wake_hit(body)
            except Exception:  # noqa: BLE001
                hit = None
            if hit:
                return "topic"
        return ""

    def _reply_to_bot(self, msg) -> bool:
        """有人引用/回复了元亨自己发出的群消息（无 @ 无名字也算唤醒）。"""
        for seg in msg or []:
            if not isinstance(seg, dict) or seg.get("type") != "reply":
                continue
            data = seg.get("data") or {}
            rid = str(data.get("id") or "").strip()
            if rid and rid in self._sent_msg_ids:
                return True
        return False

    def _track_sent(self, action: str, params: dict, result) -> None:
        """记录本桥成功发出的群消息 ID（供“引用回复她”唤醒判定）。"""
        try:
            if action != "send_msg" or not isinstance(result, dict):
                return
            if str(params.get("message_type")) != "group":
                return
            if str(result.get("status")) != "ok":
                return
            data = result.get("data") if isinstance(result.get("data"), dict) \
                else {}
            mid = str(data.get("message_id") or "").strip()
            if not mid:
                return
            self._sent_msg_ids[mid] = time.time()
            while len(self._sent_msg_ids) > SENT_MSG_ID_LIMIT:
                self._sent_msg_ids.popitem(last=False)
        except Exception:  # noqa: BLE001
            pass

    def _rate_limited(self, channel: str, user_id: str) -> bool:
        """Anti-spam: per-user cooldown + per-channel gap + per-minute budget.

        Lite defaults are deliberately quiet (2026-10-06「减少对话频率」);
        the owner (masters) is never rate limited.
        """
        if user_id in self.masters:
            return False
        now = time.time()
        is_group = channel.startswith("qq_g")
        cooldown = GROUP_USER_COOLDOWN if is_group else PRIVATE_USER_COOLDOWN
        if now - self._last_reply.get(user_id, 0.0) < cooldown:
            return True
        if is_group and GROUP_CHAN_GAP > 0:
            if now - self._last_chan_reply.get(channel, 0.0) < GROUP_CHAN_GAP:
                return True
        times = self._chan_reply.setdefault(channel, [])
        times[:] = [t for t in times if now - t < 60.0]
        if len(times) >= GROUP_CHAN_PER_MIN:
            return True
        self._last_reply[user_id] = now
        self._last_chan_reply[channel] = now
        times.append(now)
        return False

    def _claim_message(self, ev: dict, channel: str) -> bool:
        """Bounded replay protection, not a durable exactly-once guarantee."""
        mid = ev.get("message_id")
        if mid is None or str(mid) == "":
            return True  # legacy events without IDs cannot be deduplicated
        now = time.monotonic()
        while self._seen_events:
            first, ts = next(iter(self._seen_events.items()))
            if now - ts < MESSAGE_DEDUP_TTL:
                break
            self._seen_events.pop(first)
        key = (self.uin, channel, str(ev.get("user_id", "")), str(mid))
        if key in self._seen_events:
            self.duplicate_events += 1
            return False
        self._seen_events[key] = now
        while len(self._seen_events) > MESSAGE_DEDUP_LIMIT:
            self._seen_events.popitem(last=False)
        return True

    def _main_social(self):
        if self._social_store is None:
            from backend.qq_main_memory import QqMainMemory
            state = os.getenv("YHLZ_QQ_STATE_DIR", "").strip()
            canonical = _PROJECT / "cache" / "qq_bridge" / "lite"
            db = os.getenv("YHLZ_QQ_MEMORY_DB", "").strip() or None
            if db is None and state and pathlib.Path(state).resolve() != canonical.resolve():
                db = pathlib.Path(state) / "main_social.db"
            self._social_store = QqMainMemory(db)
        return self._social_store

    def _work_enabled(self, user_id: str) -> bool:
        from backend.qq_behavior import work_enabled
        return work_enabled(_load_state(), user_id)

    def _set_work(self, user_id: str, enabled: bool, channel: str) -> None:
        from backend.qq_behavior import set_work
        _save_state(set_work(_load_state(), user_id, enabled, channel))

    async def handle(self, ws, ev: dict) -> None:
        if ev.get("post_type") != "message":
            return
        msg_type = ev.get("message_type")
        user_id = str(ev.get("user_id", ""))
        if not user_id.isdigit():
            return
        msg = ev.get("message", [])
        if not isinstance(msg, list):
            return
        msg = [s for s in msg if isinstance(s, dict)
               and isinstance(s.get("data", {}), dict)]
        text, ats = self._text_of(msg)
        addressed = self.uin in {str(x) for x in ats}
        if user_id == self.uin:
            # 机器人自回显：仅用于群上下文，不触发再次回复（2026-10-06）。
            if msg_type == "group" and _bridge_profile() != "full" and text:
                try:
                    gid = str(ev.get("group_id", ""))
                    if gid.isdigit():
                        self._group_db().add(
                            group_id=gid, is_bot=True, sender_id=user_id,
                            message_id=str(ev.get("message_id")
                                           or uuid.uuid4().hex), text=text)
                except Exception:
                    pass
            return
        cmd = text.strip().replace("＃", "#")
        is_master_cmd = user_id in self.masters and cmd.startswith("#")
        # 2026-10-06 规则修订：只有主人（2258374446）的外层真实指令是命令；
        # 其他人的文本（含 # 开头）一律按普通聊天处理，不再返回安全接管话术。
        if msg_type == "private":
            channel = f"qq_p{user_id}"
        elif msg_type == "group":
            if not str(ev.get("group_id", "")).isdigit():
                return
            allowed = _allowed_groups()
            if allowed is not None and str(ev.get("group_id")) not in allowed:
                return  # 群白名单（2026-10-08）：不在名单内的群完全不读不存
            # 无 @ 接话（2026-09-30）：元亨作为群成员直接参与对话。
            channel = f"qq_g{ev.get('group_id', user_id)}"
        else:
            return
        from backend.qq_behavior import (command_not_for_bot, dev_exit_command,
                                         dev_lane_command, RELEASE,
                                         work_released)
        if not self._claim_message(ev, channel):
            return
        # P4: 群消息入库在回复/频控/LLM 之前（即使不接话也能形成上下文）。
        before_seq = None
        if msg_type == "group" and _bridge_profile() != "full" \
                and str(ev.get("group_id", "")).isdigit():
            try:
                sender = ev.get("sender") if isinstance(ev.get("sender"), dict) \
                    else {}
                before_seq = self._group_db().add(
                    group_id=str(ev.get("group_id")),
                    message_id=str(ev.get("message_id") or uuid.uuid4().hex),
                    sender_id=user_id,
                    sender_name=str(sender.get("nickname") or ""),
                    text=text, media=self._media_placeholders(msg))
                if not before_seq:
                    before_seq = None
            except Exception:
                before_seq = None
        if msg_type == "group" and _bridge_profile() != "full":
            try:
                await asyncio.to_thread(self._main_social().observe, ev, self.uin)
            except Exception:
                pass
        if msg_type == "group" and command_not_for_bot(
                text, ats, self.uin, _wake_names(), owner_command=is_master_cmd,
                owner_work=user_id in self.masters and self._work_enabled(user_id)):
            return  # observed for social context, but not directed at Yuanheng
        # remote dev channel (master only): #dev / #y / #n / #push / #devstatus
        if is_master_cmd:
            if cmd in RELEASE:
                self._set_work(user_id, False, channel)
                await self._say(ws, self._params(msg_type, user_id, ev),
                                "[元亨] 已解除工作状态，恢复正常对话。")
                return
            # 0830：退出任务 = 离开任务模式，必须同时清掉工作状态。旧逻辑
            # 只让 #解除 清状态，于是 #退出任务 之后每条普通聊天都被
            # `#dev + text` 二次派单。
            exit_task = dev_exit_command(cmd)
            if not exit_task and dev_lane_command(cmd):
                self._set_work(user_id, True, channel)
            self.log(f"指令 {user_id}: {cmd[:50]}")
            await self._dev_cmd(ws, cmd, msg_type, user_id, ev)
            if exit_task:
                self._set_work(user_id, False, channel)
            return
        # 0830：答复路由仍尊重「已明确解除/退出任务」的标记（work_released），
        # 但该标记现在会由 #退出任务 / #解除 真正清掉——旧逻辑只在 #解除 清，
        # 退出任务后仍把聊天当任务通道。
        if (user_id in self.masters and _bridge_profile() != "full"
                and not work_released(_load_state(), user_id)):
            mod = _dev_mod()
            if mod is not None:
                try:
                    job = await asyncio.to_thread(mod.awaiting_job, user_id,
                                                  channel)
                except Exception:
                    job = None
                if job:
                    params = self._params(msg_type, user_id, ev)
                    self.log(f"答复 利贞 {user_id}: {text[:50]}")
                    await self._say(ws, params, "[利贞] 收到答复，继续…")
                    try:
                        r = await asyncio.to_thread(
                            mod.answer, text, owner=user_id, channel=channel,
                            job_id=job["job_id"])
                        if str(r.get("status")) == "error":
                            await self._say(ws, params,
                                            str(r.get("text") or "答复失败"))
                    except Exception as exc:  # noqa: BLE001
                        await self._say(ws, params,
                                        f"[利贞] 答复失败：{type(exc).__name__}")
                    return
        if dev_runner is not None and _bridge_profile() == "full" \
                and user_id in self.masters and not work_released(_load_state(), user_id):
            try:
                if dev_runner._load().get("status") == "awaiting":
                    params = self._params(msg_type, user_id, ev)
                    self.log(f"答复 利贞 {user_id}: {text[:50]}")
                    await self._say(ws, params, "[利贞] 收到答复，继续…")
                    self._spawn(ws, params, lambda: (
                        (lambda d: (d.get("status", "error"),
                                    d.get("text", "")))(dev_runner.answer(text))))
                    return
            except Exception as e:  # noqa: BLE001
                self.log(f"dev 答复路由异常 {type(e).__name__}: {e}")
        # 0830：普通聊天绝不再自动派单。旧逻辑在 owner_work=True 时把每条
        # 普通消息拼成 `#dev <原文>` 发出去，于是「哦好了」「差点」
        # 「你现在怎么样」全变成开发任务；退出任务后还在继续派。
        # 派单只走显式指令：#dev / #任务派发。
        if msg_type == "group" and any(self._work_enabled(owner) for owner in self.masters):
            return  # incoming history is preserved while the owner is working
        if msg_type != "group" and _wake_mode() == "silent":
            # 缄默（2026-10-11）：私聊也静默；# 指令与系统通知不受影响。
            self.log(f"缄默跳过（私聊） {user_id}")
            return
        imgs = (await self._collect_images(msg)
                if any(s.get("type") == "image" for s in msg) else [])
        if any(s.get("type") == "record" for s in msg):
            if _voice_mode() == "text_only":
                # 群聊里只在被唤醒时提示“听不了语音”，避免对每条语音都回话。
                if msg_type == "private" or self._wake_reason(
                        text, addressed, user_id, msg,
                        str(ev.get("group_id") or "")):
                    await self._say(ws, self._params(msg_type, user_id, ev),
                                    "[元亨] 我现在听不了语音，请发文字。")
            else:
                heard = []
                for s in msg:
                    if s.get("type") == "record":
                        p = await self._resolve_record(s)
                        if p:
                            t = await asyncio.to_thread(self._voice_text, p)
                            if t:
                                heard.append(t)
                if heard:
                    text = (text + " " + " ".join(
                        f"（语音）{h}" for h in heard)).strip()
                    _cleanup_media()
        if not text and not imgs:
            # A direct group mention is a complete request for attention.
            # Preserve voice handling and all later wake/silence/rate gates.
            if (msg_type == "group" and addressed
                    and all(s.get("type") in ("at", "text", "reply") for s in msg)):
                text = "（对方在群里 @ 了你，未附文字）"
            else:
                return
        if imgs and _bridge_profile() != "full":
            for p in imgs[:4]:
                try:
                    info = self._stickers_db().ingest(
                        p, source_message_id=str(ev.get("message_id") or ""),
                        source_kind=str(msg_type),
                        source_id=str(ev.get("group_id") or user_id),
                        scope=self._scope_of(
                            self._params(msg_type, user_id, ev)))
                    judge = self._vision_judge()
                    if info.get("status") == "new" and getattr(
                            judge, "available", False):
                        raw = await asyncio.to_thread(judge.judge, p)
                        self._stickers_db().recognize(
                            info["asset_id"], raw,
                            model_version=getattr(judge, "name", "unknown"))
                except Exception:
                    pass
        group_ctx = ""
        allowed_msg_ids: set[str] = set()
        allowed_qqs: set[str] = set()
        wake_reason = ""
        if msg_type == "group":
            allowed_msg_ids.add(str(ev.get("message_id") or ""))
            allowed_qqs.add(user_id)
            wake_reason = self._wake_reason(
                text, addressed, user_id, msg, str(ev.get("group_id") or ""))
            if not wake_reason:
                # 唤醒闸门（2026-10-08）：不叫不接；消息已入库供上下文/档案。
                self.log(f"未唤醒跳过 {user_id} @ {channel}")
                return
            if not self._group_daily_ok():
                self.log(f"群日限额已满（{GROUP_DAILY_LIMIT}），跳过 {channel}")
                return
        if _bridge_profile() != "full":
            ok = await asyncio.to_thread(self._daemon_ok)
            if not ok:
                key = f"{channel}:{user_id}"
                now = time.time()
                if now - self._degrade_sent.get(key, 0.0) > 300.0:
                    self._degrade_sent[key] = now
                    await self._say(ws, self._params(msg_type, user_id, ev),
                                    "元亨的聊天后端暂时不可用；主人可以先用 #dev 安排任务。")
                return
        if self._rate_limited(channel, user_id):
            self.log(f"频控跳过 {user_id} @ {channel}")
            return
        self.log(f"来自 {user_id}: {text[:40]}"
                 + (f" [+{len(imgs)}图]" if imgs else ""))
        if msg_type == "group":
            # 上下文只在真正参与的这一轮读一次（2026-10-08 唤醒闸门）。
            if _bridge_profile() == "full":
                group_ctx = self._group_context(channel)
                self._note_group_history(channel, user_id, text)
            else:
                try:
                    block = self._group_db().context_block(
                        str(ev.get("group_id")), before_seq=before_seq)
                    # 2026-10-13（ledger 0816）：只注入**摘要**，不再追加"最近原话"。
                    # 旧做法每轮把最近 8 条原文重新灌一遍，于是同一批话在会话里反复
                    # 出现——就是老爹说的"重复读取上下文"（会话被撑大、她反复重读、
                    # 还容易把别人的话当成对她说的）。摘要本身已带来源 ID 与发言人。
                    group_ctx = block["summary"]
                    if block["completeness"] != "full":
                        group_ctx += f"\n[completeness={block['completeness']}]"
                    allowed_msg_ids |= {str(x) for x in block["source_ids"]}
                    allowed_qqs |= {str(x) for x in block["senders"]}
                except Exception:
                    group_ctx = ""
        # urllib's request may take minutes; never block WS heartbeat/outbox.
        # Speaker attribution stays inside the isolated group conversation.
        if msg_type == "group":
            ctx_block = (f"[群聊最近记录（仅供理解，不要逐条回应）]\n{group_ctx}\n"
                         if group_ctx else "")
            turn_text = f"{ctx_block}[QQ群发言者 user_id={user_id}] {text}"
            if _bridge_profile() != "full" and (allowed_qqs or allowed_msg_ids):
                turn_text += ("\n（如需呼叫某位群友可写 [[at: QQ号]]；"
                              "如需引用某条消息可写 [[reply: 消息ID]]；"
                              "两者必须来自上面的上下文，最多 @3 人）")
                if addressed and str(ev.get("message_id") or ""):
                    turn_text += (f"\n（对方这条 @ 了你；如合适可用 "
                                  f"[[at: {user_id}]] 回叫 TA，或用 "
                                  f"[[reply: {ev.get('message_id')}]] "
                                  f"引用 TA 这条消息）")
            if _silence_enabled() and wake_reason in ("topic", "name"):
                turn_text += ("\n（如果你判断这条不是对你说的、或接不上——"
                              "只输出 [[silence]]，不要硬答；能自然接一句就正常回。）")
            if _bridge_profile() != "full" and _profile_inject_enabled():
                # 群友档案卡（2026-10-09）：让她认人（身份/QQ/风格/爱好）。
                try:
                    _card = await asyncio.to_thread(
                        self._profiles_db().brief, user_id)
                except Exception:  # noqa: BLE001
                    _card = ""
                if _card:
                    turn_text += (f"\n【当前发言人档案】{_card}"
                                  "（供你认人用，不要原文复述）")
        else:
            turn_text = text
        if imgs:
            # 2026-10-13（ledger 0816）：图片只在本轮可见。把"确实收到过图"写进
            # 会话文本，后续轮次她看到自己的历史就知道当时有图，不会改口说
            # "你没发过/我没收到"——那正是老爹说的"精分"（前后自相矛盾）。
            turn_text += (f"\n[本轮收到图片 {len(imgs)} 张（仅本轮可见；"
                          "以后的轮次看不到它是正常的）]")
        sticker_hint = (self._sticker_hint_lite(channel, text)
                        if _bridge_profile() != "full" else self._sticker_hint())
        if sticker_hint:
            turn_text = f"{turn_text}\n{sticker_hint}"
        try:
            turn_out = await asyncio.to_thread(_daemon_turn, turn_text, channel,
                                               images=imgs)
        except Exception as exc:
            self.backend_errors += 1
            self.log(f"对话请求失败: {type(exc).__name__}，不自动重放")
            if msg_type == "private":
                await self._say(ws, self._params(msg_type, user_id, ev),
                                "这次请求没有完成，请稍后重新发送；我没有自动重复执行。")
            return
        # Compat: legacy/mocked transports may still hand back a plain string.
        if isinstance(turn_out, dict):
            ans = str(turn_out.get("answer") or "")
            out_attach = [str(x) for x in (turn_out.get("attachments") or [])
                          if str(x).strip()][:4]
        else:
            ans = str(turn_out or "")
            out_attach = []
        if not ans and not out_attach:
            return
        # 沉默出口（2026-10-09 收紧）：只有"知识/记忆命中、随口提到名字"被唤醒的
        # 群消息可沉默；@/引用/主人必须回——未被允许的沉默标记直接吞掉，不泄漏字面。
        if _SILENCE_RE.fullmatch(ans.strip()):
            if msg_type == "group" and _silence_enabled() \
                    and wake_reason in ("topic", "name"):
                self.log(f"选择沉默 {user_id} @ {channel}")
                return
            self.log(f"沉默标记被忽略 {user_id} @ {channel}")
            return
        if "[[" in ans and "silence" in ans.lower():
            ans = _SILENCE_RE.sub("", ans).strip()
            if not ans and not out_attach:
                return
        # Defense in depth for old/custom daemon responses. Pure-text generated
        # dev markers are not owner authorization. Keep record/audio route frozen.
        if not any(segment.get("type") == "record" for segment in msg):
            from backend.target_dev_bridge import guard_text_dev_handoff

            ans, _dev_status = guard_text_dev_handoff(
                ans, is_owner=msg_type == "private" and user_id in self.masters)
        if msg_type == "group":
            if _bridge_profile() == "full":
                self._note_group_history(channel, self.uin, ans)
            else:
                try:
                    self._group_db().add(
                        group_id=str(ev.get("group_id")), sender_id=self.uin,
                        message_id="bot:" + uuid.uuid4().hex, text=ans,
                        is_bot=True)
                except Exception:
                    pass
        (ans, out_imgs, out_files, out_faces, vmark, out_devs, out_mfaces,
         out_stickers, out_ats, out_replies) = _extract_markers(ans.strip())
        self.log(f"回复 {user_id}: {ans[:50]}")
        params = {"message": ans}
        if msg_type == "private":
            params.update(message_type="private", user_id=int(user_id))
        else:
            params.update(message_type="group",
                          group_id=int(ev.get("group_id", 0)))
        # @ 与引用：只允许上下文中真实出现过的人/消息（防幻觉）。
        prefix_segments: list[dict] = []
        if msg_type == "group":
            quote = str(out_replies[0]) if out_replies else ""
            if quote and quote in allowed_msg_ids:
                prefix_segments.append({"type": "reply",
                                        "data": {"id": quote}})
            for qq in out_ats[:3]:
                if str(qq) in allowed_qqs:
                    prefix_segments.append({"type": "at",
                                            "data": {"qq": str(qq)}})
            if prefix_segments:
                kinds = ",".join(seg["type"] for seg in prefix_segments)
                self.log(f"回复附带 {kinds}")
        # Yuanheng handed a real dev task to 利贞 on harness (owner only)
        if out_devs and msg_type == "private" and user_id in self.masters:
            await self._start_dev(ws, params, out_devs[0])
        for fid in out_faces:
            await self._send_segment(
                ws, params, {"type": "face", "data": {"id": int(fid)}})
        for mid in out_mfaces:
            await self._send_segment(
                ws, params, {"type": "mface", "data": {"emoji_id": str(mid)}})
        scope = self._scope_of(params)
        sent_sticker = False
        for name in out_stickers:
            if sent_sticker:
                break
            sp = self._resolve_sticker(name, scope)
            if sp:
                record = await self._send_image(ws, params, sp)
                sent_sticker = True
                try:
                    status = str((record or {}).get("status") or "unknown")
                    self._stickers_db().record_use(
                        str(name).strip().strip('"'), scope, status=status)
                except Exception:
                    pass
        # 完整发图（2026-09-30）：群/私聊都可发非危险图/文件；危险文件由
        # _send_image/_send_file 内部 `_file_allowed` 拒绝。
        for ip in out_imgs:
            if pathlib.Path(ip).exists():
                await self._send_image(ws, params, ip)
        for fp in out_files:
            if pathlib.Path(fp).exists():
                await self._send_file(ws, params, fp)
        # file.share 附件（2026-10-06）：daemon 校验后回传的本地路径，按类型发送。
        for ap in out_attach:
            apath = pathlib.Path(ap)
            if not apath.exists():
                self.log(f"分享附件不存在: {apath.name}")
                continue
            try:
                from backend.target_access import is_image_path
                _img = is_image_path(ap)
            except Exception:
                _img = apath.suffix.lower() in {
                    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico"}
            if _img:
                await self._send_image(ws, params, ap)
            else:
                await self._send_file(ws, params, ap)
            self.log(f"分享已发: {apath.name}")
        if not ans:
            return
        want_voice = (vmark or _load_state().get("voice", False)
                      or _voice_intent(text))
        if want_voice and await self._send_voice(ws, params, ans):
            return
        for part in [ans[i:i + 1400] for i in range(0, len(ans), 1400)]:
            if prefix_segments:
                params["message"] = list(prefix_segments) + [
                    {"type": "text", "data": {"text": part}}]
                prefix_segments = []   # 只在第一条带上 @/引用
            else:
                params["message"] = part
            await self._deliver(params, ws=ws, kind="reply")

    async def _relay_outbox(self, ws) -> None:
        """Relay queued messages through the live socket without destructive drain.

        ``peek`` keeps the item on disk until OneBot returns ``status=ok``.
        This fixes the old loss window where a disconnect or the third item in
        a batch was removed before it had actually been sent.
        """
        if not self.masters:
            return
        sent: list[float] = []
        master = int(next(iter(self.masters)))
        while True:
            await asyncio.sleep(30)
            now = time.time()
            sent[:] = [t for t in sent if now - t < 3600]
            if len(sent) >= 2:
                continue
            try:
                from backend import qq_outbox
                items = qq_outbox.peek(min(2, 2 - len(sent)))
            except Exception:
                items = []
            for it in items:
                text = str(it.get("text", "")).strip()
                if not text:
                    continue
                # T3 真实入口（0630）：经统一适配器 + 持久投递（unknown 不盲重发）
                outcome = "unknown"
                try:
                    from backend import qq_delivery_store as _ds
                    from backend import qq_send_adapter as _ad

                    _con = _ds.connect(_ds.DEFAULT_DB)
                    try:
                        async def _transport(action, params):
                            return await self._request(ws, action, params, timeout=15)

                        _r = await _ad.send(
                            _con,
                            source_event_id="outbox:" + str(
                                it.get("id") or it.get("ts") or text[:24]),
                            channel="qq_outbox", target_type="private",
                            target_id=str(master), kind=str(it.get("kind") or "proactive"),
                            action="send_msg",
                            params={"message_type": "private", "user_id": master,
                                    "message": text},
                            transport=_transport, owner="outbox")
                        outcome = str(_r.get("state") or "unknown")
                    finally:
                        _con.close()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.log(f"统一投递异常，保留队列: {type(exc).__name__}")
                    return
                if outcome == "confirmed":
                    qq_outbox.ack(it)
                    sent.append(time.time())
                    self.log(f"主动联系已发: {text[:40]}")
                elif outcome == "unknown":
                    # 发送后结果未知：**不盲重发**；持久存储已留 unknown 证据，出站队列移除
                    qq_outbox.ack(it)
                    self.log(f"主动联系结果未知(已存证据,不重发): {text[:40]}")
                else:
                    self.log(f"主动联系未确认({outcome})，保留队列: {text[:40]}")
                    return

    async def _status_hb(self) -> None:
        """Local event-loop heartbeat for the watchdog (5s, guide 13.4)."""
        interval = float(os.getenv("YHLZ_QQ_STATUS_INTERVAL", "5"))
        probe = 0.0
        while True:
            self.connection._extra["event_loop_ts"] = time.time()
            ws = self._ws
            if ws is not None and time.time() - probe >= 60.0:
                probe = time.time()
                try:
                    ev = await self._request(ws, "get_status", {}, timeout=5)
                    data = ev.get("data") if isinstance(ev, dict) else None
                    if isinstance(data, dict) and "online" in data:
                        self.connection._extra["account_online"] = bool(
                            data.get("online"))
                        self.connection._extra["account_checked_at"] = time.time()
                except Exception:
                    pass
            self._write_status()
            await asyncio.sleep(max(1.0, interval))

    async def _relay_notices(self, ws) -> None:
        """Relay outage notices (lost before recovered) via current socket."""
        from backend.qq_bridge_notices import NoticeStore

        store = NoticeStore(NOTICES, bot_uin=self.uin)
        while True:
            await asyncio.sleep(10)
            if not self.masters:
                continue
            recipient = str(next(iter(self.masters)))
            try:
                rec = store.next_to_send()
            except Exception:
                continue
            if not rec or str(rec.get("recipient")) != recipient:
                continue
            store.mark(rec["notice_id"], "sending")
            params = {"message_type": "private", "user_id": int(recipient),
                      "message": str(rec.get("text", ""))}
            try:
                result = await self._deliver(params, ws=ws, kind="notice")
            except Exception as exc:  # noqa: BLE001
                store.mark(rec["notice_id"], "pending",
                           error=type(exc).__name__)
                continue
            status = str(result.get("status"))
            if status == "confirmed":
                store.mark(rec["notice_id"], "sent")
                self.log(f"通知已发: {rec.get('kind')}")
            elif status == "unknown":
                store.mark(rec["notice_id"], "unknown")
                self.log(f"通知结果未知(不重发): {rec.get('kind')}")
            else:
                store.mark(rec["notice_id"], "pending", error=status)

    async def _read_loop(self, ws) -> None:
        async for raw in ws:
            self.connection.last_rx_at = time.time()
            self._write_status()
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            echo = str(ev.get("echo") or "")
            if echo and echo in self._pending:
                fut = self._pending.get(echo)
                if fut is not None and not fut.done():
                    fut.set_result(ev)
                continue
            if ev.get("post_type") == "meta_event":
                if ev.get("meta_event_type") == "heartbeat":
                    status = ev.get("status")
                    status = status if isinstance(status, dict) else {}
                    self.connection._extra["account_online"] = bool(
                        status.get("online"))
                    self.connection._extra["last_heartbeat_at"] = time.time()
                elif ev.get("meta_event_type") == "lifecycle":
                    self.log("生命周期: " + str(ev.get("sub_type")))
                continue
            if ev.get("post_type") == "message":
                self._enqueue(ev)

    async def _heartbeat(self, ws) -> None:
        await heartbeat_loop(ws, self.connection, interval=QQ_PING_INTERVAL,
                             timeout=QQ_PONG_TIMEOUT,
                             on_state=lambda state: self._set_state(state))

    async def run(self) -> None:
        import websockets

        self.loop = asyncio.get_running_loop()
        self.log(f"参与频率: 群冷却{GROUP_USER_COOLDOWN:g}s "
                 f"群间隔{GROUP_CHAN_GAP:g}s {GROUP_CHAN_PER_MIN}/min "
                 f"日上限{GROUP_DAILY_LIMIT} 私聊冷却{PRIVATE_USER_COOLDOWN:g}s")
        if _wake_gate_enabled():
            _names = "、".join(_wake_names()) or "-"
            _modes = ["@", _names, "引用回复"]
            if _wake_topics_enabled():
                _modes.append("知识" + ("+记忆" if _wake_memory_enabled() else ""))
            elif _wake_memory_enabled():
                _modes.append("记忆")
            if _wake_master_always():
                _modes.append("主人始终")
            self.log("唤醒闸门: 开（" + "/".join(_modes) + "）；其余群消息只入库不处理")
        else:
            self.log("唤醒闸门: 关（群消息全量处理）")
        _groups = _allowed_groups()
        self.log("群白名单: " + ("未设（所有群）" if _groups is None
                                 else f"{len(_groups)} 群生效"))
        _at_only = _wake_at_only_groups()
        if _at_only:
            self.log("仅@唤醒群: " + "、".join(sorted(_at_only)))
        _wm = _wake_mode()
        self.log("对话档位: " + MODE_LABELS[_wm])
        if _wm == "reserved":
            self.log("内敛生效：群里仅 @/名字唤醒；私聊正常")
        elif _wm == "silent":
            self.log("缄默生效：群里/@ 均不回、私聊静默；# 指令仍可用")
        self.log("沉默出口: " + ("开（仅知识/记忆/名字唤醒可沉默；@/引用/主人必回）"
                                 if _silence_enabled() else "关"))
        if _voice_mode() == "full":
            threading.Thread(target=_warm_asr, daemon=True).start()
        self.inbox = asyncio.Queue(maxsize=max(1, INBOX_LIMIT))
        self._inbox_task = asyncio.create_task(self._inbox_worker())
        self._status_task = asyncio.create_task(self._status_hb())
        self._profile_task = asyncio.create_task(self._profile_updater())
        if _bridge_profile() != "full":
            mod = _dev_mod()
            if mod is not None:
                try:
                    recovered = await asyncio.to_thread(mod.recover)
                    if recovered:
                        self.log(f"dev jobs：{recovered} 个 running 任务标记 interrupted")
                except Exception:
                    pass
        delay = 1.0
        try:
            while True:
                try:
                    self._set_state("reconnecting" if self.connection.reconnect_count else "starting")
                    self.log(f"连接 {_redact_url(self.ws_url)} "
                             f"(元亨 QQ号 {self.uin})")
                    async with websockets.connect(
                            self.ws_url, **websocket_options(
                                open_timeout=QQ_CONNECT_TIMEOUT)) as ws:
                        self.connection.connected_at = time.time()
                        self.connection.next_retry_at = 0.0
                        self._ws = ws
                        self._ws_ready.set()
                        self._set_state("connected")
                        self._transport.ws = ws
                        self.log("已连接，等待消息（私聊 / 群聊）…")
                        relay = asyncio.create_task(self._relay_outbox(ws))
                        notices = asyncio.create_task(self._relay_notices(ws))
                        devjobs = asyncio.create_task(self._relay_dev_jobs(ws))
                        heartbeat = asyncio.create_task(self._heartbeat(ws))
                        reader = asyncio.create_task(self._read_loop(ws))
                        try:
                            done, pending = await asyncio.wait(
                                {reader, heartbeat},
                                return_when=asyncio.FIRST_COMPLETED)
                            for task in done:
                                exc = task.exception()
                                if exc:
                                    raise exc
                            raise ConnectionError("QQ websocket reader stopped")
                        finally:
                            self._ws = None
                            self._ws_ready.clear()
                            self._transport.ws = None
                            for task in (relay, notices, devjobs, heartbeat,
                                         reader):
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(relay, notices, devjobs,
                                                 heartbeat, reader,
                                                 return_exceptions=True)
                            self._fail_pending(ConnectionError("QQ socket closed"))
                except asyncio.CancelledError:
                    self._set_state("stopped")
                    raise
                except Exception as e:  # noqa: BLE001
                    self.connection.reconnect_count += 1
                    self.connection.last_error = type(e).__name__
                    self.connection.next_retry_at = time.time() + delay
                    self._set_state("reconnecting", type(e).__name__)
                    self.log(f"连接断开 {type(e).__name__}: {e}，{delay:g}s 后重连")
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 30.0)
        finally:
            tasks = list(self._tasks)
            for extra in (self._inbox_task, self._status_task,
                          self._profile_task):
                if extra is not None:
                    tasks.append(extra)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._write_status()


def main() -> int:
    # single-instance lock (avoid duplicate bridges replying twice)
    import atexit
    import os as _os

    lock = _bridge_path("bridge.lock", _PROJECT / "cache" / "tmp" / "qqbot.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)

    from backend.qq_bridge_lock import pid_alive as _pid_alive

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
    _log_path = _bridge_path("bridge.log", _PROJECT / "cache" / "tmp" / "qqbot.log")
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    _logf = open(_log_path, "a", encoding="utf-8", buffering=1)
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
    print(f"[qqbot] profile={_bridge_profile()} state_dir={_bridge_state_dir()}",
          flush=True)
    from backend.qq_account_lock import AccountLock

    account = AccountLock(s["uin"])
    if not account.acquire():
        print("[qqbot] 账号锁被另一消费者持有，fail closed（拒绝第二个消费者）",
              flush=True)
        return 1
    masters = set(a.master or [MASTER_UIN])
    bridge = QQBridge(url, s["uin"], cfg, masters=masters)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    finally:
        account.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
