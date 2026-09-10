"""YHLZ watchdog (ledger 0226): keep the stack alive.

Every interval: check ollama(11434) / gemma(8081) / daemon(8321); restart any
that died. Meant to run at logon (startup folder shortcut, pythonw = no window)
so Yuanheng is "always there" (autonomy cadence / weekly report depend on it).

Usage: python tools/yhlz_watchdog.py [--interval 60] [--once]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

LOG = _ROOT / "cache" / "watchdog.log"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tick() -> dict:
    from yhlz_launcher import ensure_stack, qqbot_status, status

    before = status()
    down = [k for k, v in before.items() if not v]
    if down:
        _log(f"检测到掉线 {down} -> 拉起")
        ensure_stack()
        time.sleep(3)
    after = status()
    qb = qqbot_status()
    if qb != getattr(tick, "_last_qb", None):
        _log(f"QQ桥: {'在线' if qb else '未运行/未登录'}")
        tick._last_qb = qb
    return after


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.once:
        st = tick()
        _log(f"once: {st}")
        return 0 if all(st.values()) else 1
    _log(f"看门狗启动，每 {a.interval:.0f}s 巡检一次")
    while True:
        try:
            st = tick()
            if not all(st.values()):
                _log(f"仍掉线: {st}")
        except Exception as exc:  # noqa: BLE001
            _log(f"巡检异常 {type(exc).__name__}: {exc}")
        time.sleep(max(10.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
