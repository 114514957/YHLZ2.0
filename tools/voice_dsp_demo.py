"""Voice DSP demos (ledger 0421): NEKO input chain vs CX-O output conditioning.

Two subcommands, run against our own real clips so the effect is measurable:

  python tools/voice_dsp_demo.py neko <in16k.wav> [--out X.wav] [--transcribe] [--play]
      NEKO chain: 16k -> 48k -> RNNoise -> AGC -> Limiter -> 16k
      (params copied from N.E.K.O utils/audio_processor.py)

  python tools/voice_dsp_demo.py cxo <in.wav> [--out X.wav] [--mode peak|fixed] [--play]
      CX-O output conditioning: trim tail silence -> peak-normalize / fixed gain
      (params copied from CX-O docker/llm/cosyvoice_server.py)

Nothing here writes project data; --out defaults to cache/voice_clips/.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import os
import platform
import sys
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.voice_dsp import agc_int16 as _agc  # noqa: E402
from tools.voice_dsp import limiter_int16 as _limiter  # noqa: E402

_CLIPS = _PROJECT_ROOT / "cache" / "voice_clips"

# ---------------------------------------------------------------- NEKO params
# AGC/Limiter live in tools/voice_dsp.py (shared with the live chain, 0422).
RNNOISE_SAMPLE_RATE = 48_000
RNNOISE_FRAME_SIZE = 480

# ----------------------------------------------------------------- CX-O params
CXO_TARGET_PEAK = 0.85
CXO_FIXED_GAIN = 45.0
CXO_ABS_LIMIT = 0.98
CXO_SILENCE_PEAK = 0.0001
CXO_SILENCE_RATIO_THRESHOLD = 0.00316
CXO_TRIM_MIN_RETAIN_S = 0.05


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def _stats(label: str, x: np.ndarray, sr: int) -> dict:
    r = _rms(x)
    return {"label": label, "sr": sr, "dur": round(len(x) / sr, 2),
            "rms": round(r, 5), "dbfs": round(20 * np.log10(max(r, 1e-9)), 1),
            "peak": round(float(np.max(np.abs(x))), 4)}


# ------------------------------------------------------------------ RNNoise
_rnnoise_lib = None


def _load_rnnoise_native():
    """Load pyrnnoise's native DLL directly (N.E.K.O approach: no audiolab)."""
    global _rnnoise_lib
    if _rnnoise_lib is not None:
        return _rnnoise_lib
    lib_name = {"Windows": "rnnoise.dll", "Darwin": "librnnoise.dylib",
                "Linux": "librnnoise.so"}.get(platform.system())
    spec = importlib.util.find_spec("pyrnnoise")
    dll = None
    for d in (spec.submodule_search_locations or []) if spec else []:
        cand = os.path.join(d, lib_name)
        if os.path.isfile(cand):
            dll = cand
            break
    if dll is None:
        raise OSError(f"{lib_name} not found in pyrnnoise package")

    lib = ctypes.CDLL(dll)
    lib.rnnoise_create.argtypes = [ctypes.c_void_p]
    lib.rnnoise_create.restype = ctypes.c_void_p
    lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
    lib.rnnoise_destroy.restype = None
    lib.rnnoise_get_frame_size.argtypes = []
    lib.rnnoise_get_frame_size.restype = ctypes.c_int
    lib.rnnoise_process_frame.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float)]
    lib.rnnoise_process_frame.restype = ctypes.c_float

    class _Lib:
        FRAME_SIZE = lib.rnnoise_get_frame_size()
        create = staticmethod(lambda: lib.rnnoise_create(None))
        destroy = staticmethod(lib.rnnoise_destroy)

        @staticmethod
        def process_mono_frame(state, frame_int16):
            frame = frame_int16.astype(np.float32)
            n = len(frame)
            if n < _Lib.FRAME_SIZE:
                frame = np.pad(frame, (0, _Lib.FRAME_SIZE - n))
            ptr = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            prob = lib.rnnoise_process_frame(state, ptr, ptr)
            return np.clip(np.round(frame), -32768, 32767).astype(np.int16)[:n], float(prob)

    _rnnoise_lib = _Lib()
    return _rnnoise_lib


