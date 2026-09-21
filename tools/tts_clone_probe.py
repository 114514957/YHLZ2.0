"""A2 clone spike (ledger 0453): Edge timbre -> local Qwen3-TTS 0.6B-Base.

Loads the 0.6B-Base clone model, synthesizes test lines with an Edge-TTS
reference (zh-CN-XiaoyiNeural), writes A/B wavs (Edge original vs clone) and
reports latency + VRAM. Read-only w.r.t. production services.

Usage: python tools/tts_clone_probe.py [--ref ref01] [--xvec-only]
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL = _ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-0.6B-Base"
REFS = _ROOT / "models" / "tts" / "refs" / "xiaoyi"
OUT = _ROOT / "cache" / "voice_clips" / "clone_ab"

TESTS = [
    ("t1", "老爹，我是元亨。这句话是用本地零样本克隆说出来的。"),
    ("t2", "今天就到这里吧，记得早点休息，晚安。"),
    ("t3", "哇哈哈哈，本小姐的声音听起来是不是更像我了？"),
]


def _vram() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            alloc = torch.cuda.memory_allocated() / 1e9
            return (f"free={free/1e9:.2f}GB/{total/1e9:.2f}GB "
                    f"allocated={alloc:.2f}GB peak={torch.cuda.max_memory_allocated()/1e9:.2f}GB")
    except Exception:
        pass
    return "n/a"


def _edge_wav(text: str, out: pathlib.Path, voice: str) -> bool:
    try:
        import edge_tts
        import imageio_ffmpeg

        mp3 = out.with_suffix(".mp3")
        asyncio.run(edge_tts.Communicate(text, voice).save(str(mp3)))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(mp3),
                        "-ac", "1", "-ar", "24000", str(out)],
                       capture_output=True, check=False)
        return out.exists()
    except Exception as exc:  # noqa: BLE001
        print(f"  edge baseline fail: {type(exc).__name__}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="ref01")
    ap.add_argument("--model", default=str(MODEL))
    ap.add_argument("--xvec-only", action="store_true")
    ap.add_argument("--voice", default="zh-CN-XiaoyiNeural")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ref_wav = REFS / f"{a.ref}.wav"
    ref_txt = (REFS / f"{a.ref}.txt").read_text(encoding="utf-8").strip()
    print(f"ref={ref_wav.name} ({ref_wav.stat().st_size/1e3:.0f}KB) "
          f"xvec_only={a.xvec_only}")
    print("VRAM before:", _vram())

    import soundfile as sf
    import torch

    from faster_qwen3_tts import FasterQwen3TTS

    t0 = time.time()
    try:
        model = FasterQwen3TTS.from_pretrained(
            a.model, device="cuda", dtype=torch.bfloat16)
    except Exception as exc:  # noqa: BLE001
        print(f"LOAD FAIL: {type(exc).__name__}: {str(exc)[:300]}")
        print("VRAM:", _vram())
        return 2
    print(f"model loaded in {time.time()-t0:.1f}s | VRAM: {_vram()}")

    for name, text in TESTS:
        t = time.time()
        try:
            audio_list, sr = model.generate_voice_clone(
                text=text, language="Chinese",
                ref_audio=str(ref_wav) if not a.xvec_only else None,
                ref_text=ref_txt, xvec_only=a.xvec_only,
                temperature=0.9)
        except Exception as exc:  # noqa: BLE001
            print(f"{name} SYNTH FAIL: {type(exc).__name__}: {str(exc)[:200]}")
            print("VRAM:", _vram())
            return 3
        dt = time.time() - t
        wav = OUT / f"clone_{name}.wav"
        audio = audio_list[0] if isinstance(audio_list, (list, tuple)) else audio_list
        sf.write(str(wav), audio, int(sr))
        dur = len(audio) / float(sr)
        print(f"{name}: synth={dt:.1f}s audio={dur:.1f}s RTF={dt/dur:.2f} "
              f"-> {wav.name}")
        if name == "t1":
            _edge_wav(text, OUT / "edge_t1.wav", a.voice)
    print("VRAM after:", _vram())
    print(f"AB -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
