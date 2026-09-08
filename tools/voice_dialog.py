"""YHLZ main voice dialog entry (ledger 0219): local end-to-end loop.

    listen (RNNoise front-end + SenseVoice ASR) -> text
        -> Yuanheng (ConversationSession on local Gemma 8081)
        -> answer spoken by local Qwen3-TTS -> back to listen.

Commands: 1 = speak one turn | 2 = close | 0 = exit
Speech capture is stage-separated from TTS playback, so playback echo never
re-enters the microphone path.

ASR backend reuses tools/tts_test_start helpers (SenseVoice default, sherpa
fallback); voiceprint gate is OFF (RNNoise cleaning validated on this machine).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
from tts_test_start import (  # noqa: E402
    _build_asr,
    _capture_loop,
    _clean,
    _transcribe,
    release_sv,
)


def _speak(text: str, tts_model, speaker: str) -> None:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    wavs, sr = tts_model.generate_custom_voice(
        text=text, language="Chinese", speaker=speaker,
        instruct="自然地说，像和亲近的人聊天，别播音腔。")
    samples = np.asarray(wavs[0], dtype="float32")
    sd.play(samples, int(sr))
    sd.wait()


def _cut(text: str, limit: int = 180) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("。", "！", "？", "!", "?", "\n"):
        idx = head.rfind(sep)
        if idx > limit * 0.3:
            return head[: idx + 1]
    return head


def main() -> int:
    import argparse
    import asyncio

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=1)
    ap.add_argument("--duration-s", type=float, default=300.0)
    ap.add_argument("--denoise", default="rnnoise", choices=["off", "rnnoise"])
    ap.add_argument("--asr", default="auto",
                    choices=["auto", "sherpa", "sensevoice"])
    ap.add_argument("--tts-speaker", default="Vivian")
    a = ap.parse_args()

    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    print("加载 ASR…", flush=True)
    asr_info = _build_asr(a.asr)
    if asr_info[0] == "sherpa":
        asr_info[1].start()
    print("加载元亨（本地 Gemma）…", flush=True)
    from backend.target_entry import ConversationSession

    session = ConversationSession()
    tts_model = None  # Qwen3-TTS loaded per turn (8 GB card: ASR/TTS not co-resident)
    print("就绪。输入 1 说话（说完停 3 秒自动断），2 关闭。", flush=True)

    while True:
        try:
            line = input("cmd> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in ("2", "0", "exit", "quit", ""):
            print("已关闭。", flush=True)
            break
        if line != "1":
            continue
        print("聆听…（说完停 3 秒自动断）", flush=True)
        r = _capture_loop(a.device, 1.0, a.duration_s, a.denoise,
                          None, False, False)
        if not r.get("started"):
            print("[未捕捉到语音]", flush=True)
            continue
        audio = r["audio"]
        sid = f"c{int(time.time() * 1000)}"
        try:
            text = _clean(_transcribe(audio, asr_info, sid=sid))
        except Exception as exc:  # noqa: BLE001
            print(f"[ASR 出错] {type(exc).__name__}: {str(exc)[:120]}",
                  flush=True)
            continue
        print(f"[你] {text}", flush=True)
        if not text:
            continue
        try:
            info = asyncio.run(session.run_turn(text))
            answer = str(info.get("answer", ""))
        except Exception as exc:  # noqa: BLE001
            answer = f"抱歉，我这轮没处理过来（{type(exc).__name__}）。"
        print(f"[元亨] {answer}", flush=True)
        if not answer.strip():
            continue
        # free ASR cuda before loading TTS (8 GB card)
        if asr_info[0] == "sensevoice":
            release_sv()
        try:
            if tts_model is None:
                import torch
                from faster_qwen3_tts import FasterQwen3TTS

                print("加载 TTS（Qwen3）…", flush=True)
                tts_model = FasterQwen3TTS.from_pretrained(
                    str(_PROJECT_ROOT / "models" / "qwen3-tts" /
                        "Qwen3-TTS-12Hz-1.7B-CustomVoice"),
                    device="cuda", dtype=torch.bfloat16)
            _speak(_cut(answer), tts_model, a.tts_speaker)
        except Exception as exc:  # noqa: BLE001
            print(f"[TTS 播放失败] {type(exc).__name__}: {str(exc)[:90]}",
                  flush=True)
        finally:
            # release TTS so mic listening can reload ASR next turn
            if tts_model is not None:
                tts_model = None
                import gc
                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
    try:
        if asr_info[0] == "sherpa":
            asr_info[1].stop("done")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
