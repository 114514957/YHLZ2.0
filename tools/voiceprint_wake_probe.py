"""Voiceprint wake + dialog real-machine probe (0159).

Always-on; triggers when the ENROLLED user's voice is heard (background video
voices should not).  Then keeps listening to the complete utterance, answers
via LLM, and speaks via TTS.  Hit-to-stop.

Usage: python tools/voiceprint_wake_probe.py [--threshold 0.55] [--duration-s 40]
Prereq: python tools/voiceprint_enroll.py (hold mic close)
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
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--duration-s", type=float, default=45.0)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--cap-gain", type=float, default=1.0)
    args = parser.parse_args()

    from backend.target_wake_dialog import VoiceprintDialogLoop

    loop = VoiceprintDialogLoop(threshold=args.threshold,
                                duration_s=args.duration_s,
                                device=args.device,
                                cap_gain=args.cap_gain)

    def on_wake(sim: float, el: float) -> None:
        print(f"!! 声纹唤醒: sim={sim} @ {el}s（请继续说完）", flush=True)

    def on_verify(sim: float) -> None:
        print(f"  [sim={sim}]", flush=True)

    print(f"常开声纹监听（阈值 {args.threshold}，实时显示相似度）："
          f"请把麦克风贴近嘴边说话，命中即停…", flush=True)
    r = loop.run(on_wake=on_wake, on_verify=on_verify)
    print(f"[wake] {r['wake']}", flush=True)
    print(f"[heard] {r['heard']}", flush=True)
    if not r["wake"] or not r["heard"]:
        print("未唤醒/无内容", flush=True)
        return 1

    from backend.target_entry import ConversationSession

    session = ConversationSession()
    import asyncio

    info = asyncio.run(session.run_turn(r["heard"]))
    print(f"[answer] {info['answer'][:200]}", flush=True)
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
