"""L1 本机音频服务：OBS 浏览器源专用出口（台账 0679/0680）。

数据流：控制端（CLI/后续编排）``say`` → 本服务经 HTTP 调用现有
daemon ``/tts``（Qwen3-TTS 0.6B-Base 克隆音色，24kHz mono s16le WAV）
→ 有界队列 + 单消费者租约 → OBS 浏览器源页面（``window.obsstudio`` 内）
经 WebAudio 消费 → started/ended 回执。

硬规则：不打开任何本机音频设备；不回落系统默认输出；未武装(arm)或
无租约时不派发音频；停止/断开后旧段不得重播，generation 递增。
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "live.json"
LOCAL_CONFIG_PATH = ROOT / "config" / "live.local.json"
PAGE_PATH = ROOT / "assets" / "live_output" / "player.html"
MAX_TEXT_CHARS = 200
MAX_BODY_BYTES = 64 * 1024
AUDIO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.wav$")

TERMINAL_STATES = ("ended", "failed", "expired", "cancelled")


def now_ms() -> int:
    return int(time.time() * 1000)


def wav_info(data: bytes) -> tuple[int, int, int, int]:
    """Return (sample_rate, channels, bits, data_size) of a RIFF/WAVE buffer."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE buffer")
    sr = ch = bits = 0
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        body = offset + 8
        if chunk_id == b"fmt " and size >= 16 and body + 16 <= len(data):
            ch = int.from_bytes(data[body + 2:body + 4], "little")
            sr = int.from_bytes(data[body + 4:body + 8], "little")
            bits = int.from_bytes(data[body + 14:body + 16], "little")
        if chunk_id == b"data":
            return sr, ch, bits, min(size, len(data) - body)
        offset = body + size + (size % 2)
    raise ValueError("no data chunk")


@dataclass
class LiveConfig:
    host: str = "127.0.0.1"
    port: int = 8377
    tts_url: str = "http://127.0.0.1:8321/tts"
    tts_timeout_s: float = 240.0
    segment_ttl_s: float = 30.0
    max_queue: int = 24
    lease_ttl_s: float = 15.0
    poll_timeout_s: float = 10.0
    audio_dir: str = "cache/live/audio"
    lease_token: str = ""


