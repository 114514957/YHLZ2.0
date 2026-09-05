"""Voice entry (ledger 0163): wake(voiceprint/keyword)-then-speak dialog,
packaged as a module so `python -m backend.target_voice_entry` runs it.

Wraps the real-machine probes (tools/voice_dialog_probe / voiceprint_wake_probe
behaviour) behind the same ConversationSession used by CLI.
"""

from __future__ import annotations

import io
import sys


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="语音对话入口")
    parser.add_argument("--wake", action="store_true",
                        help="声纹唤醒（需先 voiceprint_enroll；默认直接听一句）")
    parser.add_argument("--duration-s", type=float, default=40.0)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--cap-gain", type=float, default=6.0)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    if args.wake:
        from backend.target_wake_dialog import VoiceprintDialogLoop

        loop = VoiceprintDialogLoop(duration_s=args.duration_s,
                                    device=args.device,
                                    cap_gain=args.cap_gain,
                                    threshold=args.threshold)
        print(f"声纹监听中（阈值 {args.threshold}）… 说话即唤醒，命中即停", flush=True)

        def on_wake(sim: float, el: float) -> None:
            print(f"!! 唤醒 sim={sim} @ {el}s（请说完）", flush=True)

        r = loop.run(on_wake=on_wake)
        if not r["wake"] or not r["heard"]:
            print("未唤醒/无内容", flush=True)
            return 1
        heard = r["heard"]
    else:
        from tools.voice_dialog_probe import voice_dialog_once

        print("聆听一句… 听到即答（命中即停）", flush=True)
        r = voice_dialog_once(duration_s=args.duration_s, device=args.device,
                              cap_gain=args.cap_gain, print_text=True)
        if r["status"] != "answered":
            print("未听到有效语音", flush=True)
            return 1
        return 0 if r.get("tts_exit") == 0 else 2

    print(f"[heard] {heard}", flush=True)
    import asyncio

    from backend.target_entry import ConversationSession

    session = ConversationSession()
    info = asyncio.run(session.run_turn(heard))
    print(f"[answer] {info['answer'][:200]}", flush=True)
    from tools.voice_dialog_probe import _sentence_cut

    play_text = _sentence_cut(info["answer"], 200)
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tts = subprocess.Popen(
        [sys.executable, "-m", "backend.tts_speaker_probe",
         "--speakers", "Vivian", "--text", play_text],
        cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tts.wait(timeout=180)
    print(f"tts_exit={tts.returncode}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
