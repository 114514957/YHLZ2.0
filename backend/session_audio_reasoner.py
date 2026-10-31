"""Stream the existing persona/memory session into the single Target lease."""
from __future__ import annotations
import asyncio
from backend.llm_provider_port import LLMProviderError
from backend.voice_turn_trace import mark

class SessionAudioReasoner:
    def __init__(self, session_factory, text_reasoner, *, tools_enabled=False):
        self.session_factory = session_factory
        self.text_reasoner = text_reasoner
        self.tools_enabled = tools_enabled

    async def generate(self, text, signal):
        async for delta in self.text_reasoner.generate(text, signal):
            yield delta

    async def generate_audio(self, text, audio, signal):
        session = self.session_factory()
        queue = asyncio.Queue(maxsize=64)
        active = True
        emitted = False
        def on_delta(delta):
            nonlocal emitted
            if not active or signal.is_cancelled() or not delta:
                return
            if len(delta) > 4096:
                raise LLMProviderError("VOICE-DELTA-TOO-LARGE")
            try:
                queue.put_nowait(str(delta))
            except asyncio.QueueFull as exc:
                raise LLMProviderError("VOICE-CONTENT-BACKPRESSURE") from exc
            emitted = True
            mark("llm_first_content")
        async def produce():
            mark("session_start")
            result = await session.run_turn(text, audio=audio, on_delta=on_delta,
                                           voice_tools_enabled=self.tools_enabled)
            # A non-streaming injected test factory may return only an answer.
            if not emitted and not signal.is_cancelled():
                on_delta(str(result.get("answer") or ""))
            mark("session_done")
        producer = asyncio.create_task(produce())
        # A consumer may return early before async-generator finalization.
        # Kernel invalidation must stop the session request immediately.
        callback = getattr(signal, "add_cancel_callback", None)
        if callable(callback):
            callback(producer.cancel)
        getter = None
        try:
            while True:
                if producer.done():
                    await producer  # never deliver queued content after a failure
                    if queue.empty():
                        break
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait((producer, getter), return_when=asyncio.FIRST_COMPLETED)
                if producer in done:
                    await producer
                    if not getter.done() and queue.empty():
                        break
                if getter.done():
                    value = getter.result()
                else:
                    value = await getter
                if signal.is_cancelled():
                    return
                yield value
        finally:
            active = False
            if getter is not None and not getter.done():
                getter.cancel()
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, *([getter] if getter is not None else []), return_exceptions=True)
