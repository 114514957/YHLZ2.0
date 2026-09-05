"""KWS real-machine probe (0156): always-on mic listening for the wake word.

Usage: python tools/kws_probe.py [--duration-s 60] [--device 1]
Say the wake word (元亨) while it listens.
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
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--device", type=int, default=1)
    args = parser.parse_args()

    from backend.target_kws import WakeWordSpotter

    spotter = WakeWordSpotter()
    print(f"监听中（{args.duration_s:.0f}s）… 说「元亨」测试唤醒", flush=True)

    def on_kw(keyword: str, elapsed: float) -> bool:
        print(f"!! 唤醒命中: {keyword} @ {elapsed}s", flush=True)
        return False  # hit-to-stop: end the listen window on first wake

    result = spotter.listen_once(
        duration_s=args.duration_s, device=args.device, on_keyword=on_kw
    )
    print(f"完成: {len(result['wakes'])} 次命中 / {result['duration_s']}s", flush=True)
    return 0 if result["wakes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
