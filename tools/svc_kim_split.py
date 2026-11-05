"""跑 Kim RoFormer 人声/伴奏分离（MSST），自带唱窗开合。

用法: python tools/svc_kim_split.py <mix.wav> <out_dir>
输出: <out_dir>/vocals.wav, <out_dir>/instrumental.wav
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MSST = ROOT / "cache" / "msst"
CFG = MSST / "kim.yaml"
CKPT = MSST / "pretrain" / "kim.ckpt"
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
    ap.add_argument("mix")
    ap.add_argument("out_dir")
    a = ap.parse_args()
    mix = Path(a.mix).resolve()
    out = Path(a.out_dir).resolve()
    if not mix.is_file():
        print(json.dumps({"ok": False, "error": f"missing {mix}"}, ensure_ascii=False))
        return 2
    work = ROOT / "cache" / "sing" / ("kim_" + time.strftime("%H%M%S"))
    (work / "in").mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(mix, work / "in" / mix.name)

    from backend import gpu_window
    win = gpu_window.open_window(require_free_mb=5200, timeout=120)
    info = {"window": win, "free_mb": free_mb()}
    try:
        t0 = time.time()
        r = subprocess.run(
            [str(PY), "inference.py", "--model_type", "mel_band_roformer",
             "--config_path", str(CFG), "--start_check_point", str(CKPT),
             "--input_folder", str(work / "in"), "--store_dir", str(work / "out"),
             "--extract_instrumental"],
            cwd=str(MSST), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=3600)
        info["elapsed_s"] = round(time.time() - t0, 1)
        info["rc"] = r.returncode
        stems = list((work / "out").rglob("*.wav"))
        info["stems"] = [s.name for s in stems]
        voc = next((s for s in stems if s.stem.lower().startswith("vocals")), None)
        ins = next((s for s in stems if s.stem.lower().startswith("instrumental")), None)
        if r.returncode != 0 or voc is None or ins is None:
            info["ok"] = False
            info["tail"] = (r.stdout or "")[-400:] + (r.stderr or "")[-400:]
            print(json.dumps(info, ensure_ascii=False))
            return 1
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(voc, out / "vocals.wav")
        shutil.copy2(ins, out / "instrumental.wav")
        info.update({"ok": True, "vocals": str(out / "vocals.wav"),
                     "instrumental": str(out / "instrumental.wav")})
    finally:
        try:
            info["window_close"] = gpu_window.close_window()
        except Exception as ex:  # noqa: BLE001
            info["window_close_error"] = repr(ex)
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
