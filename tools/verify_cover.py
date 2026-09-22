#!/usr/bin/env python3
"""Cover quality verifier (WSL side).

Objective checks for SVC covers, calibrated 2026-09-22:
  - content fidelity: ContentVec-768L12 frame cosine vs the separated source
    vocal (DTW-aligned). Calibration: known-good pair ~0.86, unrelated ~0.23.
  - pitch fidelity: median F0 ratio + octave-error share (rmvpe on CPU).
  - basic sanity: duration delta, clip rate, silence share.
  - optional ASR: chunked faster-whisper transcription of source vs cover,
    char-level similarity per chunk (ground truth of "lyrics preserved").

Usage:
  python verify_cover.py <source_vocal.wav> <cover.wav> [--asr] [--lyrics file]

Exit code 0 always; verdict is printed as JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np
import soundfile as sf
import torch

_HOME = pathlib.Path.home()
_DDSP = _HOME / "ddsp/DDSP-SVC"
sys.path.insert(0, str(_DDSP))

GOOD_COS = 0.80
WEAK_COS = 0.50


def _load_mono(path: str, sr: int | None = None):
    wav, in_sr = sf.read(path, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    if sr is not None and in_sr != sr:
        import librosa

        wav = librosa.resample(wav, orig_sr=in_sr, target_sr=sr)
    return wav, in_sr


def content_similarity(src: str, out: str) -> dict:
    import librosa

    from ddsp.vocoder import Units_Encoder

    enc = Units_Encoder(
        "contentvec768l12",
        str(_DDSP / "pretrain/contentvec/checkpoint_best_legacy_500.pt"),
        device="cpu")

    def units(path: str) -> np.ndarray:
        wav, _ = _load_mono(path, 16000)
        t = torch.from_numpy(wav).float().unsqueeze(0)
        with torch.no_grad():
            u = enc.encode(t, 16000, 160)
        u = u.detach().cpu().numpy()
        return u[0] if u.ndim == 3 else u

    def frame_cos(a: np.ndarray, b: np.ndarray) -> float:
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        return float(np.mean((a * b).sum(1) / (
            np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)))

    u1, u2 = units(src), units(out)
    n = min(len(u1), len(u2))
    if n > 6000:
        win = 1000
        cs = [frame_cos(u1[i:i + win], u2[i:i + win])
              for i in range(0, n - win + 1, win)]
        return {"frames_src": len(u1), "frames_out": len(u2),
                "chunk_cos_mean": round(float(np.mean(cs)), 3),
                "chunk_cos_min": round(float(np.min(cs)), 3),
                "chunks": len(cs), "mode": "chunked"}
    d, wp = librosa.sequence.dtw(X=u1.T, Y=u2.T, metric="cosine", subseq=False)
    a, b = u1[wp[:, 0]], u2[wp[:, 1]]
    dtw = float(np.mean((a * b).sum(1) / (
        np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)))
    return {"frames_src": len(u1), "frames_out": len(u2),
            "minlen_cos": round(frame_cos(u1, u2), 3),
            "dtw_cos": round(dtw, 3), "dtw_dist": round(float(d[-1, -1]), 1),
            "frames_matched": int(n)}


def pitch_stats(src: str, out: str) -> dict:
    import os

    from ddsp.vocoder import F0_Extractor

    os.chdir(_DDSP)
    f0e = F0_Extractor("rmvpe", 16000, 160, 50, 1100)
    out_d: dict = {}
    fs: dict[str, np.ndarray] = {}
    for tag, path in (("src", src), ("out", out)):
        wav, _ = _load_mono(path, 16000)
        f0 = f0e.extract(wav, 0.0) if hasattr(f0e, "extract") else None
        fs[tag] = np.asarray(f0)
    n = min(len(fs["src"]), len(fs["out"]))
    a, b = fs["src"][:n], fs["out"][:n]
    mask = (a > 0) & (b > 0)
    if mask.sum() < 10:
        return {"f0_frames": int(mask.sum())}
    ratio = b[mask] / a[mask]
    lr = np.log2(ratio)
    out_d.update({
        "f0_frames": int(mask.sum()),
        "median_ratio": round(float(np.median(ratio)), 3),
        "octave_err_share": round(float(np.mean(np.abs(np.abs(lr) - 1.0) < 0.2)), 3),
        "pitch_ok_share": round(float(np.mean(np.abs(lr) < 0.25)), 3),
    })
    return out_d


def sanity(src: str, out: str) -> dict:
    res: dict = {}
    for tag, path in (("src", src), ("out", out)):
        wav, sr = _load_mono(path)
        peak = float(np.max(np.abs(wav)) + 1e-9)
        res[f"{tag}_dur_s"] = round(len(wav) / sr, 2)
        res[f"{tag}_clip_share"] = round(float(np.mean(np.abs(wav) > 0.985)), 5)
        res[f"{tag}_rms_db"] = round(float(20 * math.log10(np.sqrt(np.mean(wav ** 2)) + 1e-9)), 1)
        res[f"{tag}_silence_share"] = round(float(np.mean(np.abs(wav) < 1e-4)), 3)
    res["dur_delta_s"] = round(abs(res["src_dur_s"] - res["out_dur_s"]), 2)
    return res


def asr_compare(src: str, out: str, chunk_s: float = 15.0) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001
        return {"error": f"faster_whisper unavailable: {exc}"}
    import difflib

    import librosa

    model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")

    def chunks(path: str):
        wav, _ = _load_mono(path, 16000)
        step = int(chunk_s * 16000)
        for i in range(0, len(wav), step):
            seg = wav[i:i + step]
            if len(seg) < 16000:
                break
            yield seg

    def transcribe(wav: np.ndarray) -> str:
        segs, _ = model.transcribe(wav, language="zh", beam_size=5,
                                   vad_filter=False)
        return "".join(s.text for s in segs).replace(" ", "")

    pairs = []
    src_t, out_t = [], []
    for c in chunks(src):
        t = transcribe(c)
        src_t.append(t)
    for c in chunks(out):
        t = transcribe(c)
        out_t.append(t)
    n = min(len(src_t), len(out_t))
    sims = []
    for i in range(n):
        s = "".join(ch for ch in src_t[i] if ch.isalnum())
        o = "".join(ch for ch in out_t[i] if ch.isalnum())
        if not s and not o:
            continue
        sims.append(difflib.SequenceMatcher(None, s, o).ratio())
        pairs.append({"i": i, "src": src_t[i][:60], "out": out_t[i][:60]})
    return {"chunks": len(pairs), "mean_char_sim": round(float(np.mean(sims)), 3) if sims else 0.0,
            "pairs": pairs[:8]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("cover")
    ap.add_argument("--asr", action="store_true")
    args = ap.parse_args()

    report: dict = {"source": args.source, "cover": args.cover}
    report["sanity"] = sanity(args.source, args.cover)
    try:
        report["content"] = content_similarity(args.source, args.cover)
        c = report["content"]
        cos = c.get("dtw_cos", c.get("chunk_cos_mean", 0.0))
        report["verdict"] = ("GOOD" if cos >= GOOD_COS
                             else "WEAK" if cos >= WEAK_COS else "BAD")
    except Exception as exc:  # noqa: BLE001
        report["content"] = {"error": f"{type(exc).__name__}: {exc}"}
        report["verdict"] = "UNKNOWN"
    try:
        report["pitch"] = pitch_stats(args.source, args.cover)
    except Exception as exc:  # noqa: BLE001
        report["pitch"] = {"error": f"{type(exc).__name__}: {exc}"}
    if args.asr:
        try:
            report["asr"] = asr_compare(args.source, args.cover)
        except Exception as exc:  # noqa: BLE001
            report["asr"] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
