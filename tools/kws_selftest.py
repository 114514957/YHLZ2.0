"""KWS self-test via TTS playback (0156): play 元亨 on speakers while
spotting on the mic.  No human speech needed."""

from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-s", type=float, default=25.0)
    parser.add_argument("--device", type=int, default=1)
    parser.add_argument("--tts-device", type=int, default=5)
    parser.add_argument("--tts-text", default="元亨")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    tts = subprocess.Popen(
        [sys.executable, "-m", "backend.tts_speaker_probe",
         "--speakers", "Vivian", "--text", args.tts_text,
         "--device", str(args.tts_device), "--play-gain", "2.0"],
        cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    from backend.target_kws import WakeWordSpotter

    spotter = WakeWordSpotter()
    print(f"监听 {args.duration_s}s：TTS 将播「{args.tts_text}」，检测唤醒命中…", flush=True)

    def on_kw(keyword: str, elapsed: float) -> bool:
        print(f"!! 命中: {keyword} @ {elapsed}s", flush=True)
        return True

    result = spotter.listen_once(
        duration_s=args.duration_s, device=args.device, on_keyword=on_kw
    )
    tts.wait(timeout=60)
    print(f"结果: {len(result['wakes'])} 次命中 / {result['duration_s']}s", flush=True)
    return 0 if result["wakes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
