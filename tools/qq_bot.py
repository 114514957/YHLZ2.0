# QQ 机器人相关功能（OneBot11 桥接）
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
MEDIA_DIR = _PROJECT / "cache" / "qq_media"
MEDIA_KEEP_DAYS = 7
IMG_MAX_BYTES = 8 * 1024 * 1024        # group/private image cap
AUDIO_MAX_BYTES = 10 * 1024 * 1024
AUDIO_MAX_SECONDS = 60                 # voice clip cap
GROUP_USER_COOLDOWN = 8.0              # per-user min gap between group replies
GROUP_CHAN_PER_MIN = 20                # per-group reply budget / minute


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
QQ_STATE = _PROJECT / "cache" / "tmp" / "qq_state.json"


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


def _extract_markers(ans: str) -> tuple[str, list, list, list, bool, list]:
    import re

    imgs = re.findall(r"\[\[img:\s*(.+?)\]\]", ans)
    files = re.findall(r"\[\[file:\s*(.+?)\]\]", ans)
    faces = re.findall(r"\[\[face:\s*(\d+)\]\]", ans)
    devs = re.findall(r"\[\[dev:\s*(.+?)\]\]", ans)
    voice = "[[voice]]" in ans
    ans = re.sub(r"\[\[(?:img|file):.*?\]\]", "", ans)
    ans = re.sub(r"\[\[face:\s*\d+\]\]", "", ans)
    ans = re.sub(r"\[\[dev:\s*.*?\]\]", "", ans).replace("[[voice]]", "")
    return ans.strip(), imgs, files, faces, voice, devs


def _tts_wav(text: str) -> str:
    """Text -> wav (24k mono). edge-tts (natural, needs net); SAPI fallback."""
    import subprocess
    import tempfile

    text = str(text or "").strip()
    if not text:
        return ""
    d = pathlib.Path(tempfile.mkdtemp(prefix="yhlz_tts_"))
    wav = d / "t.wav"
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


