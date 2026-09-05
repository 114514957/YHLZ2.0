"""Always-on wake-word dialog loop (ledger 0158).

The 3.3M zipformer KWS model fails on this machine's weak mic signal
(evidence: user speech RMS ~0.002, TTS echo 0.008 — neither triggers KWS at
any gain, while FunASR transcribes the same audio reliably).  Wake is therefore
implemented as: VAD-gated FunASR streaming + keyword match in the transcript
(元亨).  Wake-seen then keeps capturing until 0.6 s of silence → full heard
utterance for the conversation layer.  Hit-to-stop semantics everywhere.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WAKE_WORDS = ("元亨",)
VOICEPRINT_FILE = _PROJECT_ROOT / "cache" / "voiceprint" / "user_embedding.npy"


class VoiceprintDialogLoop:
    """Voiceprint-based always-on wake (ledger 0159): user's voice triggers.

    Speech windows (VAD-gated) are embedded by cam++ and compared against the
    enrolled user vector (cosine).  Background (video/other voices) should not
    trigger.  After wake, capture continues until 0.6 s silence -> heard text
    via FunASR streaming (same partial-accumulation discipline).
    """

    def __init__(
        self,
        *,
        cap_gain: float = 1.0,
        device: int = 1,
        duration_s: float = 40.0,
        threshold: float = 0.3,
        embedding_path: Path = VOICEPRINT_FILE,
        sleep_after_wake_s: float = 3.0,
    ) -> None:
        self.cap_gain = float(cap_gain)
        self.device = int(device)
        self.duration_s = float(duration_s)
        self.threshold = float(threshold)
        self.embedding_path = Path(embedding_path)
        self.sleep_after_wake_s = float(sleep_after_wake_s)
        self._sv_model: Any = None
        self._user_vec: Optional[np.ndarray] = None

    def _ensure_sv(self):
        if self._sv_model is None:
            from funasr import AutoModel

            self._sv_model = AutoModel(
                model=str(_PROJECT_ROOT / "models" / "voice" / "sv" / "campplus"),
                device="cpu", disable_update=True, disable_pbar=True,
                disable_log=True,
            )
        if self._user_vec is None:
            if not self.embedding_path.exists():
                raise FileNotFoundError(
                    f"voiceprint missing: {self.embedding_path} (run voiceprint_enroll)")
            self._user_vec = np.load(str(self.embedding_path)).reshape(-1)
        return self._sv_model

    def _similarity(self, audio: np.ndarray) -> float:
        model = self._ensure_sv()
        r = model.generate(input=audio)
        e = np.asarray(r[0]["spk_embedding"], dtype="float32").reshape(-1)
        e = e / (np.linalg.norm(e) + 1e-9)
        return float(np.dot(e, self._user_vec))

    def run(self, *, on_wake=None, on_verify=None) -> dict:
        import sounddevice as sd

        from backend.target_chain import CancellationSignal
        from backend.target_funasr_asr import (
            FunasrASRConfig,
            FunasrOnlineASRProvider,
        )
        from backend.target_vad import TargetVADProvider

        model_dir = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"
        vad = TargetVADProvider()
        asr = FunasrOnlineASRProvider(FunasrASRConfig(model_dir=model_dir))
        vad.start()
        asr.start()
        sig = CancellationSignal()
        asr.open_stream("vp", 1, 16000, 1, sig)

        t0 = time.time()
        accum = ""
        last_grow = 0.0
        tail_silent = 0
        wake_ts = 0.0
        pending: list[np.ndarray] = []  # voiced frames awaiting embedding
        pending_silent = 0
        total = int(self.duration_s * 10)
        with sd.InputStream(device=self.device, samplerate=16000, channels=1,
                            dtype="float32", blocksize=1600) as inp:
            for _ in range(total):
                if time.time() - t0 > self.duration_s:
                    break
                data, _ = inp.read(1600)
                mono = np.asarray(data[:, 0] if data.ndim > 1 else data,
                                  dtype="float32")
                if self.cap_gain != 1.0:
                    mono = np.clip(mono * self.cap_gain, -1.0, 1.0).astype("float32")
                speech = bool(vad.detect_speech(mono, 16000))
                # ASR runs always on speech (warm, captures wake phrase too)
                if speech:
                    for upd in asr.push_audio("vp", mono, 16000, sig):
                        if upd.text and len(upd.text) > len(accum):
                            accum = upd.text
                            last_grow = time.time()
                if not wake_ts:
                    if speech:
                        pending.append(mono)
                        pending_silent = 0
                        if len(pending) >= 10:  # >= 1.0 s voiced -> verify (0.4 s too noisy)
                            win = np.concatenate(pending)
                            try:
                                sim = self._similarity(win)
                            except Exception:
                                sim = 0.0
                            if on_verify is not None:
                                try:
                                    on_verify(round(sim, 3))
                                except Exception:
                                    pass
                            if sim >= self.threshold:
                                wake_ts = time.time()
                                if on_wake is not None:
                                    try:
                                        on_wake(round(sim, 3),
                                                round(time.time() - t0, 2))
                                    except Exception:
                                        pass
                            pending = []
                    else:
                        pending_silent += 1
                        if pending_silent >= 6:
                            pending = []
                            pending_silent = 0
                    tail_silent = 0
                    continue
                tail_silent = tail_silent + 1 if not speech else 0
                # post-wake: finish on 2 s silence after heard content
                if accum and tail_silent >= 20 and time.time() - last_grow > 2.0:
                    break
                # auto-sleep: woken (false positive?) but no speech for N s -> back to sleep
                if wake_ts and time.time() - wake_ts > self.sleep_after_wake_s:
                    wake_ts = 0.0
                    accum = ""
                    tail_silent = 0
                    pending = []
                    pending_silent = 0
                    last_grow = 0.0
        asr.finish_stream("vp", sig)
        vad.stop("done")
        asr.stop("done")
        return {
            "wake": bool(wake_ts),
            "similarity": None,
            "heard": accum.strip(),
            "duration_s": round(time.time() - t0, 2),
        }


class WakeDialogLoop:
    """Always-on listening; returns after wake word + complete utterance."""

    def __init__(
        self,
        *,
        wake_words: Sequence[str] = DEFAULT_WAKE_WORDS,
        cap_gain: float = 6.0,
        device: int = 1,
        duration_s: float = 30.0,
    ) -> None:
        self.wake_words = tuple(wake_words) or DEFAULT_WAKE_WORDS
        self.cap_gain = float(cap_gain)
        self.device = int(device)
        self.duration_s = float(duration_s)

    @staticmethod
    def _strip_wake(heard: str, wake: str) -> str:
        text = str(heard or "")
        for w in (wake, wake + "，", wake + ","):
            if text.startswith(w):
                return text[len(w):].lstrip("，,。. ")
        return text

    def run(self, *, on_wake=None) -> dict:
        import sounddevice as sd

        from backend.target_chain import CancellationSignal
        from backend.target_funasr_asr import (
            FunasrASRConfig,
            FunasrOnlineASRProvider,
        )
        from backend.streaming_asr_bridge import ASRStreamUpdateKind
        from backend.target_vad import TargetVADProvider

        model_dir = _PROJECT_ROOT / "models" / "voice" / "asr" / "paraformer-zh-streaming"
        vad = TargetVADProvider()
        asr = FunasrOnlineASRProvider(FunasrASRConfig(model_dir=model_dir))
        vad.start()
        asr.start()
        sig = CancellationSignal()
        asr.open_stream("wake", 1, 16000, 1, sig)

        t0 = time.time()
        accum = ""
        wake_seen = ""
        last_grow = 0.0
        tail_silent = 0
        total = int(self.duration_s * 10)
        with sd.InputStream(device=self.device, samplerate=16000, channels=1,
                            dtype="float32", blocksize=1600) as inp:
            for _ in range(total):
                if time.time() - t0 > self.duration_s:
                    break
                data, _ = inp.read(1600)
                mono = np.asarray(data[:, 0] if data.ndim > 1 else data,
                                  dtype="float32")
                if self.cap_gain != 1.0:
                    mono = np.clip(mono * self.cap_gain, -1.0, 1.0).astype("float32")
                speech = bool(vad.detect_speech(mono, 16000))
                if not speech and not wake_seen:
                    continue  # idle: no speech, no ASR cost
                for upd in asr.push_audio("wake", mono, 16000, sig):
                    if upd.text and len(upd.text) > len(accum):
                        accum = upd.text
                        last_grow = time.time()
                if not wake_seen:
                    for w in self.wake_words:
                        if w in accum:
                            wake_seen = w
                            if on_wake is not None:
                                try:
                                    on_wake(w, round(time.time() - t0, 2))
                                except Exception:
                                    pass
                            break
                tail_silent = tail_silent + 1 if not speech else 0
                if wake_seen and accum and tail_silent >= 6 \
                        and time.time() - last_grow > 0.6:
                    break
        asr.finish_stream("wake", sig)
        stream_result = ""
        try:
            stream_result = accum
        except Exception:
            pass
        vad.stop("done")
        asr.stop("done")
        heard = stream_result or accum
        text = self._strip_wake(heard, wake_seen) if wake_seen else heard
        return {
            "wake": wake_seen,
            "heard": text.strip(),
            "raw": accum,
            "duration_s": round(time.time() - t0, 2),
        }
