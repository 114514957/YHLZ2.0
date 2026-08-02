from __future__ import annotations
import asyncio
import dataclasses
import enum
import io
import logging
import threading
import time
import re
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple, Callable
import aiohttp
from pydub import AudioSegment
import winsound
import subprocess
import shutil

from .models import LiveSettings, ReplacementRule

logger = logging.getLogger("live_stream.tts_service")

class Priority(enum.IntEnum):
    HIGH = 0
    NORMAL = 1

@dataclasses.dataclass
class TtsTask:
    text: str
    priority: Priority = Priority.NORMAL
    key: Optional[str] = None
    room_id: Optional[int] = None

class PredictQueue:
    def __init__(self, max_size: Optional[int] = None, on_evict: Optional[Callable[[TtsTask], None]] = None):
        self._max_size = max_size
        self._high: Deque[TtsTask] = deque()
        self._normal: Deque[TtsTask] = deque()
        self._cv = threading.Condition()
        self._on_evict = on_evict

    def push(self, task: TtsTask) -> bool:
        with self._cv:
            cap = self._max_size if isinstance(self._max_size, int) and self._max_size > 0 else None
            size = len(self._high) + len(self._normal)
            if cap is not None and size >= cap:
                if task.priority == Priority.HIGH:
                    evicted = self._normal.popleft() if self._normal else (self._high.popleft() if self._high else None)
                    if evicted and self._on_evict:
                        self._on_evict(evicted)
                else:
                    return False
            if task.priority == Priority.HIGH:
                self._high.append(task)
            else:
                self._normal.append(task)
            self._cv.notify()
        return True

    def pop(self) -> TtsTask:
        with self._cv:
            while True:
                if self._high:
                    return self._high.popleft()
                if self._normal:
                    return self._normal.popleft()
                self._cv.wait()

class AudioQueue:
    def __init__(self, max_size: Optional[int] = None, on_evict: Optional[Callable[[TtsTask], None]] = None):
        self._max_size = max_size
        self._q: Deque[Tuple[AudioSegment, TtsTask]] = deque()
        self._cv = threading.Condition()
        self._on_evict = on_evict

    def push(self, audio: AudioSegment, task: TtsTask):
        with self._cv:
            cap = self._max_size if isinstance(self._max_size, int) and self._max_size > 0 else None
            if cap is not None and len(self._q) >= cap:
                evicted = self._q.popleft() if self._q else None
                if evicted and self._on_evict:
                    self._on_evict(evicted[1])
            self._q.append((audio, task))
            self._cv.notify()

    def pop(self) -> Tuple[AudioSegment, TtsTask]:
        with self._cv:
            while True:
                try:
                    return self._q.popleft()
                except Exception:
                    self._cv.wait()

class GradioClient:
    def __init__(self, base_url: str, ssl_verify: bool = False, timeout: int = 300):
        self.base_url = base_url if base_url.endswith("/") else (base_url + "/")
        self.ssl_verify = ssl_verify
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._fn_map: Dict[str, int] = {}

    async def ensure(self):
        if self._session is None:
            connector = aiohttp.TCPConnector(ssl=self.ssl_verify)
            self._session = aiohttp.ClientSession(timeout=self.timeout, connector=connector, headers={
                "User-Agent": "live_stream/tts_service"
            })
            await self._load_config()

    async def _load_config(self):
        assert self._session is not None
        url = self.base_url + "config"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            cfg = await resp.json()
            deps = cfg.get("dependencies") or []
            for i, dep in enumerate(deps):
                api_name = (dep or {}).get("api_name")
                if api_name:
                    self._fn_map[str(api_name).strip().lstrip("/")] = int((dep or {}).get("id", i))

    async def close(self):
        if self._session is not None:
            s = self._session
            self._session = None
            try:
                await s.close()
            except Exception:
                pass

    async def predict(self, api_name: str, *args: Any) -> Any:
        await self.ensure()
        assert self._session is not None
        fn = self._fn_map.get(api_name.strip().lstrip("/"))
        if fn is None:
            raise RuntimeError(f"API '{api_name}' not found in gradio config")
        url = self.base_url + "api/predict/"
        data = {
            "data": list(args),
            "fn_index": fn,
            "session_hash": str(int(time.time() * 1000))
        }
        async with self._session.post(url, json=data) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Gradio predict failed: {resp.status} {text[:200]}")
            j = await resp.json()
            if j.get("error"):
                raise RuntimeError(f"Gradio API error: {j.get('error')}")
            return j.get("data")

