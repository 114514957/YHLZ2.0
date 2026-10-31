"""Offline P2 stub bridge (test-only): owned pid lock + fresh status heartbeat.

Used by tools/qq_bridge_p2_matrix.py to exercise real watchdog spawn/terminate
without QQ, NapCat or the daemon.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend.qq_bridge_lock import (  # noqa: E402
    acquire_pid_lock, make_info, release_pid_lock,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="lite")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--ws-state", default="connected")
    ap.add_argument("--account-online", default="true")
    args = ap.parse_args()
    state = pathlib.Path(args.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    info = make_info(args.profile, entry=str(pathlib.Path(__file__).resolve()),
                     role="bridge")
    acquire_pid_lock(state / "bridge.lock", info)
    (state / "bridge.pid").write_text(
        json.dumps(info, ensure_ascii=False), encoding="utf-8")
    try:
        while True:
            status = {
                "state": args.ws_state,
                "event_loop_ts": time.time(),
                "account_online": args.account_online.lower() == "true",
                "profile": args.profile,
                "pid": info["pid"],
                "instance_id": info["instance_id"],
                "inbox": {"pending": 0, "busy": 0},
                "dev_state": {"status": "idle", "task": ""},
            }
            tmp = state / "bridge_status.json.tmp"
            tmp.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            tmp.replace(state / "bridge_status.json")
            time.sleep(0.5)
    finally:
        release_pid_lock(state / "bridge.lock", info)
        (state / "bridge.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
