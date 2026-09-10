"""Raw OneBot event probe: connect to NapCat WS and append every received
event to cache/tmp/qq_events.log (until killed). For diagnosing delivery.
Usage: python tools/qq_listen_probe.py
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = _ROOT / "cache" / "tmp" / "qq_events.log"
URL = "ws://127.0.0.1:3001?access_token=yhlz2026"


async def main() -> int:
    import websockets
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8", buffering=1) as f:
        f.write(f"\n=== probe start {time.strftime('%H:%M:%S')} ===\n")
        while True:
            try:
                async with websockets.connect(URL, open_timeout=5) as ws:
                    f.write(f"[{time.strftime('%H:%M:%S')}] connected\n")
                    async for raw in ws:
                        f.write(f"[{time.strftime('%H:%M:%S')}] {raw}\n")
            except Exception as e:  # noqa: BLE001
                f.write(f"[{time.strftime('%H:%M:%S')}] err {type(e).__name__}: {e}\n")
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