def _rnnoise(x48: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """float32 48k mono -> denoised float32 + per-frame speech probability."""
    lib = _load_rnnoise_native()
    fs = lib.FRAME_SIZE
    x16 = (np.clip(x48, -1.0, 1.0) * 32767.0).astype(np.int16)
    pad = (-len(x16)) % fs
    if pad:
        x16 = np.pad(x16, (0, pad))
    state = lib.create()
    if not state:
        raise RuntimeError("rnnoise_create() NULL")
    out = np.empty_like(x16)
    probs: list[float] = []
    try:
        for i in range(0, len(x16), fs):
            den, prob = lib.process_mono_frame(state, x16[i:i + fs])
            out[i:i + fs] = den
            probs.append(prob)
    finally:
        lib.destroy(state)
    if pad:
        out = out[:-pad]
    return out.astype(np.float32) / 32767.0, probs


def neko_chain(x16: np.ndarray, sr: int = 16_000, *, denoise: bool = True,
               agc: bool = True, limiter: bool = True) -> tuple[np.ndarray, list[float]]:
    """16k float -> (NEKO chain) -> 16k float + RNNoise probs."""
    import soxr

    x48 = soxr.resample(x16, sr, RNNOISE_SAMPLE_RATE, quality="HQ")
    probs: list[float] = []
    if denoise:
        den48, probs = _rnnoise(x48)
    else:
        den48 = x48
    den16 = (np.clip(den48, -1, 1) * 32767).astype(np.int16)
    out = _agc(den16) if agc else den16
    out = _limiter(out) if limiter else out
    out48 = out.astype(np.float32) / 32768.0
    out16 = soxr.resample(out48, RNNOISE_SAMPLE_RATE, sr, quality="HQ")
    return out16.astype(np.float32), probs


# ------------------------------------------------------------- CX-O conditioning
def _trim_tail_silence(x: np.ndarray, sr: int, block: int = 960) -> np.ndarray:
    """CX-O _trim_tail_silence: drop trailing blocks below peak*ratio (keep 0.05s)."""
    if len(x) == 0:
        return x
    peak = float(np.max(np.abs(x)))
    if peak < CXO_SILENCE_PEAK:
        return x
    thresh = peak * CXO_SILENCE_RATIO_THRESHOLD
    last = len(x)
    while last > block and float(np.max(np.abs(x[last - block:last]))) < thresh:
        last -= block
    keep = max(last, int(CXO_TRIM_MIN_RETAIN_S * sr))
    return x[:keep]


def cxo_condition(x: np.ndarray, sr: int, mode: str = "peak") -> np.ndarray:
    """CX-O TTS conditioning: tail trim -> peak normalize / fixed gain -> clamp."""
    x = _trim_tail_silence(np.asarray(x, dtype=np.float32), sr)
    peak = float(np.max(np.abs(x)))
    if peak >= CXO_SILENCE_PEAK:
        if mode == "fixed":
            x = x * CXO_FIXED_GAIN
        else:
            x = x * ((CXO_TARGET_PEAK) / peak)
    return np.clip(x, -CXO_ABS_LIMIT, CXO_ABS_LIMIT).astype(np.float32)


# ----------------------------------------------------------------------- main
def _transcribe(path: Path) -> str:
    import asyncio

    from backend.target_orchestrator import (
        _to_input_audio, build_openai_compatible_llm_turn,
    )

    llm = build_openai_compatible_llm_turn(
        base_url="http://127.0.0.1:8081/v1/chat/completions", api_key="",
        model="gemma-4-e4b", temperature=0.2, max_tokens=200,
        reasoning_effort="none")
    msgs = [
        {"role": "system", "content": "你是转写助手，只输出听到的话，不要解释。"},
        {"role": "user", "content": [_to_input_audio(str(path)),
                                     {"type": "text", "text": "转写这段音频，只输出内容。"}]},
    ]
    out = asyncio.run(llm(msgs, []))
    return str(out.get("content") or "").strip()[:120]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import soundfile as sf

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("neko", help="NEKO input chain demo")
    p1.add_argument("wav")
    p1.add_argument("--out", default="")
    p1.add_argument("--transcribe", action="store_true")
    p1.add_argument("--play", action="store_true")
    p1.add_argument("--no-denoise", action="store_true")
    p1.add_argument("--no-agc", action="store_true")
    p1.add_argument("--no-limiter", action="store_true")
    p2 = sub.add_parser("cxo", help="CX-O output conditioning demo")
    p2.add_argument("wav")
    p2.add_argument("--out", default="")
    p2.add_argument("--mode", choices=["peak", "fixed"], default="peak")
    p2.add_argument("--play", action="store_true")
    a = ap.parse_args()

    src = Path(a.wav)
    x, sr = sf.read(str(src), dtype="float32")
    if x.ndim > 1:
        x = x[:, 0]

    if a.cmd == "neko":
        y, probs = neko_chain(x, sr, denoise=not a.no_denoise,
                              agc=not a.no_agc, limiter=not a.no_limiter)
        out = Path(a.out) if a.out else _CLIPS / (src.stem + "_neko.wav")
        sf.write(str(out), y, sr, subtype="PCM_16")
        print("before:", _stats("in", x, sr))
        print("after :", _stats("out", y, sr))
        if probs:
            print(f"rnnoise: frames={len(probs)} mean_prob={np.mean(probs):.3f} "
                  f"speech_frames(>0.2)={int(np.sum(np.array(probs) > 0.2))}")
        if a.transcribe:
            print("transcribe before:", _transcribe(src))
            print("transcribe after :", _transcribe(out))
    else:
        y = cxo_condition(x, sr, a.mode)
        out = Path(a.out) if a.out else _CLIPS / (src.stem + f"_cxo_{a.mode}.wav")
        sf.write(str(out), y, sr, subtype="PCM_16")
        print("before:", _stats("in", x, sr))
        print("after :", _stats("out", y, sr))
        print(f"clip_count(>=0.98): {int(np.sum(np.abs(y) >= CXO_ABS_LIMIT - 1e-6))}")

    print("wav:", out)
    if a.play:
        from tools.voice_dialog_probe import _play_wav

        print("played:", _play_wav(Path(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
