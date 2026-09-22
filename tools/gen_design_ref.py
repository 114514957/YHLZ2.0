"""Generate the clone reference for the chosen designed voice (ledger 0463).

VoiceDesign(清亮俏皮) -> ~12s reference wav + transcript, stored under
models/tts/refs/design_bright/ so the 0.6B clone engine can speak it stably.
Usage: python tools/gen_design_ref.py
"""
from __future__ import annotations

import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

MODEL = _ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
OUT = _ROOT / "models" / "tts" / "refs" / "design_bright"
INSTRUCT = ("清亮、年轻的少女声线，活泼俏皮，语速偏快，"
            "语气自然亲近，像在跟熟人撒娇。")
TEXT = ("老爹，我是元亨呀。今天心情特别好，想到你就想笑。"
        "你要是累了就歇会儿，我在这儿陪着你。")


def main() -> int:
    from backend import gpu_window

    OUT.mkdir(parents=True, exist_ok=True)
    win = gpu_window.open_window(require_free_mb=5600)
    print("window:", win)
    try:
        if not win.get("ok"):
            print("GPU window failed; abort")
            return 2
        import soundfile as sf
        import torch

        from faster_qwen3_tts import FasterQwen3TTS

        t0 = time.time()
        model = FasterQwen3TTS.from_pretrained(
            str(MODEL), device="cuda", dtype=torch.bfloat16)
        print(f"loaded in {time.time() - t0:.1f}s")
        t = time.time()
        audio_list, sr = model.generate_voice_design(
            text=TEXT, instruct=INSTRUCT, language="Chinese")
        audio = (audio_list[0] if isinstance(audio_list, (list, tuple))
                 else audio_list)
        wav = OUT / "ref01.wav"
        sf.write(str(wav), audio, int(sr))
        (OUT / "ref01.txt").write_text(TEXT, encoding="utf-8")
        print(f"ref: {len(audio) / sr:.1f}s in {time.time() - t:.1f}s -> {wav}")
        return 0
    finally:
        print("closing window:", gpu_window.close_window())


if __name__ == "__main__":
    raise SystemExit(main())
