"""Wake-word + dialog real-machine probe (0158): always-on until you say
元亨 + a sentence; then LLM answers and TTS speaks (hit-to-stop).

Usage: python tools/wake_dialog_probe.py [--wake-word 元亨] [--duration-s 40]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--wake-word", default="元亨")
    parser.add_argument("--duration-s", type=float, default=40.0)
    parser.add_argument("--device", type=int, default=1)
    args = parser.parse_args()

    from backend.target_wake_dialog import WakeDialogLoop

    loop = WakeDialogLoop(wake_words=(args.wake_word,),
                          duration_s=args.duration_s, device=args.device)

    def on_wake(w: str, el: float) -> None:
        print(f"!! 唤醒: {w} @ {el}s（请继续说完）", flush=True)

    print(f"常开监听（{args.duration_s:.0f}s 上限）：说「{args.wake_word}」唤醒，命中即停…",
          flush=True)
    r = loop.run(on_wake=on_wake)
    print(f"[heard] {r['heard']}", flush=True)
    if not r["heard"] or not r["wake"]:
        print("无唤醒/无内容", flush=True)
        return 1
    from backend.target_entry import ConversationSession

    session = ConversationSession()
    import asyncio

    info = asyncio.run(session.run_turn(r["heard"]))
    print(f"[answer] {info['answer'][:200]}", flush=True)
    # TTS speak via the probe module (MCI playback path)
    from tools.voice_dialog_probe import _sentence_cut

    play_text = _sentence_cut(info["answer"], 200)
    import subprocess

    tts = subprocess.Popen(
        [sys.executable, "-m", "backend.tts_speaker_probe",
         "--speakers", "Vivian", "--text", play_text],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tts.wait(timeout=180)
    print(f"tts_exit={tts.returncode}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
