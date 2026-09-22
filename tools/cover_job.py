#!/usr/bin/env python3
"""Cover job with an exclusive GPU window around ALL heavy stages.

Why (2026-09-22 finding): on the 8GB card the BS-Roformer separation slows to
~12x realtime when it has to share VRAM with llama-server/TTS (sysmem
fallback). The werkbank's two-stage flow keeps the chat online during
separation, which is fine on big cards but pathological here. This runner
opens the window once (llama+watchdog stopped, WSL terminated) and runs
separation+F0 and the SoulX SVC back to back, then restores the services.

Usage:
  python tools/cover_job.py <target audio> [--voice xiaoyi] [--out-dir DIR]
                            [--keep-vocal]
Outputs JSON on stdout: {ok, cover, vocal, log_tail, free_mb}.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from backend import gpu_window  # noqa: E402

_ROOT_OUT = _ROOT / "音频素材" / "翻唱产出"
_VOCAL_CACHE = _ROOT / "cache" / "voice_clips" / "sing"
_REF = {
    "xiaoyi": ("models/tts/refs/xiaoyi/ref01.wav", "Xiaoyi嗓"),
    "bright": ("models/tts/refs/design_bright/ref01.wav", "清亮嗓"),
}


def _wsl_path(p: pathlib.Path) -> str:
    p = p.resolve()
    drive = p.drive.rstrip(":").lower()
    rest = str(p)[len(p.drive):].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    cmd = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash"] + args
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--voice", default="xiaoyi", choices=sorted(_REF))
    ap.add_argument("--out-dir", default=str(_ROOT_OUT))
    ap.add_argument("--keep-vocal", action="store_true")
    ap.add_argument("--no-prep", action="store_true",
                    help="reuse the target prepared by an earlier prep run")
    ap.add_argument("--svc-auto", action="store_true",
                    help="SVC with --auto_shift (key may change; default raw)")
    ap.add_argument("--fast-sep", action="store_true",
                    help="demucs fast separation instead of BS-Roformer prep")
    ap.add_argument("--window-mb", type=int, default=6500)
    ap.add_argument("--prep-timeout", type=float, default=2700)
    ap.add_argument("--svc-timeout", type=float, default=1800)
    args = ap.parse_args()

    tgt = pathlib.Path(args.target).resolve()
    if not tgt.is_file():
        print(json.dumps({"ok": False, "error": f"target not found: {tgt}"},
                         ensure_ascii=False))
        return 2
    ref_rel, vtag = _REF[args.voice]
    ref = _ROOT / ref_rel
    out_dir = pathlib.Path(args.out_dir)

    result: dict = {"ok": False, "target": str(tgt), "voice": args.voice}
    t0 = time.time()
    try:
        win = gpu_window.open_window(require_free_mb=args.window_mb)
        result["window"] = win
        if not win.get("ok"):
            raise RuntimeError(f"显存不足 free={win.get('free_mb')}MB")

        r0 = None
        if args.no_prep:
            result["prep_rc"] = "skipped"
        else:
            prep = ("wsl_fast_prep.sh" if args.fast_sep
                    else "wsl_soulx_prep.sh")
            if args.fast_sep:
                cmd = [_wsl_path(_ROOT / "tools" / prep),
                       _wsl_path(tgt), args.voice]
            else:
                cmd = [_wsl_path(_ROOT / "tools" / prep),
                       _wsl_path(ref), _wsl_path(tgt), "1", args.voice]
            r0 = _run(cmd, timeout=args.prep_timeout)
            result["prep_rc"] = r0.returncode
            result["prep_tail"] = (r0.stdout or "")[-400:] + (r0.stderr or "")[-200:]
            if r0.returncode != 0:
                raise RuntimeError(f"prep failed rc={r0.returncode}")

        out = _ROOT / "cache" / "sing" / "out"
        out.mkdir(parents=True, exist_ok=True)
        r1 = _run([_wsl_path(_ROOT / "tools" / "wsl_soulx_svc.sh"),
                   _wsl_path(out), args.voice,
                   "auto" if args.svc_auto else "raw"],
                  timeout=args.svc_timeout)
        result["svc_rc"] = r1.returncode
        result["svc_tail"] = (r1.stdout or "")[-600:] + (r1.stderr or "")[-300:]
        gen = out / "generated.wav"
        if r1.returncode != 0 or not gen.is_file():
            raise RuntimeError(f"svc failed rc={r1.returncode}")

        out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", tgt.stem)[:40] or "cover"
        final = out_dir / f"{stem}_{vtag}_{time.strftime('%Y%m%d-%H%M%S')}.wav"
        shutil.copy2(gen, final)
        result["cover"] = str(final)

        vocal_src = ("/root/soulx/SoulX-Singer/example/transcriptions/"
                     "target_user/vocal.wav")
        vocal_dst = _VOCAL_CACHE / f"{stem}_vocal.wav"
        if args.keep_vocal:
            _VOCAL_CACHE.mkdir(parents=True, exist_ok=True)
            r2 = _run(["-c", f"cp {vocal_src!r} {_wsl_path(vocal_dst)!r}"],
                      timeout=120)
            result["vocal_rc"] = r2.returncode
            if r2.returncode == 0:
                result["vocal"] = str(vocal_dst)
            else:
                result["vocal_err"] = (r2.stderr or "")[-200:]

        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        try:
            result["restore"] = gpu_window.close_window()
        except Exception as exc:  # noqa: BLE001
            result["restore_error"] = str(exc)[:160]
        result["elapsed_s"] = round(time.time() - t0, 1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
