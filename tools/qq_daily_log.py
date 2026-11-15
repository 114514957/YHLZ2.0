# -*- coding: utf-8 -*-
"""QQ 每日对话记录器：把会话里新增的每一轮，带时间戳落成按天分文件。

为什么要有它：`cache/sessions/qq_*.json` 只存 `saved_at`（整个文件最后一次保存），
history 里**没有时间戳**，没法按天复盘。这个脚本每次运行都做一次增量快照：
  读所有 qq_*.json 的 history → 用 (role+内容哈希) 判重 → 没见过的新轮次，
  以当前时间为 ts 追加进 `cache/qq_daily/<YYYYMMDD>.jsonl`。

用法：
  python qq_daily_log.py            # 采一次
  python qq_daily_log.py --loop 300 # 每 5 分钟采一次（可挂后台）
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
YH = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
SESS = os.path.join(YH, "cache", "sessions")
OUTDIR = os.path.join(YH, "cache", "qq_daily")
SEEN = os.path.join(OUTDIR, "_seen_hashes.json")


def now() -> float:
    return time.time()


def h(role: str, content: str) -> str:
    return hashlib.sha1((role + "\x00" + content).encode("utf-8")).hexdigest()[:16]


def load_seen() -> dict:
    if os.path.exists(SEEN):
        try:
            return json.load(io.open(SEEN, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_seen(d: dict) -> None:
    os.makedirs(OUTDIR, exist_ok=True)
    tmp = SEEN + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, SEEN)


def channel_of(path: str) -> str:
    b = os.path.basename(path)[:-5]
    return b[3:] if b.startswith("qq_") else b


def collect(verbose: bool = True) -> int:
    os.makedirs(OUTDIR, exist_ok=True)
    # 首次运行会把 sessions 里的历史一次性回填——这些**不是今天聊的**，
    # 必须标记，否则日报会把陈年旧账算成当天对话（2026-11-13 实测：首跑回填 104 轮）。
    first_run = not os.path.exists(SEEN)
    seen = load_seen()
    day = time.strftime("%Y%m%d")
    out_path = os.path.join(OUTDIR, "%s.jsonl" % day)
    added = 0

    for p in sorted(glob.glob(os.path.join(SESS, "qq_*.json"))):
        ch = channel_of(p)
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        hist = d.get("history") or []
        if not isinstance(hist, list):
            continue
        # 找「新轮次」：从头扫，遇到全是见过的就跳过；遇到没见过的就记
        for i, m in enumerate(hist):
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").strip()
            text = (m.get("content") or "").strip()
            if role not in ("user", "assistant") or not text:
                continue
            key = h(role, text)
            if key in seen:
                continue
            seen[key] = {"ch": ch, "ts": now(), "day": day}
            rec = {"ts": now(), "day": day, "channel": ch, "idx": i,
                   "role": role, "text": text,
                   "backfill": first_run,
                   "next_role": (hist[i + 1].get("role") if i + 1 < len(hist) else None)}
            with io.open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            added += 1

    save_seen(seen)
    if verbose:
        print("采集完成：新增 %d 轮 → %s" % (added, out_path))
    return added


def run_review(day: str = "") -> None:
    """调 style_review 出一份日报；失败不影响采集。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import style_review as SR  # noqa: PLC0415
        d = day or time.strftime("%Y%m%d")
        res = SR.review(d)
        out = SR.write_report(res)
        if res.get("turns"):
            SR.append_style_bank(res)
            SR.update_index(res)
        print("复盘完成：%d 轮 → %s" % (res.get("turns", 0), out), flush=True)
    except Exception as ex:  # noqa: BLE001
        print("复盘失败：%s: %s" % (type(ex).__name__, ex), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="秒；0 表示只采一次")
    ap.add_argument("--review", action="store_true", help="采完立刻复盘一次")
    ap.add_argument("--review-at", default="",
                    help="每天到这个时刻自动复盘，如 23:50（配合 --loop）")
    a = ap.parse_args()
    if not a.loop:
        collect()
        if a.review:
            run_review()
        return 0
    print("循环采集，每 %d 秒一次%s（Ctrl+C 退出）"
          % (a.loop, "，每天 %s 自动复盘" % a.review_at if a.review_at else ""))
    reviewed = ""
    # 2026-11-14：**补跑**。进程如果在 23:50 之后才起（比如机器睡了一夜），
    # 只靠 loop 里的判断会等到第二天才出报告。所以启动时先看今天的报告在不在。
    if a.review_at and time.strftime("%H:%M") >= a.review_at:
        day = time.strftime("%Y%m%d")
        rep = os.path.join(ROOT, "docs", "复盘", "风格日报_%s.md" % day)
        if not os.path.exists(rep):
            print("今天还没出报告，补跑一次：%s" % os.path.basename(rep), flush=True)
            run_review(day)
            reviewed = day
    while True:
        try:
            collect(verbose=False)
        except Exception as ex:  # noqa: BLE001
            print("采集失败：%s" % ex, flush=True)
        if a.review_at:
            day = time.strftime("%Y%m%d")
            if time.strftime("%H:%M") >= a.review_at and reviewed != day:
                run_review(day)
                reviewed = day
        time.sleep(max(60, a.loop))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
