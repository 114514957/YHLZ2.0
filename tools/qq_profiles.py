"""QQ group member profile CLI (2026-10-06).

Usage:
    .venv\\Scripts\\python.exe tools\\qq_profiles.py --rebuild
    .venv\\Scripts\\python.exe tools\\qq_profiles.py --list [--limit 30]
    .venv\\Scripts\\python.exe tools\\qq_profiles.py --show <qq>
    .venv\\Scripts\\python.exe tools\\qq_profiles.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

if not os.getenv("YHLZ_QQ_PROFILE"):
    os.environ["YHLZ_QQ_PROFILE"] = "lite"

from backend.qq_bridge_state import path as _bridge_path  # noqa: E402
from backend.qq_group_store import GroupHistoryStore  # noqa: E402
from backend.qq_profiles import MemberProfileStore  # noqa: E402


def _paths() -> tuple[pathlib.Path, pathlib.Path]:
    hist = _bridge_path("group_history.db",
                        _ROOT / "cache" / "tmp" / "qq_group_history.db")
    prof = _bridge_path("profiles.db",
                        _ROOT / "cache" / "tmp" / "qq_profiles.db")
    return hist, prof


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    hist_path, prof_path = _paths()
    store = MemberProfileStore(prof_path)
    if args.rebuild:
        from backend.yhlz_paths import MASTER_UIN

        history = GroupHistoryStore(hist_path, bot_uin=os.getenv(
            "YHLZ_QQ_BOT_UIN", "3655185302"))
        updated = store.rebuild(
            history, masters={MASTER_UIN},
            bot_uin=os.getenv("YHLZ_QQ_BOT_UIN", "3655185302"))
        print(f"rebuilt {updated} profiles -> {prof_path}")
        if not (args.list or args.show):
            return 0
    if args.show:
        profile = store.get(args.show)
        if not profile:
            print("未找到该 QQ 的档案")
            return 1
        print(MemberProfileStore.profile_text(profile))
        return 0
    if args.json:
        print(json.dumps(store.list_members(args.limit), ensure_ascii=False,
                         indent=2))
        return 0
    print(store.list_text(args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
