"""VAD segment -> in-memory WAV -> existing Target lease, without ASR text.

Explicit native-capture mode is an active conversation (no lexical wake word).
The existing media route/AEC admission gate remains authoritative.
"""
from __future__ import annotations
import asyncio
import base64
import io
import wave
import numpy as np
from backend.asr_bridge import ASRBridge, ASREventKind, TranscriptResult
from backend.speech_segment import SpeechSegmentAssembler

class NativeClipEncoder:
    def transcribe(self, segment, signal):
        # Port compatibility only: this produces audio, NEVER a transcript.
        if signal.is_cancelled():
            raise asyncio.CancelledError()
        if segment.sample_rate != 16000 or segment.channels != 1:
            raise ValueError("NATIVE-AUDIO-REQUIRES-16K-MONO")
        blocks = []
        count = 0
        for frame in segment.frames:
            samples = frame.samples
            if isinstance(samples, (bytes, bytearray, memoryview)):
                if len(samples) % 2:
                    raise ValueError("NATIVE-AUDIO-ODD-PCM")
                block = np.frombuffer(samples, dtype="<i2")
            else:
                values = np.asarray(samples)
                if values.ndim > 2 or (values.ndim == 2 and values.shape[1] != 1):
                    raise ValueError("NATIVE-AUDIO-CHANNELS")
                values = values.reshape(-1)
                if not np.all(np.isfinite(values)):
                    raise ValueError("NATIVE-AUDIO-NONFINITE")
                if np.issubdtype(values.dtype, np.integer):
                    block = np.clip(values, -32768, 32767).astype("<i2")
                else:
                    block = (np.clip(values, -1, 1) * 32767).astype("<i2")
            count += len(block)
            if count > 16000 * 30:
                raise ValueError("NATIVE-AUDIO-TOO-LONG")
            blocks.append(block)
        if not count:
            raise ValueError("NATIVE-AUDIO-EMPTY")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            for block in blocks:
                wav.writeframes(block.tobytes())
        return "data:audio/wav;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    def abort(self, reason="cancelled"):
        pass  # synchronous, bounded conversion; no running inference/device

    def wait_stopped(self, timeout_s=0):
        return True  # local encoder only, NOT proof of LLM/TTS/GPU stop

    def health(self):
        return {"available": True, "provider": "native_wav_encoder", "asr_model": False}

class NativeAudioIngress(ASRBridge):
    def __init__(self, *, chain, submit_audio, cancel_timeout_s=8.0, timeout_s=300.0):
        if not callable(submit_audio):
            raise TypeError("submit_audio must be callable")
        # VAD already has end hysteresis. Do not add another fixed silence wait.
        # Avoid ASRBridge's 100-frame cap cutting 20ms capture into 2s requests.
        assembler = SpeechSegmentAssembler(max_frames=1500, max_duration_ms=30000,
                                           min_duration_ms=120)
        super().__init__(asr=NativeClipEncoder(), chain=chain, assembler=assembler,
                         timeout_s=timeout_s, cancel_timeout_s=cancel_timeout_s)
        self.submit_audio = submit_audio

    async def _run_segment(self, segment, signal):
        self._emit(ASREventKind.STARTED, segment, payload={"input_mode":"native_audio"})
        try:
            clip = self.asr.transcribe(segment, signal)
            if signal.is_cancelled() or not self._is_current_task(segment.segment_id, segment.generation):
                self._stale += 1
                result = TranscriptResult(segment.segment_id, segment.generation, "", "stale")
                self._last_result = result
                self._emit(ASREventKind.STALE, segment)
                return result
            outcome = await asyncio.wait_for(
                self.submit_audio([clip], text="", source="microphone_native"),
                timeout=self.timeout_s)
            result = TranscriptResult(segment.segment_id, segment.generation, "", outcome.status,
                                      error_code=outcome.error_code)
            self._last_result = result
            if outcome.status == "completed":
                self._completed += 1
                self._emit(ASREventKind.COMPLETED, segment, payload={"input_mode":"native_audio"})
            else:
                self._failed += 1
                self._emit(ASREventKind.ERROR, segment, payload={"code":outcome.error_code or "NATIVE-AUDIO-TURN-FAILED"})
            return result
        except asyncio.TimeoutError:
            self._failed += 1
            self._timeouts += 1
            result = TranscriptResult(segment.segment_id, segment.generation, "", "failed",
                                      error_code="NATIVE-AUDIO-TIMEOUT")
            self._last_result = result
            self._emit(ASREventKind.ERROR, segment, payload={"code": result.error_code})
            return result
        except asyncio.CancelledError:
            self._cancelled += 1
            self._emit(ASREventKind.CANCELLED, segment)
            raise
        except Exception as exc:
            self._failed += 1
            result = TranscriptResult(segment.segment_id, segment.generation, "", "failed",
                                      error_code="NATIVE-AUDIO-FAILED")
            self._last_result = result
            self._emit(ASREventKind.ERROR, segment, payload={"code":result.error_code,"detail":type(exc).__name__})
            return result
        finally:
            signal.mark_done()
            await self._confirm_cancel_stop(segment, signal)
            if self._active_segment_id == segment.segment_id:
                self._active_task = self._active_signal = self._active_segment = None
                self._active_segment_id = None

    def snapshot(self):
        return {**super().snapshot(), "input_mode": "native_audio",
                "wake_policy": "explicit_active_session",
                "stop_evidence_scope": "encoder_only_not_llm_tts",
                "ports": {"asr_cancel_supported": False, "asr_stop_observable": False}}
