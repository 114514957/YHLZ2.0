"""原生卡拉OK分轨（MSST + becruily mel-band-roformer-karaoke），不依赖 WSL。

背景（2026-10-22 验收链路 = 记录 0935）：三轨 = demucs 两轨 → 卡拉OK模型拆 lead/backing。
WSL 现在起不来（E_ACCESSDENIED），所以把这一段搬到 Windows：同一个 MSST 推理器，
换 becruily 的 karaoke 权重即可。

用法：
  python tools/svc_karaoke_split.py <vocals.wav> <out_dir> [--no-window]

输出：<out_dir>/lead.wav（主唱）、<out_dir>/backing.wav（和声/伴奏人声）
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
MSST = ROOT / "cache" / "msst"
CFG = MSST / "karaoke.yaml"
CKPT = MSST / "pretrain" / "karaoke.ckpt"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


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
    ap.add_argument("vocals")
    ap.add_argument("out_dir")
    ap.add_argument("--no-window", action="store_true")
    a = ap.parse_args()

    src = Path(a.vocals).resolve()
    out = Path(a.out_dir).resolve()
    if not src.is_file():
        print(json.dumps({"ok": False, "error": f"missing {src}"}, ensure_ascii=False))
        return 2
    if not CKPT.is_file():
        print(json.dumps({"ok": False, "error": f"missing {CKPT}"}, ensure_ascii=False))
        return 2

    work = ROOT / "cache" / "sing" / ("kara_" + time.strftime("%H%M%S"))
    (work / "in").mkdir(parents=True, exist_ok=True)
    (work / "out").mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, work / "in" / src.name)

    win = None
    held = os.environ.get("YH_WINDOW_HELD") == "1"   # 上层已经开过唱窗，别重复开/关
    if not a.no_window and not held:
        from backend import gpu_window  # noqa: E402
        win = gpu_window.open_window(require_free_mb=5500, timeout=120)
        deadline = time.time() + 120
        while time.time() < deadline and free_mb() < 3500:
            time.sleep(3)
    info = {"window": win, "free_mb": free_mb()}
    try:
        t0 = time.time()
        r = subprocess.run(
            [str(PY if PY.is_file() else sys.executable), "inference.py",
             "--model_type", "mel_band_roformer",
             "--config_path", str(CFG),
             "--start_check_point", str(CKPT),
             "--input_folder", str(work / "in"),
             "--store_dir", str(work / "out")],
            cwd=str(MSST), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=3600)
        info["elapsed_s"] = round(time.time() - t0, 1)
        info["rc"] = r.returncode
        if r.returncode != 0:
            info.update({"ok": False, "tail": (r.stdout or "")[-400:] + (r.stderr or "")[-400:]})
            print(json.dumps(info, ensure_ascii=False))
            return 1
        stems = list((work / "out").rglob("*.wav"))
        info["stems"] = [s.name for s in stems]
        if not stems:
            info.update({"ok": False, "error": "no stems produced"})
            print(json.dumps(info, ensure_ascii=False))
            return 1
        # 约定：vocals.* = 主唱；instrumental/other.* = 和声
        lead = next((s for s in stems if s.stem.lower().startswith("vocals")), None)
        back = next((s for s in stems if s is not lead), None)
        if lead is None or back is None:
            info.update({"ok": False, "error": f"unexpected stems {info['stems']}"})
            print(json.dumps(info, ensure_ascii=False))
            return 1
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lead, out / "lead.wav")
        shutil.copy2(back, out / "backing.wav")
        info.update({"ok": True, "lead": str(out / "lead.wav"),
                     "backing": str(out / "backing.wav")})
    finally:
        if win is not None:
            try:
                info["window_close"] = gpu_window.close_window()
            except Exception as ex:  # noqa: BLE001
                info["window_close_error"] = repr(ex)
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

