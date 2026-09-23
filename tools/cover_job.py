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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
    ap.add_argument("--3stem", dest="three_stem", action="store_true",
                    help="3-stem mode: lead(干声)/backing(和声)/bgm(伴奏); "
                         "replace lead only, then mix all three back")
    ap.add_argument("--lead-gain", type=float, default=1.4)
    ap.add_argument("--backing-gain", type=float, default=0.8)
    ap.add_argument("--bgm-gain", type=float, default=0.8)
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
        elif args.three_stem:
            stem_dir = _ROOT / "cache" / "sing" / "stem3"
            stem_dir.mkdir(parents=True, exist_ok=True)
            r0 = _run([_wsl_path(_ROOT / "tools" / "wsl_stem3_split.sh"),
                       _wsl_path(tgt), _wsl_path(stem_dir)],
                      timeout=args.prep_timeout)
            result["stem3_rc"] = r0.returncode
            result["stem3_tail"] = (r0.stdout or "")[-300:] + (r0.stderr or "")[-200:]
            if r0.returncode != 0:
                raise RuntimeError(f"stem3 split failed rc={r0.returncode}")
            r0b = _run([_wsl_path(_ROOT / "tools" / "wsl_f0_prep.sh"),
                        _wsl_path(stem_dir / "lead.wav")], timeout=900)
            result["f0_rc"] = r0b.returncode
            result["f0_tail"] = (r0b.stdout or "")[-200:] + (r0b.stderr or "")[-200:]
            if r0b.returncode != 0:
                raise RuntimeError(f"f0 prep failed rc={r0b.returncode}")
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

        source_wav = gen
        stem_dir = _ROOT / "cache" / "sing" / "stem3"
        if args.three_stem:
            mixed = out / "mixed.wav"
            r3 = _run([_wsl_path(_ROOT / "tools" / "wsl_mix3.sh"),
                       _wsl_path(gen), _wsl_path(stem_dir / "backing.wav"),
                       _wsl_path(stem_dir / "bgm.wav"), _wsl_path(mixed),
                       "--lead-gain", str(args.lead_gain),
                       "--backing-gain", str(args.backing_gain),
                       "--bgm-gain", str(args.bgm_gain)], timeout=600)
            result["mix_rc"] = r3.returncode
            result["mix_tail"] = (r3.stdout or "")[-200:] + (r3.stderr or "")[-200:]
            if r3.returncode != 0 or not mixed.is_file():
                raise RuntimeError(f"mixdown failed rc={r3.returncode}")
            source_wav = mixed

        # ledger 0476: one folder per production inside 翻唱产出; type-first
        # names (干声/和声/伴奏/AI主唱/成品) — operator naming convention.
        stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", tgt.stem)[:40] or "cover"
        suffix = "_三轨" if args.three_stem else ""
        run_dir = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}"
        run_dir.mkdir(parents=True, exist_ok=True)

        vocal_src = ("/root/soulx/SoulX-Singer/example/transcriptions/"
                     "target_user/vocal.wav")
        # 干声 = SVC input; 和声/伴奏 = stems (three-stem mode)
        staged = [("干声", vocal_src)]
        if args.three_stem:
            staged += [("和声", _wsl_path(stem_dir / "backing.wav")),
                       ("伴奏", _wsl_path(stem_dir / "bgm.wav"))]
        for type_name, wsl_src in staged:
            dst = run_dir / f"{type_name}_{stem}.wav"
            r2 = _run(["-c", f"cp {wsl_src!r} {_wsl_path(dst)!r}"], timeout=120)
            if r2.returncode == 0:
                result.setdefault("staged", []).append(str(dst))

        ai_lead = run_dir / f"AI主唱_{stem}_{vtag}.wav"
        shutil.copy2(gen, ai_lead)
        final = run_dir / f"成品_{stem}_{vtag}{suffix}.wav"
        shutil.copy2(source_wav, final)
        (run_dir / "说明.txt").write_text(
            f"元亨翻唱 · 生产档案\n源曲：{tgt}\n流程：demucs → MDX卡拉OK → "
            f"DDSP-SVC 换主唱（归一化+th-80）{'+ 三轨混回' if args.three_stem else ''}\n"
            f"嗓：{vtag}；增益：lead={args.lead_gain} back={args.backing_gain} "
            f"bgm={args.bgm_gain}\n", encoding="utf-8")
        result["run_dir"] = str(run_dir)
        result["cover"] = str(final)

        sid = ""
        try:
            from backend import song_library

            tags = ["翻唱", "三轨"] if args.three_stem else ["翻唱"]
            title = f"{stem}（元亨翻唱·{vtag}{'·三轨' if args.three_stem else ''}）"
            item = song_library.save_ref(title=title, wav_path=final,
                                         source="cover-job", target=str(tgt),
                                         tags=tags)
            sid = str(item.get("id") or "")
        except Exception as exc:  # noqa: BLE001
            result["library_error"] = str(exc)[:160]
        result["song_id"] = sid

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
