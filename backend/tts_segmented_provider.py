"""Opt-in engineering text streaming over a commit-only persistent TTS port.

One logical turn -> serial child sessions on the SAME underlying worker. Child
DONE plus iterator drain and stop proof gate reuse. No speech-to-speech or native
text-stream capability is claimed. Playback still owns physical device state.
"""
from __future__ import annotations

from backend.voice_turn_trace import mark as trace_mark

import asyncio
import inspect
import time
from dataclasses import replace

from backend.tts_provider_port import (
    PCMFrameRepacker, TTSEventKind, TTSProviderEvent, TTSProviderPortError,
    TTSRequest, coerce_capabilities, coerce_provider_event,
)
from backend.voice_streaming import SpokenDeltaFilter, StreamingTextChunker, TextChunkerConfig

_END = object()


async def _invoke(method, *args):
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    if inspect.isasyncgenfunction(method):
        return method(*args)
    result = await asyncio.to_thread(method, *args)
    return await result if inspect.isawaitable(result) else result


def _next(iterator):
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


async def _events(session):
    source = await _invoke(session.audio_events)
    if hasattr(source, "__aiter__"):
        async for event in source:
            yield event
    else:
        iterator = iter(source)
        while True:
            more, event = await asyncio.to_thread(_next, iterator)
            if not more:
                return
            yield event


class SegmentedTTSProvider:
    def __init__(self, provider, *, config=None, segment_capacity=8,
                 pcm_frame_capacity=15, tick_ms=20, stop_timeout_s=1.0):
        if min(segment_capacity, pcm_frame_capacity, tick_ms, stop_timeout_s) <= 0:
            raise ValueError("segmented TTS bounds must be positive")
        self.provider = provider
        self.config = config or TextChunkerConfig()
        self.segment_capacity = segment_capacity
        self.pcm_frame_capacity = pcm_frame_capacity
        self.tick_ms = tick_ms
        self.stop_timeout_s = stop_timeout_s
        self._session = None

    def describe_capabilities(self):
        # Preserve honest acoustic/native text-stream declarations.
        return coerce_capabilities(self.provider.describe_capabilities())

    async def open(self, request):
        old = self._session
        if old is not None and not old.reusable:
            raise TTSProviderPortError("VOICE-TTS-SEGMENT-BUSY")
        self._session = _SegmentedSession(self, request)
        return self._session

    def health(self):
        return dict(self.provider.health(), segmented_text_stream=True,
                    segment_session=self._session.health() if self._session else None)

    def metrics(self):
        return dict(self.provider.metrics(), segmented_text_stream=True,
                    segment_metrics=self._session.metrics() if self._session else None)

    def __getattr__(self, name):
        # Existing lifecycle / strict playback-idle gate stays on the provider.
        return getattr(self.provider, name)