def load_config(path: Optional[Path] = None) -> LiveConfig:
    base_path = Path(path) if path else DEFAULT_CONFIG_PATH
    merged: dict[str, Any] = {}
    for src in (base_path, LOCAL_CONFIG_PATH):
        if src.exists():
            try:
                merged.update(json.loads(src.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    config = LiveConfig(**{k: v for k, v in merged.items()
                           if k in LiveConfig.__dataclass_fields__})
    if not config.lease_token:
        config.lease_token = secrets.token_hex(24)
        LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if LOCAL_CONFIG_PATH.exists():
            try:
                existing = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
        existing["lease_token"] = config.lease_token
        LOCAL_CONFIG_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def token_fingerprint(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class LiveError(Exception):
    code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class AuthError(LiveError):
    code = 401


class LeaseError(LiveError):
    code = 409

    def __init__(self, detail: str, holder: Optional[str] = None):
        super().__init__(detail)
        self.holder = holder


class QueueFullError(LiveError):
    code = 429


class StaleError(LiveError):
    code = 409


class NotFoundError(LiveError):
    code = 404


class TtsError(LiveError):
    code = 502


@dataclass
class Segment:
    speech_id: str
    segment_id: str
    text: str
    filename: str
    duration_s: float
    sample_rate: int
    channels: int
    sha256_16: str
    synth_ms: int
    created_at: float
    generation: int
    state: str = "queued"
    source: str = "tts"
    acks: list[dict[str, Any]] = field(default_factory=list)


class AudioSink:
    """Bounded, lease-guarded WAV queue served to one OBS browser client."""

    def __init__(self, config: LiveConfig):
        self.config = config
        audio_dir = Path(config.audio_dir)
        self.audio_dir = audio_dir if audio_dir.is_absolute() else ROOT / audio_dir
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self._seq = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=500)
        self._segments: dict[str, Segment] = {}
        self._order: deque[str] = deque()
        self._lease_holder: Optional[str] = None
        self._lease_seen = 0.0
        self._lease_meta: dict[str, Any] = {}
        self.armed = False
        self.route: dict[str, Any] = {"route": None, "monitor": None,
                                      "at_ms": None, "by": None}
        self.generation = 1
        self.counters: Counter[str] = Counter()
        self.ack_log: deque[dict[str, Any]] = deque(maxlen=200)
        self.tts_last_ok_ms: Optional[int] = None
        self.tts_last_error: Optional[str] = None
        self._cleanup_old_files()

    def _cleanup_old_files(self) -> None:
        cutoff = time.time() - 24 * 3600
        for path in self.audio_dir.glob("*.wav"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def _emit(self, type_: str, **fields: Any) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "type": type_, "wall_ms": now_ms(), **fields}
        self._events.append(event)
        self.cond.notify_all()
        return event

    def _expire_locked(self) -> None:
        now = time.monotonic()
        ttl = self.config.segment_ttl_s
        for segment in self._segments.values():
            if segment.state == "queued" and now - segment.created_at > ttl:
                segment.state = "expired"
                self.counters["expired"] += 1
                self._emit("expired", segment_id=segment.segment_id,
                           speech_id=segment.speech_id)
        self._prune_locked()

    def _prune_locked(self) -> None:
        if len(self._order) <= 200:
            return
        recent = set(list(self._order)[-50:])
        keep: list[str] = []
        for sid in self._order:
            segment = self._segments.get(sid)
            if segment is None:
                continue
            if segment.state not in TERMINAL_STATES or sid in recent:
                keep.append(sid)
        self._order = deque(keep)
        keep_set = set(keep)
        for sid in list(self._segments):
            if sid not in keep_set:
                self._segments.pop(sid, None)

    def _lease_state_locked(self) -> tuple[Optional[str], float]:
        if self._lease_holder is None:
            return None, 0.0
        remaining = self.config.lease_ttl_s - (time.monotonic() - self._lease_seen)
        if remaining <= 0:
            self._lease_lost_locked()
            return None, 0.0
        return self._lease_holder, remaining

    def _lease_lost_locked(self) -> None:
        holder = self._lease_holder
        if holder is None:
            return
        self._lease_holder = None
        self._lease_meta = {}
        unknown = 0
        for segment in self._segments.values():
            if segment.state in ("scheduled", "started"):
                segment.state = "cancelled"
                unknown += 1
        if unknown or self.armed:
            self.generation += 1
            self.armed = False
            for segment in self._segments.values():
                if segment.state == "queued":
                    segment.generation = self.generation
            self._emit("lease_lost", holder=holder, cancelled=unknown,
                       generation=self.generation)
        self.counters["lease_lost"] += 1

    def _touch_lease_locked(self, client_id: str, *, acquire: bool,
                            ua: str = "", remote: str = "") -> None:
        self._expire_locked()
        holder, _ = self._lease_state_locked()
        if holder is None and acquire:
            self._lease_holder = client_id
            self._lease_meta = {"ua": ua, "remote": remote, "at_ms": now_ms()}
            self.counters["lease_acquired"] += 1
            self._emit("lease_acquired", holder=client_id)
        elif holder is not None and holder != client_id:
            raise LeaseError("lease-held-by-other", holder=holder)
        self._lease_seen = time.monotonic()

    def synth_and_enqueue(self, text: str) -> dict[str, Any]:
        text = str(text or "").strip()[:MAX_TEXT_CHARS]
        if not text:
            raise LiveError("empty-text")
        with self.lock:
            self._expire_locked()
            if self._active_queue_len_locked() >= self.config.max_queue:
                raise QueueFullError("queue-full")
            gen_entry = self.generation
        started = time.monotonic()
        try:
            wav = self._tts_synthesize(text)
            sr, ch, bits, data_size = wav_info(wav)
        except LiveError as exc:
            with self.lock:
                self.counters["tts_fail"] += 1
                self.tts_last_error = exc.detail
            raise
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.counters["tts_fail"] += 1
                self.tts_last_error = f"{type(exc).__name__}: {exc}"
            raise TtsError(self.tts_last_error) from exc
        synth_ms = int((time.monotonic() - started) * 1000)
        speech_id = f"live-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        filename = f"{speech_id}.wav"
        (self.audio_dir / filename).write_bytes(wav)
        duration_s = data_size / float(max(1, sr * ch * max(1, bits // 8)))
        import hashlib
        segment = Segment(
            speech_id=speech_id, segment_id=speech_id, text=text,
            filename=filename, duration_s=round(duration_s, 3),
            sample_rate=sr, channels=ch,
            sha256_16=hashlib.sha256(wav).hexdigest()[:16],
            synth_ms=synth_ms, created_at=time.monotonic(),
            generation=self.generation, source="tts")
        with self.lock:
            if self.generation != gen_entry:
                self.counters["dropped_stale"] += 1
                raise StaleError("generation-changed")
            self.tts_last_ok_ms = synth_ms
            self.tts_last_error = None
            self.counters["tts_ok"] += 1
            self._expire_locked()
            if self._active_queue_len_locked() >= self.config.max_queue:
                raise QueueFullError("queue-full")
            self._segments[segment.segment_id] = segment
            self._order.append(segment.segment_id)
            self._emit("segment", segment_id=segment.segment_id,
                       speech_id=segment.speech_id, duration_s=segment.duration_s)
            return self.brief_locked(segment)

    def enqueue_cached(self, filename: str) -> dict[str, Any]:
        name = str(filename or "").strip()
        if not AUDIO_NAME_RE.match(name):
            raise LiveError("bad-audio-name")
        path = self.audio_dir / name
        if not path.exists():
            raise NotFoundError("no-cached-audio")
        with self.lock:
            self._expire_locked()
            if self._active_queue_len_locked() >= self.config.max_queue:
                raise QueueFullError("queue-full")
            gen_entry = self.generation
        data = path.read_bytes()
        sr, ch, bits, data_size = wav_info(data)
        duration_s = data_size / float(max(1, sr * ch * max(1, bits // 8)))
        import hashlib
        with self.lock:
            if self.generation != gen_entry:
                self.counters["dropped_stale"] += 1
                raise StaleError("generation-changed")
            speech_id = f"replay-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
            segment = Segment(
                speech_id=speech_id, segment_id=speech_id, text=f"[cached] {name}",
                filename=name, duration_s=round(duration_s, 3),
                sample_rate=sr, channels=ch,
                sha256_16=hashlib.sha256(data).hexdigest()[:16],
                synth_ms=0, created_at=time.monotonic(),
                generation=self.generation, source="cached")
            self._segments[segment.segment_id] = segment
            self._order.append(segment.segment_id)
            self._emit("segment", segment_id=segment.segment_id,
                       speech_id=segment.speech_id, duration_s=segment.duration_s,
                       source="cached")
            return self.brief_locked(segment)

    def _tts_synthesize(self, text: str) -> bytes:
        payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.tts_url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(
                    request, timeout=self.config.tts_timeout_s) as response:
                if response.status != 200:
                    raise TtsError(f"tts-http-{response.status}")
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()[:200].decode("utf-8", "replace")
            raise TtsError(f"tts-http-{exc.code}:{body}") from exc
        except urllib.error.URLError as exc:
            raise TtsError(f"tts-unreachable:{exc.reason}") from exc

    def _active_queue_len_locked(self) -> int:
        return sum(1 for sid in self._order
                   if sid in self._segments
                   and self._segments[sid].state not in TERMINAL_STATES)

    def brief_locked(self, segment: Segment) -> dict[str, Any]:
        return {
            "speech_id": segment.speech_id,
            "segment_id": segment.segment_id,
            "text": segment.text,
            "state": segment.state,
            "generation": segment.generation,
            "duration_s": segment.duration_s,
            "sample_rate": segment.sample_rate,
            "channels": segment.channels,
            "sha256_16": segment.sha256_16,
            "synth_ms": segment.synth_ms,
            "source": segment.source,
            "age_s": round(time.monotonic() - segment.created_at, 3),
            "audio_path": f"/audio/{segment.filename}",
        }

    def _queue_locked(self) -> list[dict[str, Any]]:
        return [self.brief_locked(self._segments[sid]) for sid in self._order
                if sid in self._segments
                and self._segments[sid].state not in TERMINAL_STATES]

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._expire_locked()
            holder, remaining = self._lease_state_locked()
            return {
                "service": "yhlz-live-l1",
                "now_ms": now_ms(),
                "armed": self.armed,
                "route": dict(self.route),
                "generation": self.generation,
                "lease": {
                    "holder": holder,
                    "expires_in_s": round(remaining, 2) if holder else None,
                    "client_ua": self._lease_meta.get("ua"),
                    "remote": self._lease_meta.get("remote"),
                },
                "queue": self._queue_locked(),
                "counters": dict(sorted(self.counters.items())),
                "recent_acks": list(self.ack_log)[-10:],
                "events": list(self._events)[-20:],
                "tts": {"url": self.config.tts_url,
                        "last_ok_ms": self.tts_last_ok_ms,
                        "last_error": self.tts_last_error},
                "config": {
                    "segment_ttl_s": self.config.segment_ttl_s,
                    "max_queue": self.config.max_queue,
                    "lease_ttl_s": self.config.lease_ttl_s,
                    "poll_timeout_s": self.config.poll_timeout_s,
                },
            }

    def channel(self, client_id: str, since: int, ua: str, remote: str,
                wait_s: Optional[float] = None) -> dict[str, Any]:
        wait_s = self.config.poll_timeout_s if wait_s is None else wait_s
        with self.lock:
            self._touch_lease_locked(client_id, acquire=True, ua=ua, remote=remote)
            deadline = time.monotonic() + max(0.0, wait_s)
            while True:
                events = [e for e in self._events if e["seq"] > since]
                dispatchable = self.armed and any(
                    seg.state == "queued" for seg in self._segments.values())
                if events or dispatchable or time.monotonic() >= deadline:
                    break
                self.cond.wait(timeout=min(0.5, max(0.05, deadline - time.monotonic())))
            holder, remaining = self._lease_state_locked()
            return {
                "ok": True,
                "since": self._seq,
                "events": events[-100:],
                "armed": self.armed,
                "route": dict(self.route),
                "generation": self.generation,
                "queue": self._queue_locked(),
                "lease": {"client_id": holder,
                          "expires_in_s": round(remaining, 2) if holder else None},
            }

    def ack(self, client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        segment_id = str(payload.get("segment_id") or "")
        kind = str(payload.get("kind") or "")
        if kind not in ("scheduled", "started", "ended", "failed"):
            raise LiveError("bad-ack-kind")
        with self.lock:
            self._touch_lease_locked(client_id, acquire=False)
            segment = self._segments.get(segment_id)
            if segment is None:
                raise NotFoundError("unknown-segment")
            generation = int(payload.get("generation") or 0)
            if generation != self.generation:
                raise StaleError("stale-generation")
            if kind == "scheduled" and segment.state == "queued":
                segment.state = "scheduled"
            elif kind == "started" and segment.state in ("queued", "scheduled"):
                segment.state = "started"
                self.counters["started"] += 1
            elif kind == "ended" and segment.state in ("started", "scheduled"):
                segment.state = "ended"
                self.counters["ended"] += 1
            elif kind == "failed" and segment.state not in TERMINAL_STATES:
                segment.state = "failed"
                self.counters["failed"] += 1
            entry = {"t_ms": now_ms(), "client_id": client_id,
                     "segment_id": segment_id, "kind": kind,
                     "state": segment.state,
                     "generation": generation,
                     "at_client_ms": payload.get("at_client_ms"),
                     "detail": payload.get("detail")}
            segment.acks.append(entry)
            self.ack_log.append(entry)
            self.cond.notify_all()
            return {"ok": True, "state": segment.state}

    def control(self, action: str, payload: dict[str, Any],
                *, client_id: Optional[str] = None,
                by: str = "control") -> dict[str, Any]:
        action = str(action or "")
        if action == "say":
            return self.synth_and_enqueue(str(payload.get("text") or ""))
        if action == "enqueue_audio":
            return self.enqueue_cached(str(payload.get("filename") or ""))
        with self.lock:
            if action == "arm":
                self._expire_locked()
                self.armed = True
                self.route = {"route": str(payload.get("route") or "obs_browser"),
                              "monitor": str(payload.get("monitor") or "off"),
                              "at_ms": now_ms(), "by": by}
                self.counters["arm"] += 1
                self._emit("arm", route=self.route["route"],
                           monitor=self.route["monitor"])
            elif action == "disarm":
                self.armed = False
                self.counters["disarm"] += 1
                self._emit("disarm")
            elif action == "stop":
                cancelled = 0
                for segment in self._segments.values():
                    if segment.state not in TERMINAL_STATES:
                        segment.state = "cancelled"
                        cancelled += 1
                self.generation += 1
                self.armed = False
                holder = self._lease_holder
                self._lease_holder = None
                self.counters["stop"] += 1
                self._emit("stop", cancelled=cancelled, holder=holder,
                           generation=self.generation,
                           reason=str(payload.get("reason") or "owner"))
            else:
                raise LiveError("bad-action")
        return self.status()

    def audio_file(self, name: str) -> Path:
        if not AUDIO_NAME_RE.match(name):
            raise NotFoundError("bad-audio-name")
        path = (self.audio_dir / name).resolve()
        if path.parent != self.audio_dir.resolve() or not path.exists():
            raise NotFoundError("no-audio-file")
        return path

    def authorize(self, token: str) -> None:
        if not hmac.compare_digest(str(token or ""), self.config.lease_token):
            raise AuthError("bad-token")


class LiveAudioHandler(BaseHTTPRequestHandler):
    service: AudioSink
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, BrokenPipeError):
            pass

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _error(self, exc: LiveError) -> None:
        self._json(exc.code, {"ok": False, "error": exc.detail,
                              "holder": getattr(exc, "holder", None)})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise LiveError("bad-length")
        if not 0 <= length <= MAX_BODY_BYTES:
            raise LiveError("body-too-large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LiveError("bad-json")
        if not isinstance(data, dict):
            raise LiveError("bad-json")
        return data

    def _params(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _page(self) -> None:
        try:
            body = PAGE_PATH.read_bytes()
        except OSError:
            self._json(500, {"ok": False, "error": "player-page-missing"})
            return
        self._send(200, body, "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        params = self._params()
        try:
            if route.path in ("/", "/player"):
                self._page()
                return
            if route.path == "/status":
                self._json(200, self.service.status())
                return
            if route.path == "/channel":
                self.service.authorize((params.get("token") or [""])[0])
                client_id = (params.get("client_id") or [""])[0].strip()
                if not client_id:
                    raise LiveError("client-id-required")
                since = int((params.get("since") or ["0"])[0] or 0)
                result = self.service.channel(
                    client_id, since, self.headers.get("User-Agent", ""),
                    self.client_address[0] if self.client_address else "")
                self._json(200, result)
                return
            if route.path.startswith("/audio/"):
                self.service.authorize((params.get("token") or [""])[0])
                if not self.service.armed:
                    raise LeaseError("not-armed")
                path = self.service.audio_file(route.path.rsplit("/", 1)[-1])
                self._send(200, path.read_bytes(), "audio/wav")
                return
            raise NotFoundError("not-found")
        except LiveError as exc:
            self._error(exc)
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        try:
            payload = self._read_json()
            self.service.authorize(str(payload.get("token") or ""))
            if route.path == "/control":
                client_id = str(payload.get("client_id") or "control")
                result = self.service.control(
                    str(payload.get("action") or ""), payload,
                    client_id=client_id, by=client_id)
                self._json(200, {"ok": True, "result": result})
                return
            if route.path == "/ack":
                client_id = str(payload.get("client_id") or "").strip()
                if not client_id:
                    raise LiveError("client-id-required")
                result = self.service.ack(client_id, payload)
                self._json(200, result)
                return
            raise NotFoundError("not-found")
        except LiveError as exc:
            self._error(exc)
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def make_server(config: LiveConfig) -> ThreadingHTTPServer:
    service = AudioSink(config)
    handler = type("BoundLiveAudioHandler", (LiveAudioHandler,),
                   {"service": service})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    server.daemon_threads = True
    return server
