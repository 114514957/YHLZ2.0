# -*- coding: utf-8 -*-
"""干声预处理 v2：去混响（MSST dereverb 模型）+ 高通 + 轻谱减（2026-11-13）

老爹：「分离不干净，以后干声分离完要做预处理」。
v1 只做了参考谱减，实测只压掉 4% 能量——**听不出来**，因为唱的地方人声远大于伴奏。

v2 换主力：仓库里本来就有 **dereverb.ckpt**（871 MB，MSST 去混响模型）。
混响是"干声不干净"的大头：它让换声后又糊又散，而且任何分离模型都去不掉
（分离只分"人声/伴奏"，不分"直达声/混响"）。

链路：高通 70Hz → **dereverb 模型去混响** → 轻参考谱减（压伴奏残留）→ 峰值 -3 dBFS

用法：
  python tools/svc_prep_vocal.py <vocals.wav> <instrumental.wav> <out.wav>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
MSST = ROOT / "cache" / "msst"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
CFG = MSST / "dereverb.yaml"
CKPT = MSST / "pretrain" / "dereverb.ckpt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("instrumental")
    ap.add_argument("out")
    ap.add_argument("--skip-dereverb", action="store_true")
    ap.add_argument("--alpha", type=float, default=0.6)
    ap.add_argument("--floor", type=float, default=0.20)
    a = ap.parse_args()

    v = Path(a.vocals).resolve()
    i = Path(a.instrumental).resolve()
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    info: dict = {"ok": False, "steps": {}}

    if not (CFG.is_file() and CKPT.is_file()):
        info["error"] = "缺 dereverb 模型：%s / %s" % (CFG, CKPT)
        print(json.dumps(info, ensure_ascii=False))
        return 2

    # ── 1) 去混响（MSST，单模型、不开 GPU 唱窗由上层负责）──────────────
    if a.skip_dereverb:
        derev = v
        info["steps"]["dereverb"] = {"ok": True, "skipped": True}
    else:
        work = ROOT / "cache" / "sing" / ("derev_" + time.strftime("%H%M%S"))
        (work / "in").mkdir(parents=True, exist_ok=True)
        shutil.copy2(v, work / "in" / "vocal.wav")
        t0 = time.time()
        r = subprocess.run(
            [str(PY), "inference.py", "--model_type", "mel_band_roformer",
             "--config_path", str(CFG), "--start_check_point", str(CKPT),
             "--input_folder", str(work / "in"), "--store_dir", str(work / "out")],
            cwd=str(MSST), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=3600)
        el = round(time.time() - t0, 1)
        stems = sorted((work / "out").rglob("*.wav")) if (work / "out").is_dir() else []
        # 去混响模型的输出：干声/混响两轨，取名字里带 vocal/干/anechoic 的那条
        pick = None
        for s in stems:
            nm = s.stem.lower()
            if any(k in nm for k in ("vocal", "dry", "anechoic", "干", "nv")):
                pick = s
                break
        if pick is None and stems:
            pick = stems[0]
        info["steps"]["dereverb"] = {"ok": pick is not None, "elapsed_s": el,
                                     "rc": r.returncode,
                                     "stems": [s.name for s in stems],
                                     "picked": pick.name if pick else "",
                                     "tail": ("" if pick else (r.stdout or "")[-300:])}
        if pick is None:
            info["error"] = "去混响没有产出"
            print(json.dumps(info, ensure_ascii=False))
            return 1
        derev = pick

    # ── 2) 高通 + 轻参考谱减（复用 v1 的 DSP 部分，力度调轻）────────────
    t0 = time.time()
    r = subprocess.run(
        [str(PY), str(ROOT / "tools" / "svc_vocal_clean.py"),
         str(derev), str(i), str(out),
         "--alpha", str(a.alpha), "--floor", str(a.floor), "--hp", "70"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1800)
    info["steps"]["spectral"] = {"ok": r.returncode == 0,
                                 "elapsed_s": round(time.time() - t0, 1)}
    if r.returncode != 0:
        info["error"] = (r.stderr or "")[-300:]
        print(json.dumps(info, ensure_ascii=False))
        return 1
    try:
        info["spectral_report"] = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        info["spectral_report"] = {}
    info.update({"ok": True, "out": str(out)})
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
