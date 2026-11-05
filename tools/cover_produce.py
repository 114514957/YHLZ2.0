"""一首歌跑完整条已验收链路（10-22 版）：demucs → 原生卡拉OK → SeedVC → 柔化e → 三轨混回。

把唱窗开合集中在外面：cover_seedvc.py 内部不管显存，SVC 阶段必须已经在窗口里。
用法：
  python tools/cover_produce.py "音频素材/翻唱投入/xxx.m4a" [--voice bright] [--presets e]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # gbk 控制台会炸在 em dash 上


def free_mb() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--voice", default="bright")
    ap.add_argument("--presets", default="e")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    from backend import gpu_window  # noqa: E402

    win = gpu_window.open_window(require_free_mb=5500, timeout=150)
    info = {"window": win, "free_mb": free_mb()}
    # 关键：告诉下层（卡拉OK那步）唱窗已由外层持有，别再自己关一次——
    # 2026-11-02 实测：它一关，llama 立刻回填 4.3GB，随后 SVC 只剩 173MB 可用。
    os.environ["YH_WINDOW_HELD"] = "1"
    t0 = time.time()
    try:
        cmd = [str(ROOT / ".venv" / "Scripts" / "python.exe"),
               str(ROOT / "tools" / "cover_seedvc.py"), args.target,
               "--voice", args.voice, "--presets", args.presets]
        if args.out_dir:
            cmd += ["--out-dir", args.out_dir]
        print("[run]", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=7200, cwd=str(ROOT),
                           creationflags=0x08000000)
        tail = (r.stdout or "").strip().splitlines()
        parsed = None
        for line in reversed(tail):
            if line.strip().startswith("{") and '"ok"' in line:
                try:
                    parsed = json.loads(line)
                    break
                except Exception:  # noqa: BLE001
                    continue
        info["elapsed_s"] = round(time.time() - t0, 1)
        info["rc"] = r.returncode
        info["result"] = parsed
        if parsed is None:
            info["tail"] = (r.stdout or "")[-600:] + (r.stderr or "")[-400:]
    finally:
        try:
            info["window_close"] = gpu_window.close_window()
        except Exception as ex:  # noqa: BLE001
            info["window_close_error"] = repr(ex)
    print(json.dumps(info, ensure_ascii=False))
    return 0 if (info.get("result") or {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

