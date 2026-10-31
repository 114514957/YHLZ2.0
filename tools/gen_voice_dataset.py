"""Generate a Xiaoyi speech dataset for DDSP-SVC training (ledger 0466).

Reads sentences from the QQ corpus (filtered), synthesizes with edge-tts
(zh-CN-XiaoyiNeural), converts to 44.1k mono wav.
Usage: python tools/gen_voice_dataset.py [--n 400]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = _ROOT / "data" / "finetune" / "corpus_qq_raw.jsonl"
OUT = _ROOT / "models" / "tts" / "voice_train" / "xiaoyi"


def pick_sentences(n: int) -> list[str]:
    lines: list[str] = []
    if CORPUS.exists():
        for raw in CORPUS.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(raw)
            except Exception:
                continue
            t = str(d.get("text") or "").strip()
            if not (12 <= len(t) <= 42):
                continue
            if any(c in t for c in "@[]<>{}"):
                continue
            if re.search(r"https?://|\.com|\.cn", t):
                continue
            if len(re.findall(r"[\u4e00-\u9fff]", t)) < 8:
                continue
            lines.append(t)
    dedup = list(dict.fromkeys(lines))
    if not dedup:
        dedup = ["今天天气不错，我们出去走走吧。"] * n
    step = max(1, len(dedup) // n)
    return dedup[::step][:n]


async def synth(texts: list[str]) -> None:
    import edge_tts
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    OUT.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    done = 0

    async def one(i: int, text: str) -> None:
        nonlocal done
        wav = OUT / f"{i:04d}.wav"
        if wav.exists() and wav.stat().st_size > 20000:
            done += 1
            return
        mp3 = OUT / f"{i:04d}.mp3"
        async with sem:
            try:
                await edge_tts.Communicate(text, "zh-CN-XiaoyiNeural").save(str(mp3))
                await asyncio.to_thread(subprocess.run, [
                    ffmpeg, "-y", "-i", str(mp3), "-ac", "1", "-ar", "44100",
                    str(wav)], capture_output=True)
                mp3.unlink(missing_ok=True)
                done += 1
                if done % 50 == 0:
                    print(f"  {done} clips", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i}] fail {type(exc).__name__}")

    await asyncio.gather(*(one(i, t) for i, t in enumerate(texts, 1)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    a = ap.parse_args()
    texts = pick_sentences(a.n)
    print(f"sentences: {len(texts)} -> {OUT}")
    asyncio.run(synth(texts))
    wavs = sorted(OUT.glob("*.wav"))
    total = 0.0
    import soundfile as sf

    for w in wavs:
        try:
            total += float(sf.info(str(w)).duration)
        except Exception:
            pass
    print(f"done: {len(wavs)} wavs, {total / 60:.1f} min audio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
