"""Generate Yuanheng voice SFT material (ledger 0429).

Builds audio-text pairs from local data so the cloud run is just training:

  ASR pairs      : system(转写助手) + user(audio) + assistant(精确文本)
  Reply pairs    : system(元亨+语音纪律) + user(audio) + assistant(元亨短答)
  真实片段       : the real clips in cache/voice_clips with verified text
  noise mixing   : a share of ASR clips get real background mixed at SNR 8-15dB
                   (targets the "noisy clip -> garbage transcript" failure)

Audio is always 16 kHz mono wav, stored under <out>/audio/.
Output: <out>/voice_v1_train.jsonl / voice_v1_val.jsonl / voice_v1.stats.json

Usage:
    python tools/gen_voice_data.py --n-asr 200 --n-reply 150
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

SYS_ASR = "你是转写助手，只输出听到的话，不要解释。"
TXT_ASR = "转写这段音频，只输出内容。"
SYS_REPLY = ("你是元亨——老爹的伙伴，活泼、傲娇、话短；像朋友说话，禁止助手腔。"
             "老爹是语音说的：只输出你要对他说的话本身，≤2句；"
             "禁止复述、念稿、助手腔，禁止输出思考/分析/状态/括号说明。")
TXT_REPLY = "（听完直接回应）"

SEED_PHRASES = [
    "元亨，今晚吃什么？", "利贞在吗", "老爹回来了", "大肥鱼又胖了",
    "今天有点累", "帮我记住，我不吃香菜", "现在几点了",
    "明天要下雨吗", "我回来了", "刚刚说到哪了", "你记得我喜欢什么吗",
    "讲个冷笑话", "别闹了", "我想你了", "晚安", "早上好",
]

_BAD_REPLY = ("**", "[[", "（思考", "(思考", "思考模式", "分析用户意图",
              "作为", "助手")


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def _tts(text: str, out: Path) -> bool:
    """Edge-TTS -> 16k mono wav (soxr)."""
    import asyncio as _a

    import edge_tts
    import imageio_ffmpeg
    import soundfile as sf

    mp3 = out.with_suffix(".mp3")
    tmp = out.with_suffix(".24k.wav")

    async def _go() -> None:
        await edge_tts.Communicate(text, "zh-CN-XiaoyiNeural", rate="+8%").save(str(mp3))

    try:
        _a.run(_go())
        if not (mp3.exists() and mp3.stat().st_size > 0):
            return False
        import subprocess

        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(mp3),
                        "-ac", "1", "-ar", "16000", str(tmp)],
                       capture_output=True, timeout=120)
        if not (tmp.exists() and tmp.stat().st_size > 44):
            return False
        x, sr = sf.read(str(tmp), dtype="float32")
        sf.write(str(out), x, sr, subtype="PCM_16")
        return True
    except Exception:
        return False
    finally:
        for p in (mp3, tmp):
            try:
                p.unlink()
            except Exception:
                pass


def _mix_background(speech: np.ndarray, bg: np.ndarray, snr_db: float) -> np.ndarray:
    if bg.size == 0 or speech.size == 0:
        return speech
    if bg.size < speech.size:
        bg = np.tile(bg, int(np.ceil(speech.size / bg.size)))
    bg = bg[: speech.size]
    target = _rms(speech) / (10 ** (snr_db / 20.0))
    cur = _rms(bg)
    if cur <= 0:
        return speech
    mixed = speech + bg * (target / cur)
    return np.clip(mixed, -1.0, 1.0).astype("float32")


def _phrase_pool(limit: int) -> list[str]:
    """Short realistic user lines from the v6 SFT data + manual seeds."""
    pool = list(SEED_PHRASES)
    src = _ROOT / "dist" / "finetune_bundle" / "sft_persona_v6_train.jsonl"
    try:
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            for m in rec.get("messages") or []:
                if m.get("role") != "user":
                    continue
                t = str(m.get("content") or "").strip()
                if 4 <= len(t) <= 24 and re.search(r"[\u4e00-\u9fff]", t) \
                        and "（" not in t and "[[" not in t:
                    pool.append(t)
    except Exception:
        pass
    seen: list[str] = []
    for p in pool:
        if p not in seen:
            seen.append(p)
    random.shuffle(seen)
    return seen[:limit] if limit > 0 else seen


def _ask_reply(wav: Path) -> str:
    """One audio-direct 元亨 reply via the local llama-server (8081)."""
    import base64

    body = json.dumps({
        "model": "gemma-4-e4b", "stream": False, "temperature": 0.2,
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": SYS_REPLY},
            {"role": "user", "content": [
                {"type": "input_audio",
                 "input_audio": {"data": base64.b64encode(wav.read_bytes()).decode(),
                                 "format": "wav"}},
                {"type": "text", "text": TXT_REPLY},
            ]},
        ],
    }).encode()
    req = urllib.request.Request("http://127.0.0.1:8081/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return str(json.loads(r.read().decode())["choices"][0]["message"]
                   .get("content") or "").strip()


def _reply_ok(text: str) -> bool:
    t = str(text or "").strip()
    if not t or len(t) > 80 or t.endswith(("？", "?")):
        return False
    return not any(b in t for b in _BAD_REPLY)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(_ROOT / "dist" / "finetune_bundle" / "voice"))
    ap.add_argument("--n-asr", type=int, default=200)
    ap.add_argument("--n-reply", type=int, default=150)
    ap.add_argument("--noise-ratio", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=20260918)
    ap.add_argument("--val-ratio", type=float, default=0.1)
    args = ap.parse_args()
    random.seed(args.seed)

    out = Path(args.out)
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    import soundfile as sf

    bg = None
    bg_src = _ROOT / "cache" / "voice_clips" / "seg_20260918_192803.wav"
    if bg_src.exists():
        bg, _ = sf.read(str(bg_src), dtype="float32")

    pool = _phrase_pool(args.n_asr + args.n_reply + 20)
    asr_phrases = pool[: args.n_asr]
    reply_phrases = pool[args.n_asr: args.n_asr + args.n_reply]

    rows: list[dict] = []
    t0 = time.time()

    # ---- ASR pairs ----
    for i, phrase in enumerate(asr_phrases):
        path = audio_dir / f"asr_{i:04d}.wav"
        if not path.exists() and not _tts(phrase, path):
            continue
        x, sr = sf.read(str(path), dtype="float32")
        if random.random() < args.noise_ratio and bg is not None:
            x = _mix_background(x, bg, random.uniform(8.0, 15.0))
            sf.write(str(path), x, sr, subtype="PCM_16")
        rows.append({
            "id": f"voice_asr_{i:04d}", "kind": "asr",
            "messages": [
                {"role": "system", "content": SYS_ASR},
                {"role": "user", "content": [
                    {"type": "audio", "audio": f"voice/audio/{path.name}"},
                    {"type": "text", "text": TXT_ASR}]},
                {"role": "assistant", "content": phrase},
            ],
        })
        if (i + 1) % 20 == 0:
            print(f"[asr] {i + 1}/{len(asr_phrases)}", flush=True)

    # ---- reply pairs (audio -> 元亨 short reply, generated by local v6) ----
    made = 0
    for i, phrase in enumerate(reply_phrases):
        path = audio_dir / f"reply_{i:04d}.wav"
        if not path.exists() and not _tts(phrase, path):
            continue
        try:
            reply = _ask_reply(path)
        except Exception:
            continue
        if not _reply_ok(reply):
            continue
        rows.append({
            "id": f"voice_reply_{i:04d}", "kind": "reply",
            "messages": [
                {"role": "system", "content": SYS_REPLY},
                {"role": "user", "content": [
                    {"type": "audio", "audio": f"voice/audio/{path.name}"},
                    {"type": "text", "text": TXT_REPLY}]},
                {"role": "assistant", "content": reply},
            ],
        })
        made += 1
        if (i + 1) % 10 == 0:
            print(f"[reply] {i + 1}/{len(reply_phrases)} ok={made}", flush=True)

    # ---- real clips (verified text) ----
    real = [("seg_20260918_192014.wav", "哦，我听得到啊，啥都。"),
            ("seg_20260918_201121.wav", "今晚吃什么")]
    for j, (name, text) in enumerate(real):
        src = _ROOT / "cache" / "voice_clips" / name
        if not src.exists():
            continue
        dst = audio_dir / f"real_{j:02d}.wav"
        import shutil

        shutil.copyfile(src, dst)
        rows.append({
            "id": f"voice_real_{j:02d}", "kind": "asr_real",
            "messages": [
                {"role": "system", "content": SYS_ASR},
                {"role": "user", "content": [
                    {"type": "audio", "audio": f"voice/audio/{dst.name}"},
                    {"type": "text", "text": TXT_ASR}]},
                {"role": "assistant", "content": text},
            ],
        })

    random.shuffle(rows)
    n_val = max(1, int(len(rows) * args.val_ratio))
    val, train = rows[:n_val], rows[n_val:]
    for name, part in (("voice_v1_train.jsonl", train), ("voice_v1_val.jsonl", val)):
        with (out / name).open("w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    try:
        audio_rel = str(audio_dir.relative_to(_ROOT))
    except ValueError:
        audio_rel = str(audio_dir)
    stats = {"total": len(rows), "train": len(train), "val": len(val),
             "kinds": kinds, "noise_ratio": args.noise_ratio,
             "audio_dir": audio_rel,
             "elapsed_s": round(time.time() - t0, 1)}
    (out / "voice_v1.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
