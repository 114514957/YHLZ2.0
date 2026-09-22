"""VoiceDesign probe (ledger 0461): design 元亨's voice by description.

Opens the GPU window (stops LLM/watchdog), loads the 1.7B-VoiceDesign model
and synthesizes one line under several persona instructions, saving A/B wavs.

Usage: python tools/tts_design_probe.py
"""
from __future__ import annotations

import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

MODEL = _ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
OUT = _ROOT / "cache" / "voice_clips" / "design"
TEXT = "老爹，我是元亨，这是我的新声音，你觉得怎么样？"

DESIGNS = [
    ("design_01_bright", "清亮、年轻的少女声线，活泼俏皮，语速偏快，"
                         "语气自然亲近，像在跟熟人撒娇。"),
    ("design_02_gentle", "温柔清澈的年轻女声，语气安静体贴，语速稍慢，"
                         "像深夜和老朋友慢慢聊天。"),
    ("design_03_sassy", "机灵聪慧的少女音，带一点傲娇和笑意，吐字清晰有力，"
                        "偶尔上扬，不播音腔。"),
    ("design_04_calm", "沉稳但不失灵动的年轻女声，理性而温暖，语速适中，"
                       "表达清楚，有书卷气。"),
]


def _vram() -> str:
    try:
        import torch

        free, total = torch.cuda.mem_get_info()
        return (f"free={free / 1e9:.2f}G/{total / 1e9:.2f}G "
                f"peak={torch.cuda.max_memory_allocated() / 1e9:.2f}G")
    except Exception:
        return "n/a"


def main() -> int:
    from backend import gpu_window

    OUT.mkdir(parents=True, exist_ok=True)
    # 1.7B needs ~5-5.5GB; desktop apps may hold ~2GB, so 6500 is too strict
    win = gpu_window.open_window(require_free_mb=5600)
    print("window:", win)
    rc = 0
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
        print(f"model loaded in {time.time() - t0:.1f}s | {_vram()}")

        for name, instruct in DESIGNS:
            t = time.time()
            try:
                audio_list, sr = model.generate_voice_design(
                    text=TEXT, instruct=instruct, language="Chinese")
            except Exception as exc:  # noqa: BLE001
                print(f"{name}: FAIL {type(exc).__name__}: {str(exc)[:160]}")
                rc = 3
                continue
            dt = time.time() - t
            audio = (audio_list[0] if isinstance(audio_list, (list, tuple))
                     else audio_list)
            wav = OUT / f"{name}.wav"
            sf.write(str(wav), audio, int(sr))
            print(f"{name}: {dt:.1f}s for {len(audio)/sr:.1f}s audio "
                  f"-> {wav.name} | {_vram()}")
        print("design outputs ->", OUT)
    finally:
        print("closing window:", gpu_window.close_window())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
