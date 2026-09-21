"""Generate Edge-TTS reference clips for the Qwen3-TTS 0.6B clone (A1/0453).

Usage: python tools/gen_edge_refs.py [--voice zh-CN-XiaoyiNeural] [--out DIR]
Produces ref01..refNN.wav (24k mono) + matching .txt transcripts, ready for
`faster-qwen3-tts clone --ref-audio refNN.wav --ref-text "$(cat refNN.txt)"`.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent

REFS = [
    ("ref01", "今天天气挺好的，下午我们去河边走走吧，顺便看看大肥鱼有没有长胖。"),
    ("ref02", "老爹，别熬太晚了，事情做不完就明天再说，身体比什么都重要。"),
    ("ref03", "哇哈哈哈，本小姐今天心情好，谁也别拦着我，我要把这条街逛个遍！"),
    ("ref04", "这个模块的显存占用还可以再压一压，把批大小降到四以下试试，应该能稳住。"),
    ("ref05", "风从黄河边吹过来的时候，我总觉得时间是可以被听见的，"
              "像旧唱片里沙沙的底噪，提醒我此刻真的在活着。"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="zh-CN-XiaoyiNeural")
    ap.add_argument("--rate", default="+0%")
    ap.add_argument("--out", default=str(_ROOT / "models" / "tts" / "refs" / "xiaoyi"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    import edge_tts
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for name, text in REFS:
        mp3 = out / f"{name}.mp3"
        wav = out / f"{name}.wav"
        try:
            asyncio.run(edge_tts.Communicate(
                text, a.voice, rate=a.rate).save(str(mp3)))
            subprocess.run([ffmpeg, "-y", "-i", str(mp3), "-ac", "1",
                            "-ar", "24000", str(wav)],
                           capture_output=True, check=False)
            (out / f"{name}.txt").write_text(text, encoding="utf-8")
            dur = ""
            if wav.exists():
                import wave

                with wave.open(str(wav), "rb") as w:
                    dur = f"{w.getnframes() / w.getframerate():.1f}s"
            print(f"{name}: {dur} -> {wav.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: FAIL {type(exc).__name__}: {exc}")
    print(f"refs -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