class TTSService:
    def __init__(self) -> None:
        self._cfg: Optional[LiveSettings] = None
        self._predict_q = PredictQueue()
        self._audio_q = AudioQueue()
        self._predict_thread = threading.Thread(target=self._predict_worker, daemon=True)
        self._play_thread = threading.Thread(target=self._play_worker, daemon=True)
        self._threads_started = False
        self._gradio_ready = threading.Event()
        self._status_listener: Optional[Callable[[Optional[int], Optional[str], str], None]] = None

    def init(self, settings: LiveSettings):
        self._cfg = settings
        if not self._threads_started:
            self._threads_started = True
            self._predict_thread.start()
            self._play_thread.start()

    def update_settings(self, settings: LiveSettings):
        self._cfg = settings

    def set_status_listener(self, fn: Optional[Callable[[Optional[int], Optional[str], str], None]]):
        self._status_listener = fn

    def _emit_status(self, room_id: Optional[int], key: Optional[str], status: str):
        try:
            logger.debug("TTS_STATUS room=%s key=%s status=%s", room_id, key, status)
        except Exception:
            pass
        try:
            if self._status_listener:
                self._status_listener(room_id, key, status)
        except Exception:
            pass

    def enqueue_text(self, text: str, priority: Priority = Priority.NORMAL, key: Optional[str] = None, room_id: Optional[int] = None) -> bool:
        if not self._cfg or not getattr(self._cfg, "tts_enabled", False):
            return False

        t = text or ""
        try:
            text_to_process = t
            rep_list = getattr(self._cfg, "replacement_rules", None) or []
            if isinstance(rep_list, list) and len(rep_list) > 0:
                for raw in rep_list:
                    try:
                        if isinstance(raw, ReplacementRule):
                            rule = raw
                        else:
                            rule = ReplacementRule(**(raw or {}))
                    except Exception:
                        continue
                    if not rule.key:
                        continue
                    flags = 0 if rule.match_case else re.IGNORECASE
                    pattern = rule.key if rule.use_regex else re.escape(rule.key)
                    if rule.whole_word:
                        pattern = r"\b" + pattern + r"\b"
                    try:
                        text_to_process = re.sub(pattern, rule.value, text_to_process, flags=flags)
                    except re.error:
                        continue
                t = text_to_process
        except Exception:
            pass

        max_q = getattr(self._cfg, "max_tts_queue_size", None) or getattr(self._cfg, "tts_max_queue_size", None)
        cap = int(max_q) if max_q is not None else None
        self._predict_q._max_size = cap
        self._audio_q._max_size = cap

        ok = self._predict_q.push(TtsTask(text=t, priority=priority, key=key, room_id=room_id))
        if ok:
            self._emit_status(room_id, key, "pending")
        else:
            if key is not None:
                self._emit_status(room_id, key, "cancelled")
        return ok

    def _predict_worker(self):
        logger.info("TTS predict worker started")
        client: Optional[GradioClient] = None
        selected_sig: Optional[Tuple[str, str, str, str]] = None

        def _new_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

        loop = _new_loop()

        while True:
            try:
                task = self._predict_q.pop()

                cfg = self._cfg
                if not cfg:
                    time.sleep(2.0)
                    continue

                base = (cfg.gradio_server_url or "").strip()
                if not base:
                    logger.warning("Gradio server URL not set; waiting...")
                    time.sleep(2.0)
                    continue

                if client is None or (isinstance(client, GradioClient) and client.base_url.rstrip("/") != (base if base.endswith("/") else (base + "/")).rstrip("/")):
                    client = GradioClient(base, ssl_verify=False)
                    selected_sig = None

                try:
                    sig = (base, str(cfg.sovits_model), str(cfg.gpt_model), str(cfg.text_lang))
                    if selected_sig != sig:
                        result = loop.run_until_complete(client.predict("/change_sovits_weights", cfg.sovits_model, cfg.text_lang, cfg.text_lang))
                        logger.info("Changed SoVITS weights: %s", result)
                        result = loop.run_until_complete(client.predict("/change_gpt_weights", cfg.gpt_model))
                        logger.info("Changed GPT weights: %s", result)
                        selected_sig = sig
                        self._gradio_ready.set()
                except Exception as e:
                    logger.warning("Failed to initialize Gradio client: %s", e)
                    client.close()
                    client = None
                    selected_sig = None
                    self._gradio_ready.clear()
                    time.sleep(2.0)
                    continue

                assert client is not None

                ref_audio_dict = None
                if isinstance(cfg.ref_audio_path, str) and cfg.ref_audio_path.strip():
                    ref_audio_dict = {
                        "path": cfg.ref_audio_path.strip(),
                        "orig_name": cfg.ref_audio_path.strip().split("/")[-1],
                        "meta": {"_type": "gradio.FileData"},
                    }

                ref_text = ""
                if isinstance(cfg.ref_text_path, str) and cfg.ref_text_path.strip():
                    try:
                        with open(cfg.ref_text_path.strip(), "r", encoding="utf-8") as f:
                            ref_text = f.read().strip()
                    except Exception:
                        ref_text = ""

                logger.info("Generating TTS: %s", task.text)
                try:
                    data = loop.run_until_complete(client.predict(
                        "/inference",
                        task.text,
                        cfg.text_lang,
                        ref_audio_dict,
                        [],
                        ref_text,
                        cfg.text_lang,
                        int(cfg.top_k),
                        float(cfg.top_p),
                        float(cfg.temperature),
                        cfg.text_split_method,
                        int(cfg.batch_size),
                        float(cfg.speed_factor),
                        bool(cfg.ref_text_free),
                        bool(cfg.split_bucket),
                        float(cfg.fragment_interval),
                        int(cfg.seed),
                        bool(cfg.keep_random),
                        bool(cfg.parallel_infer),
                        float(cfg.repetition_penalty),
                        str(cfg.sample_steps),
                        bool(cfg.super_sampling),
                    ))

                    audio_url = None
                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                        audio_url = data[0].get("url")

                    if not audio_url:
                        logger.error("Unexpected inference result: %s", repr(data)[:200])
                        continue

                    async def _download(url: str) -> bytes:
                        assert client is not None
                        assert client._session is not None
                        async with client._session.get(url) as resp:
                            resp.raise_for_status()
                            return await resp.read()

                    buf = loop.run_until_complete(_download(audio_url))
                    logger.info("Downloaded audio %.1f KB", len(buf) / 1024)

                    audio = AudioSegment.from_file(io.BytesIO(buf))
                    vol_db = float(getattr(cfg, "tts_volume", 0.0) or 0.0)
                    if vol_db > 24.0:
                        vol_db = 24.0
                    if vol_db < -60.0:
                        vol_db = -60.0
                    if vol_db != 0.0:
                        audio = audio.apply_gain(vol_db)

                    self._audio_q.push(audio, task)
                    logger.info("Enqueued audio: %s", task.text)
                except Exception as e:
                    logger.error("TTS inference error: %s", e)
                    time.sleep(1.0)

            except Exception as e:
                logger.error("Predict worker error: %s", e, exc_info=True)
                time.sleep(1.0)

    def _play_worker(self):
        logger.info("TTS play worker started")
        while True:
            try:
                audio, task = self._audio_q.pop()
                self._emit_status(getattr(task, "room_id", None), getattr(task, "key", None), "playing")
                logger.info("Playing: %s", task.text)

                buf = io.BytesIO()
                audio.export(buf, format="wav")
                data = buf.getvalue()

                try:
                    winsound.PlaySound(data, winsound.SND_MEMORY)
                except Exception as we:
                    logger.warning("winsound playback failed: %s; trying ffplay fallback", we)
                    try:
                        if shutil.which("ffplay"):
                            subprocess.run(
                                ["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", "-f", "wav", "-i", "pipe:0"],
                                input=data,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=True,
                            )
                        else:
                            raise
                    except Exception as fe:
                        logger.error("FFplay playback failed: %s", fe)

                self._emit_status(getattr(task, "room_id", None), getattr(task, "key", None), "done")
            except Exception as e:
                logger.error("Play worker error: %s", e, exc_info=True)

_service: Optional[TTSService] = None

def init(settings: LiveSettings):
    global _service
    if _service is None:
        _service = TTSService()
    _service.init(settings)

def update_settings(settings: LiveSettings):
    if _service is None:
        init(settings)
    else:
        _service.update_settings(settings)

def enqueue_text(text: str, priority: Priority = Priority.NORMAL, key: Optional[str] = None, room_id: Optional[int] = None) -> bool:
    if _service is None:
        return False
    return _service.enqueue_text(text, priority, key, room_id)

def set_status_listener(fn: Optional[Callable[[Optional[int], Optional[str], str], None]]):
    if _service is not None:
        _service.set_status_listener(fn)

def priority_from_event_type(event_type: str) -> Priority:
    high_priority_types = {"SUPER_CHAT_MESSAGE", "GUARD_BUY", "SEND_GIFT", "COMBO_SEND"}
    return Priority.HIGH if event_type in high_priority_types else Priority.NORMAL