class _SegmentedSession:
    def __init__(self, owner, request):
        self.owner, self.request = owner, request
        self._segments = asyncio.Queue(maxsize=owner.segment_capacity)
        self._audio = asyncio.Queue(maxsize=owner.pcm_frame_capacity)
        self._chunker = StreamingTextChunker(owner.config)
        self._safe = []
        self._filter = SpokenDeltaFilter(self._safe.append)
        self._lock = asyncio.Lock()
        self._committed = self._cancelled = self._drained = False
        self._stop_confirmed = True
        self._active = None
        self._error = None
        self._segment_count = self._pcm_sequence = self._stale = 0
        self._first_pcm_ms = None
        self._started = time.monotonic()
        self._repacker = PCMFrameRepacker()
        self._runner = asyncio.create_task(self._run())
        self._timer = asyncio.create_task(self._tick())

    @property
    def reusable(self):
        return self._runner.done() and self._drained and self._stop_confirmed

    async def _enqueue(self, parts):
        for part in parts:
            if self._cancelled:
                return
            trace_mark("first_segment_ready")
            await self._segments.put(part)

    async def push_text(self, delta):
        if len(str(delta or "")) > 4096:
            raise TTSProviderPortError("VOICE-TTS-DELTA-TOO-LARGE")
        async with self._lock:
            if self._committed or self._cancelled or self._runner.done() or self._error:
                raise TTSProviderPortError("VOICE-TTS-SEGMENT-CLOSED")
            self._filter.push(delta)
            safe = list(self._safe)
            self._safe.clear()
            for value in safe:
                await self._enqueue(self._chunker.push(value))

    async def commit_text(self):
        async with self._lock:
            if self._committed or self._cancelled or self._runner.done() or self._error:
                raise TTSProviderPortError("VOICE-TTS-SEGMENT-CLOSED")
            self._filter.finish()
            await self._enqueue(self._chunker.finish())
            self._committed = True
            self._timer.cancel()
            await self._segments.put(_END)
        return True

    async def _tick(self):
        try:
            while not self._committed and not self._cancelled:
                await asyncio.sleep(self.owner.tick_ms / 1000)
                async with self._lock:
                    await self._enqueue(self._chunker.tick())
        except asyncio.CancelledError:
            pass

    def _event(self, kind, **kwargs):
        return TTSProviderEvent(kind, self.request.speech_id,
                                self.request.provider_epoch, **kwargs)

    async def _pcm(self, chunk):
        if self._cancelled:
            return
        trace_mark("first_pcm_produced")
        if self._first_pcm_ms is None:
            self._first_pcm_ms = round((time.monotonic() - self._started) * 1000, 2)
        await self._audio.put(self._event(
            TTSEventKind.PCM_CHUNK, sequence=self._pcm_sequence,
            chunk=replace(chunk, sequence=self._pcm_sequence)))
        self._pcm_sequence += 1

    async def _run(self):
        try:
            await self._audio.put(self._event(TTSEventKind.READY))
            while not self._cancelled:
                segment = await self._segments.get()
                if segment is _END or self._cancelled:
                    break
                child = replace(self.request,
                                speech_id=f"{self.request.speech_id}:seg:{self._segment_count}")
                self._active = await _invoke(self.owner.provider.open, child)
                self._stop_confirmed = False
                if self._cancelled:
                    await _invoke(self._active.cancel, "cancelled_during_open")
                else:
                    await _invoke(self._active.push_text, segment)
                    trace_mark("first_tts_submit")
                    await _invoke(self._active.commit_text)
                done = False
                child_error = None
                async for raw in _events(self._active):
                    event = coerce_provider_event(raw, request=child)
                    if event.speech_id != child.speech_id or event.provider_epoch != child.provider_epoch:
                        self._stale += 1
                        continue
                    if self._cancelled:
                        continue  # drain worker, never forward late PCM
                    if event.kind == TTSEventKind.ERROR.value:
                        child_error = TTSProviderPortError(event.code, event.detail)
                        await _invoke(self._active.cancel, "segment_error")
                        continue
                    if child_error is not None:
                        continue
                    if event.kind == TTSEventKind.DONE.value:
                        done = True
                    elif event.kind == TTSEventKind.PCM_CHUNK.value:
                        if done:
                            raise TTSProviderPortError("VOICE-TTS-PCM-AFTER-DONE")
                        for frame in self._repacker.feed(event.chunk):
                            await self._pcm(frame)
                self._stop_confirmed = bool(await _invoke(
                    self._active.wait_stopped, self.owner.stop_timeout_s))
                if not self._stop_confirmed:
                    raise TTSProviderPortError("VOICE-TTS-SEGMENT-STOP-UNCONFIRMED")
                self._active = None
                if child_error is not None:
                    raise child_error
                if not done and not self._cancelled:
                    raise TTSProviderPortError("VOICE-TTS-SEGMENT-NO-DONE")
                self._segment_count += 1
            if not self._cancelled:
                for frame in self._repacker.flush():
                    await self._pcm(frame)
                await self._audio.put(self._event(TTSEventKind.PCM_STREAM_END))
                await self._audio.put(self._event(TTSEventKind.DONE))
        except Exception as exc:
            self._error = getattr(exc, "code", "VOICE-TTS-SEGMENT-ERROR")
            if self._active is not None:
                try:
                    await _invoke(self._active.cancel, "segment_error")
                    self._stop_confirmed = bool(await _invoke(
                        self._active.wait_stopped, self.owner.stop_timeout_s))
                except Exception:
                    self._stop_confirmed = False
            if not self._cancelled:
                await self._audio.put(self._event(TTSEventKind.ERROR, code=self._error,
                                                  detail=type(exc).__name__))
        finally:
            self._timer.cancel()
            if self._cancelled:
                self._clear(self._audio)
                self._audio.put_nowait(_END)
            else:
                await self._audio.put(_END)

    async def audio_events(self):
        try:
            while True:
                event = await self._audio.get()
                if event is _END:
                    self._drained = True
                    return
                if not self._cancelled:
                    yield event
        finally:
            if self._cancelled:
                self._clear(self._audio)
                self._drained = True

    @staticmethod
    def _clear(queue):
        while not queue.empty():
            queue.get_nowait()

    async def cancel(self, reason="cancelled"):
        self._cancelled = True
        self._filter.cancel()
        self._chunker.cancel()
        self._timer.cancel()
        self._clear(self._segments)
        self._segments.put_nowait(_END)
        self._clear(self._audio)
        if self._active is not None:
            await _invoke(self._active.cancel, reason)
        return True  # request accepted; wait_stopped supplies proof

    async def wait_stopped(self, timeout_s):
        try:
            await asyncio.wait_for(asyncio.shield(self._runner), max(0.001, timeout_s))
        except asyncio.TimeoutError:
            return False
        return self._stop_confirmed

    def health(self):
        return {"state": "stopping" if self._cancelled and not self._runner.done()
                else "stopped" if self._runner.done() else "streaming",
                "speech_id": self.request.speech_id,
                "provider_epoch": self.request.provider_epoch, "error_code": self._error}

    def metrics(self):
        return {"segments_completed": self._segment_count,
                "segment_queue_depth": self._segments.qsize(),
                "pcm_queue_depth": self._audio.qsize(),
                "pcm_queue_bound_ms": self.owner.pcm_frame_capacity * 20,
                "first_pcm_ms": self._first_pcm_ms, "stale_event_count": self._stale,
                "cancelled": self._cancelled, "stop_confirmed": self._stop_confirmed,
                "error_code": self._error}