def _daemon_turn(text: str, channel: str, images: list | None = None) -> str:
    body: dict = {"text": str(text)[:1500], "channel": channel}
    if images:
        body["images"] = [str(p) for p in images][:4]
    data = json.dumps(body).encode()
    req = urllib.request.Request(DAEMON + "/turn", data=data,
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
        self._last_reply: dict = {}
        self._chan_reply: dict = {}

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

    @staticmethod
    def _file_uri(path: str) -> str:
        return "file:///" + str(pathlib.Path(path).resolve()).replace("\\", "/")

    async def _send_segment(self, ws, params: dict, seg: dict) -> None:
        p = dict(params)
        p["message"] = [seg]
        await self._send(ws, "send_msg", p)

    async def _send_voice(self, ws, params, text: str) -> bool:
        wav = await asyncio.to_thread(_tts_wav, text)
        silk = await asyncio.to_thread(_wav_to_silk, wav) if wav else ""
        if not silk:
            return False
        await self._send_segment(
            ws, params, {"type": "record", "data": {"file": self._file_uri(silk)}})
        return True

    async def _send_image(self, ws, params, path: str) -> None:
        await self._send_segment(
            ws, params, {"type": "image", "data": {"file": self._file_uri(path)}})

    async def _send_file(self, ws, params, path: str) -> None:
        await self._send_segment(ws, params, {
            "type": "file",
            "data": {"file": self._file_uri(path),
                     "name": pathlib.Path(path).name}})

    async def _dev_report(self, ws, params, status, text, hint: bool = True) -> None:
        tag = {"awaiting": "❓ 需要你决定", "done": "✅ 完成",
               "error": "⚠️ 出错", "running": "⏳ 进行中",
               "info": "ℹ️"}.get(status, status)
        msg = f"[opencode] {tag}\n{text}"
        if status == "done" and hint:
            msg += "\n\n回 #y 提交 / #n 不提交 / #push 推送"
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
        """Kick off an opencode dev task (ask-first flow) for the owner."""
        if dev_runner is None:
            await self._say(ws, params, "[opencode] 运行器不可用")
            return
        task = str(task).strip()
        if not task:
            return
        await self._say(ws, params, f"[opencode] 已开工：{task[:80]}")
        self._spawn(ws, params, lambda: (
            (lambda d: (d.get("status", "error"), d.get("text", "")))(
                dev_runner.start(task))))

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
                        lambda: ("info", dev_runner.commit(msg).get("text", "")),
                        hint=False)
        elif low == "#n":
            await self._say(ws, params, "[opencode] 好的，不提交，改动留在工作区。")
        elif low == "#push":
            self._spawn(ws, params,
                        lambda: ("info", dev_runner.push().get("text") or "已推送"),
                        hint=False)
        elif low == "#dev" or low.startswith("#dev "):
            task = low[4:].strip()
            if not task:
                await self._say(ws, params, "用法：#dev <任务>")
                return
            await self._start_dev(ws, params, task)
        elif low in ("#voice", "#voice on", "#voice off"):
            st = _load_state()
            arg = low.replace("#voice", "").strip()
            st["voice"] = True if arg == "on" else (
                False if arg == "off" else not st.get("voice", False))
            _save_state(st)
            await self._say(ws, params,
                            f"[元亨] 语音回复已{'开' if st['voice'] else '关'}")
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
        else:
            await self._say(ws, params,
                            "未知指令：#dev <任务> / #y / #n / #push / #devstatus / "
                            "#voice on|off / #say <文字> / #img <路径> / #file <路径> / #face <id>")

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

    def _rate_limited(self, channel: str, user_id: str) -> bool:
        """Group anti-spam: per-user cooldown + per-group per-minute budget."""
        if user_id in self.masters:
            return False
        now = time.time()
        if now - self._last_reply.get(user_id, 0.0) < GROUP_USER_COOLDOWN:
            return True
        times = self._chan_reply.setdefault(channel, [])
        times[:] = [t for t in times if now - t < 60.0]
        if len(times) >= GROUP_CHAN_PER_MIN:
            return True
        self._last_reply[user_id] = now
        times.append(now)
        return False

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
        if msg_type == "group" and self._rate_limited(channel, user_id):
            self.log(f"群频控跳过 {user_id} @ {channel}")
            return
        imgs = (await self._collect_images(msg)
                if any(s.get("type") == "image" for s in msg) else [])
        if any(s.get("type") == "record" for s in msg):
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
            return
        self.log(f"来自 {user_id}: {text[:40]}"
                 + (f" [+{len(imgs)}图]" if imgs else ""))
        ans = _daemon_turn(text, channel, images=imgs)
        if not ans:
            return
        ans, out_imgs, out_files, out_faces, vmark, out_devs = _extract_markers(ans.strip())
        params = {"message": ans}
        if msg_type == "private":
            params.update(message_type="private", user_id=int(user_id))
        else:
            params.update(message_type="group",
                          group_id=int(ev.get("group_id", 0)))
        # Yuanheng handed a real dev task to opencode (owner only)
        if out_devs and user_id in self.masters:
            await self._start_dev(ws, params, out_devs[0])
        for fid in out_faces:
            await self._send_segment(
                ws, params, {"type": "face", "data": {"id": int(fid)}})
        for ip in out_imgs:
            if pathlib.Path(ip).exists():
                await self._send_image(ws, params, ip)
        for fp in out_files:
            if pathlib.Path(fp).exists():
                await self._send_file(ws, params, fp)
        if not ans:
            return
        want_voice = (vmark or _load_state().get("voice", False)
                      or _voice_intent(text))
        if want_voice and await self._send_voice(ws, params, ans):
            return
        for part in [ans[i:i + 1400] for i in range(0, len(ans), 1400)]:
            params["message"] = part
            await self._send(ws, "send_msg", params)

    async def _relay_outbox(self, ws) -> None:
        """P2e: relay queued proactive messages (from the daemon) to the master.
        Only runs while connected; rate-limited to <=2/hour."""
        sent: list = []
        master = int(next(iter(self.masters)))
        while True:
            await asyncio.sleep(90)
            try:
                from backend import qq_outbox

                items = qq_outbox.drain(3)
            except Exception:
                items = []
            now = time.time()
            sent[:] = [t for t in sent if now - t < 3600]
            for it in items:
                if len(sent) >= 2:
                    break
                text = str(it.get("text", "")).strip()
                if not text:
                    continue
                try:
                    await self._send(ws, "send_msg", {
                        "message_type": "private", "user_id": master,
                        "message": text})
                    sent.append(time.time())
                    self.log(f"主动联系已发: {text[:40]}")
                except Exception:
                    pass

    async def run(self) -> None:
        import websockets

        self.loop = asyncio.get_running_loop()
        threading.Thread(target=_warm_asr, daemon=True).start()
        delay = 3
        while True:
            try:
                self.log(f"连接 {self.ws_url} (元亨 QQ号 {self.uin})")
                async with websockets.connect(self.ws_url) as ws:
                    delay = 3
                    self.log("已连接，等待消息（私聊 / 群里 @元亨）…")
                    relay = asyncio.create_task(self._relay_outbox(ws))
                    try:
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
                    finally:
                        relay.cancel()
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
