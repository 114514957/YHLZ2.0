"""批量翻唱：把「投入里有、产出里没有」的歌按顺序跑完（cover_produce S1-S7）。

用法：
  python tools/cover_batch.py --pending [--since 2026-11-13] [--limit N]
                              [--voice bright] [--presets e]

只做调度：每首调 tools/cover_produce.py，失败记下来继续下一首；
锁文件 cache/sing/batch.lock 防止同时跑两批。日志 cache/sing/batch_<ts>.log。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "音频素材" / "翻唱投入"
OUT = ROOT / "音频素材" / "翻唱产出"
LOCK = ROOT / "cache" / "sing" / "batch.lock"
LOG_DIR = ROOT / "cache" / "sing"


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"^\d{8}[-_]?\d*", "", s)
    s = re.sub(r"_(3stem|seedvc|1022复刻|native分轨.*)$", "", s)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff\u3040-\u30ff]+", "", s)


def pending(since: str = "") -> list[Path]:
    made = {norm(p.name) for p in OUT.iterdir() if p.is_dir()} if OUT.exists() else set()
    out = []
    for p in IN.iterdir():
        if not p.is_file() or p.suffix.lower() not in (".m4a", ".mp3", ".wav", ".flac"):
            continue
        if since and time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)) < since:
            continue
        n = norm(p.stem)
        if n and any(n in m or m in n for m in made):
            continue
        out.append(p)
    out.sort(key=lambda x: x.stat().st_mtime)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--voice", default="bright")
    ap.add_argument("--presets", default="e")
    ap.add_argument("--song", nargs="*", default=None)
    args = ap.parse_args()

    if LOCK.exists():
        print("已有批处理在跑（cache/sing/batch.lock）", flush=True)
        return 2
    songs = ([Path(s) for s in args.song] if args.song else
             (pending(args.since) if args.pending else []))
    if args.limit:
        songs = songs[:args.limit]
    if not songs:
        print("没有待翻的歌", flush=True)
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"batch_{ts}.log"
    results = []
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            def say(line: str) -> None:
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()

            say(f"batch start {ts}: {len(songs)} songs -> {log_path}")
            for i, song in enumerate(songs, start=1):
                t0 = time.time()
                say(f"[{i}/{len(songs)}] {song.name} ...")
                cmd = [str(py), "-X", "utf8", str(ROOT / "tools" / "cover_produce.py"),
                       str(song), "--voice", args.voice, "--presets", args.presets]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace",
                                       timeout=1800, cwd=str(ROOT),
                                       creationflags=0x08000000)
                    out = (r.stdout or "").strip().splitlines()
                    info = None
                    for line in reversed(out):
                        if line.strip().startswith("{") and '"ok"' in line:
                            try:
                                info = json.loads(line)
                                break
                            except Exception:  # noqa: BLE001
                                continue
                    ok = bool(info and info.get("ok") and r.returncode == 0)
                    rec = {"song": song.name, "ok": ok,
                           "elapsed_s": round(time.time() - t0, 1),
                           "final": (info or {}).get("final"),
                           "sep": (info or {}).get("sep"),
                           "error": None if ok else (
                               (info or {}).get("error")
                               or (r.stderr or "")[-200:] or f"rc={r.returncode}")}
                except Exception as exc:  # noqa: BLE001
                    rec = {"song": song.name, "ok": False,
                           "elapsed_s": round(time.time() - t0, 1),
                           "error": f"{type(exc).__name__}: {exc}"}
                results.append(rec)
                say(("OK " if rec["ok"] else "FAIL ") + song.name
                    + f" {rec['elapsed_s']}s"
                    + (f" -> {rec['final']}" if rec["ok"] else f" :: {str(rec['error'])[:120]}"))
            json_path = LOG_DIR / f"batch_{ts}.json"
            json_path.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
            ok_n = sum(1 for x in results if x["ok"])
            say(f"batch done: {ok_n}/{len(results)} ok -> {json_path}")
    finally:
        try:
            LOCK.unlink()
        except Exception:  # noqa: BLE001
            pass
    return 0 if all(x["ok"] for x in results) else 1


if __name__ == "__main__":
    sys.exit(main())
