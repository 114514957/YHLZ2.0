#!/usr/bin/env python3
"""Mix a converted lead with backing (和声) and bgm (伴奏) into the final cover.

Usage:
  wsl_mix3.py <lead_converted.wav> <backing.wav> <bgm.wav> <out.wav>
              [--lead-gain 1.0] [--backing-gain 0.85] [--bgm-gain 0.85]
              [--peak 0.99]

All inputs are resampled to the bgm sample rate (or 44.1k), mono is doubled,
shorter tracks are zero-padded. Output is peak-limited to --peak.
"""
from __future__ import annotations

import argparse
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lead")
    ap.add_argument("backing")
    ap.add_argument("bgm")
    ap.add_argument("out")
    ap.add_argument("--lead-gain", type=float, default=1.0)
    ap.add_argument("--backing-gain", type=float, default=0.85)
    ap.add_argument("--bgm-gain", type=float, default=0.85)
    ap.add_argument("--peak", type=float, default=0.99)
    ap.add_argument("--target-sr", type=int, default=44100)
    args = ap.parse_args()

    import librosa
    import numpy as np
    import soundfile as sf

    sr = args.target_sr

    def load(path: str) -> np.ndarray:
        wav, in_sr = sf.read(path, dtype="float32", always_2d=True)
        if in_sr != sr:
            wav = librosa.resample(wav, orig_sr=in_sr, target_sr=sr,
                                   axis=0)
        if wav.shape[1] == 1:
            wav = np.repeat(wav, 2, axis=1)
        return wav[:, :2]

    lead = load(args.lead) * args.lead_gain
    backing = load(args.backing) * args.backing_gain
    bgm = load(args.bgm) * args.bgm_gain
    n = max(len(lead), len(backing), len(bgm))
    mix = np.zeros((n, 2), dtype=np.float32)
    for track in (lead, backing, bgm):
        mix[:len(track)] += track
    peak = float(np.max(np.abs(mix)) + 1e-9)
    info = {"peak_before": round(peak, 3), "peak_after": args.peak}
    if peak > args.peak:
        mix *= args.peak / peak
    sf.write(args.out, mix, sr, subtype="PCM_16")
    info.update({"out": args.out, "duration_s": round(n / sr, 2), "sr": sr})
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
