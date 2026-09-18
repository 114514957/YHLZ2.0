"""v7.1 real-domain ASR mix (ledger 0432): augment the real mic clips.

v7 regressed on real-mic ASR because the ASR task saw 200 TTS clips and only 2
real ones.  This builds voice_v1b_* with:
  real ASR  : 2 real clips x N augmentations (noise/gain/shift), true text kept
  TTS ASR   : capped subset of the v1 TTS rows (keeps general coverage)
  replies   : all v1 reply rows (voice behaviour)
Rehearsal text rows stay handled by sft_voice --rehearsal.

Usage: python tools/gen_voice_real.py --n-per-clip 50 --tts-keep 100
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

VOICE = _ROOT / "dist" / "finetune_bundle" / "voice"
AUDIO = VOICE / "audio"
SYS_ASR = "你是转写助手，只输出听到的话，不要解释。"
TXT_ASR = "转写这段音频，只输出内容。"

REAL = [
    ("seg_20260918_192014.wav", "哦，我听得到啊，啥都。"),
    ("seg_20260918_201121.wav", "今晚吃什么"),
]


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def _augment(x: np.ndarray, sr: int, bg: np.ndarray | None, rng) -> np.ndarray:
    y = x.copy()
    mode = rng.random()
    if mode < 0.45 and bg is not None and bg.size:
        noise = bg
        if noise.size < y.size:
            noise = np.tile(noise, int(np.ceil(y.size / noise.size)))
        off = rng.randrange(0, max(1, noise.size - y.size + 1)) if noise.size > y.size else 0
        noise = noise[off:off + y.size]
        target = _rms(y) / (10 ** (rng.uniform(5.0, 20.0) / 20.0))
        y = y + noise * (target / max(_rms(noise), 1e-9))
    elif mode < 0.75:
        y = y * (10 ** (rng.uniform(-6.0, 6.0) / 20.0))
    else:
        shift = rng.randint(-1600, 1600)
        y = np.roll(y, shift)
        if shift > 0:
            y[:shift] = 0
        elif shift < 0:
            y[shift:] = 0
    return np.clip(y, -1.0, 1.0).astype("float32")


def _row(rid: str, wav: str, truth: str) -> dict:
    return {"id": rid, "kind": "asr_real",
            "messages": [
                {"role": "system", "content": SYS_ASR},
                {"role": "user", "content": [
                    {"type": "audio", "audio": f"voice/audio/{wav}"},
                    {"type": "text", "text": TXT_ASR}]},
                {"role": "assistant", "content": truth},
            ]}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-per-clip", type=int, default=50)
    ap.add_argument("--tts-keep", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20260919)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)

    bg = None
    bg_p = _ROOT / "cache" / "voice_clips" / "seg_20260918_192803.wav"
    if bg_p.exists():
        bg, _ = sf.read(str(bg_p), dtype="float32")

    # ---- real-domain rows ----
    real_rows: list[dict] = []
    for ci, (name, truth) in enumerate(REAL):
        src = _ROOT / "cache" / "voice_clips" / name
        if not src.exists():
            print("missing", src)
            continue
        x, sr = sf.read(str(src), dtype="float32")
        real_rows.append(_row(f"v1b_real_{ci}_orig", name, truth))
        for k in range(args.n_per_clip):
            y = _augment(x, sr, bg, rng)
            wav = f"real_aug_{ci}_{k:03d}.wav"
            sf.write(str(AUDIO / wav), y, sr, subtype="PCM_16")
            real_rows.append(_row(f"v1b_real_{ci}_{k:03d}", wav, truth))

    # ---- existing rows ----
    old = [json.loads(l) for l in (VOICE / "voice_v1_train.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    tts_asr = [r for r in old if r["kind"] == "asr"]
    rng.shuffle(tts_asr)
    tts_asr = tts_asr[: args.tts_keep]
    replies = [r for r in old if r["kind"] == "reply"]
    # fix audio paths (old rows reference voice/audio/... already)
    rows = real_rows + tts_asr + replies
    rng.shuffle(rows)

    val_real = real_rows[: min(6, len(real_rows))]
    train = [r for r in rows if r not in val_real]
    out_train = VOICE / "voice_v1b_train.jsonl"
    out_val = VOICE / "voice_v1b_val.jsonl"
    with out_train.open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with out_val.open("w", encoding="utf-8") as f:
        for r in val_real:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"real": len(real_rows), "tts_asr": len(tts_asr),
                      "replies": len(replies), "train": len(train),
                      "val": len(val_real)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
