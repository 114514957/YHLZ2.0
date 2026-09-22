#!/usr/bin/env python3
"""ASR check for covers: transcribe a cover (optionally biased by the lyrics)
and score it against the ground-truth lyrics text.

Usage:
  cover_asr_check.py <cover.wav> --lyrics lyrics.txt [--src-vocal src.wav]
                     [--model-dir /path/to/fw-snapshot] [--out report.json]
"""
from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import re
import sys

import numpy as np
import soundfile as sf


def clean(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cover")
    ap.add_argument("--lyrics")
    ap.add_argument("--src-vocal")
    ap.add_argument("--model-dir", default="")
    ap.add_argument("--out")
    ap.add_argument("--chunk", type=float, default=0.0,
                    help="chunk seconds; 0 = whole file")
    ap.add_argument("--no-context", action="store_true",
                    help="disable condition_on_previous_text (anti-hallucination)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    model_dir = args.model_dir or str(pathlib.Path.home() /
        ".cache/huggingface/hub/models--Systran--faster-whisper-large-v3/snapshots")
    if not pathlib.Path(model_dir).is_dir():
        print("model dir missing:", model_dir)
        return 2
    if not (pathlib.Path(model_dir) / "model.bin").exists():
        subs = [p for p in pathlib.Path(model_dir).iterdir() if p.is_dir()]
        model_dir = str(subs[0]) if subs else model_dir
    model = WhisperModel(model_dir, device="cuda", compute_type="int8_float16")

    lyrics = ""
    if args.lyrics:
        lyrics = pathlib.Path(args.lyrics).read_text(encoding="utf-8")
    init_prompt = clean(lyrics)[:180] if lyrics else None

    def load(path: str) -> np.ndarray:
        wav, sr = sf.read(path, dtype="float32", always_2d=True)
        wav = wav.mean(1)
        if sr != 16000:
            import librosa

            wav = librosa.resample(wav, orig_sr=sr, target_sr=16000)
        return wav

    def transcribe(wav: np.ndarray) -> str:
        segs, _ = model.transcribe(wav, language="zh", beam_size=5,
                                   condition_on_previous_text=not args.no_context,
                                   initial_prompt=init_prompt)
        return "".join(s.text for s in segs)

    rep: dict = {"cover": args.cover, "model_dir": model_dir}
    wav = load(args.cover)
    if args.chunk and args.chunk > 0:
        step = int(args.chunk * 16000)
        chunks = []
        for i in range(0, len(wav), step):
            seg = wav[i:i + step]
            if len(seg) < 16000:
                break
            chunks.append(transcribe(seg))
        text = "".join(chunks)
        rep["chunks"] = chunks
    else:
        text = transcribe(wav)
    rep["asr_text"] = text
    if lyrics:
        c, l = clean(text), clean(lyrics)
        rep["lyrics_chars"] = len(l)
        rep["asr_chars"] = len(c)
        rep["similarity"] = round(difflib.SequenceMatcher(None, c, l).ratio(), 3)
        rep["similarity_local"] = round(difflib.SequenceMatcher(
            None, c, l).ratio() * 1.0, 3)
        rep["lyrics_head"] = lyrics.strip().splitlines()[:2]
    if args.src_vocal:
        src_text = transcribe(load(args.src_vocal))
        rep["src_asr_text"] = src_text
        rep["similarity_vs_src"] = round(difflib.SequenceMatcher(
            None, clean(text), clean(src_text)).ratio(), 3)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
