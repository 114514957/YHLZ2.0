#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed-VC 44k 翻唱链路（2026-10-21 验收通过）。

流程：
  1) 三轨分离（WSL BS-RoFormer/MDX，复用 tools/wsl_stem3_split.sh）
  2) Seed-VC 44k SVC（whisper-base + F0 + 44k BigVGAN）转主唱
  3) cover_v3_dsp.py 柔化（e / d）
  4) wsl_mix3.py 混音（主唱 / 和声 / 伴奏）

用法：
  python tools/cover_seedvc.py "音频素材/翻唱投入/xxx.mp3" --voice bright --presets e,d
  python tools/cover_seedvc.py <target> --stems-dir cache/sing/stem3_real \
      --svc-wav cache/svc_test/real_raw/vc_lead_ref01_1.0_30_0.7.wav   # 跳过重活
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

ROOT = Path(__file__).resolve().parents[1]
SEEDVC = ROOT / "Seed-VC"
OUT_ROOT = ROOT / "音频素材" / "翻唱产出"
FFMPEG = ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin"

REF = {
    "bright": ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.wav",
    "xiaoyi": ROOT / "models" / "tts" / "refs" / "xiaoyi" / "ref01.wav",
}
GSV5_PY = ROOT / "venv-gsv5" / "Scripts" / "python.exe"
SVC_CKPT = SEEDVC / "checkpoints" / "DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth"
SVC_CFG = SEEDVC / "configs" / "presets" / "config_44k_local.yml"


def wsl_path(p: Path) -> str:
    p = p.resolve()
    return "/mnt/" + p.drive.rstrip(":").lower() + str(p)[len(p.drive):].replace("\\", "/")


def native_demucs_split(tgt: Path, stem_dir: Path) -> tuple[bool, str]:
    """Windows 原生兜底分离（不依赖 WSL）：vocals → lead，no_vocals → bgm。

    daemon（pythonw 无控制台）里 WSL 会 E_ACCESSDENIED，生产必须有这条路。
    """
    import numpy as np
    import soundfile as sf

    tmp = ROOT / "cache" / "sing" / "_demucs_tmp"
    tmp_in = ROOT / "cache" / "sing" / "_demucs_in.wav"
    # Windows 会吞掉文件名/目录名末尾的点（"God knows....mp3"），demucs
    # 用原名建目录会 FileNotFound。先转成固定安全名再分离。
    conv = run([str(FFMPEG / "ffmpeg.exe"), "-y", "-i", str(tgt),
                "-ac", "2", "-ar", "44100", str(tmp_in)], timeout=600)
    if conv.returncode != 0 or not tmp_in.is_file():
        return False, "ffmpeg convert failed: " + (conv.stderr or "")[-300:]
    shutil.rmtree(tmp, ignore_errors=True)
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "TORCH_HOME": str(ROOT / "cache" / "torch")})
    r = None
    for device in ("cuda", "cpu"):
        shutil.rmtree(tmp, ignore_errors=True)
        r = run([str(GSV5_PY), "-m", "demucs.separate", "--two-stems=vocals",
                 "-n", "htdemucs", "-d", device, "-o", str(tmp), str(tmp_in)],
                timeout=1800, env=env)
        voc = next(tmp.rglob("vocals.wav"), None)
        nov = next(tmp.rglob("no_vocals.wav"), None)
        if r.returncode == 0 and voc and nov:
            shutil.copy2(voc, stem_dir / "lead.wav")
            shutil.copy2(nov, stem_dir / "bgm.wav")
            info = sf.info(str(stem_dir / "lead.wav"))
            sf.write(str(stem_dir / "backing.wav"),
                     np.zeros((info.frames, info.channels), dtype="float32"),
                     info.samplerate)
            tmp_in.unlink(missing_ok=True)
            return True, f"demucs2-{device}"
    tmp_in.unlink(missing_ok=True)
    return False, ((r.stdout or "")[-300:] + (r.stderr or "")[-300:]) if r else "demucs failed"


def native_karaoke_split(stem_dir: Path) -> tuple[bool, str]:
    """原生卡拉OK拆分（MSST + becruily mel-band-roformer）：demucs 的 vocals → lead/backing。

    2026-11-02：WSL 在本机起不来（E_ACCESSDENIED，daemon 同样），把 `wsl_stem3_split.sh`
    的第二段搬到 Windows。实测：202s 歌曲 194.6s（含开唱窗），权重 1.72 GB，
    lead/backing 同度泄漏 corr≈0.01（不串原唱）。
    """
    voc = stem_dir / "lead.wav"          # native_demucs_split 把 demucs vocals 放在这
    if not voc.is_file():
        return False, "no demucs vocals"
    out = stem_dir / "_karaoke"
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    r = run([str(py if py.is_file() else sys.executable),
             str(ROOT / "tools" / "svc_karaoke_split.py"),
             str(voc), str(out)], timeout=3600)
    lead, back = out / "lead.wav", out / "backing.wav"
    if r.returncode != 0 or not lead.is_file() or not back.is_file():
        return False, ("karaoke failed: "
                       + ((r.stdout or "")[-200:] + (r.stderr or "")[-200:]))
    shutil.copy2(lead, stem_dir / "lead.wav")
    shutil.copy2(back, stem_dir / "backing.wav")
    return True, "native-demucs+karaoke"


def run(cmd: list[str], timeout: float, cwd: Path | None = None,
        env: dict | None = None, flags: int | None = None) -> subprocess.CompletedProcess:
    print("[run]", " ".join(str(c) for c in cmd), flush=True)
    if flags is None:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, creationflags=flags)


def wsl_cmd(args: list[str]) -> list[str]:
    """交互终端里直接 wsl.exe 即可；daemon（pythonw）里会 E_ACCESSDENIED，
    由调用方回退原生 demucs。不要套 conhost：它会吞掉失败返回码。"""
    return ["wsl.exe", "-d", "Ubuntu-22.04", "--"] + args


def ensure_ascii_junction() -> str | None:
    """建 C:\\yhlz -> 工作区的 junction，供任务/bat 用纯 ASCII 路径。"""
    link = "C:\\yhlz"
    if os.path.isdir(link):
        return link
    r = run(["cmd.exe", "/c", "mklink", "/J", link, str(ROOT)], timeout=60)
    return link if os.path.isdir(link) else None


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def ascii_root() -> str | None:
    """ROOT 的纯 ASCII 路径（优先 8.3 短路径，其次专用 junction C:\\yhz）。

    2026-11-01 查到的坑：`C:\\yhlz` 这个 junction 早先被指到了 **YHLZ**（项目根），
    而本脚本把它当 YH 根来拼 bat 路径 → `/mnt/c/yhlz/tools/...` 不存在 →
    计划任务那条 WSL 分轨永远失败 → 静默退回 demucs 两轨（无和声、带伴奏泄漏）。
    所以这里不再盲信 C:\\yhlz：先取 8.3 短路径（不动文件系统），再校验目标。
    """
    try:
        r = run(["cmd.exe", "/c", 'for %I in ("%s") do @echo %%~sI' % ROOT],
                timeout=30, flags=0)
        lines = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
        cand = lines[-1] if lines else ""
        if cand and _is_ascii(cand) and Path(cand).is_dir():
            return cand
    except Exception:  # noqa: BLE001
        pass
    link = "C:\\yhz"
    try:
        if os.path.isdir(link):
            if Path(link).resolve() == ROOT.resolve():
                return link
        else:
            run(["cmd.exe", "/c", "mklink", "/J", link, str(ROOT)], timeout=60, flags=0)
            if os.path.isdir(link) and Path(link).resolve() == ROOT.resolve():
                return link
    except Exception:  # noqa: BLE001
        pass
    return None


def wsl_split_via_task(tgt: Path, stem_dir: Path,
                       timeout: float = 1800) -> tuple[bool, str]:
    """把 WSL 三轨分离交给计划任务（cmd 有控制台，WSL 可用）。

    daemon 是 pythonw/GUI 子系统，直接 spawn wsl.exe 必 E_ACCESSDENIED；
    bat 由计划任务以 cmd 跑则正常。全 ASCII 路径，避免 em dash/日文编码。
    """
    in_wav = ROOT / "cache" / "sing" / "_task_in.wav"
    conv = run([str(FFMPEG / "ffmpeg.exe"), "-y", "-i", str(tgt),
                "-ac", "2", "-ar", "44100", str(in_wav)], timeout=600)
    if conv.returncode != 0 or not in_wav.is_file():
        return False, "ffmpeg convert failed"
    stems = ROOT / "cache" / "sing" / "_task_stems"
    shutil.rmtree(stems, ignore_errors=True)
    marker = ROOT / "cache" / "wsl_split_done.txt"
    marker.unlink(missing_ok=True)
    log = ROOT / "cache" / "wsl_split.log"
    bat = ROOT / "cache" / "wsl_split.bat"
    ar = ascii_root()
    if not ar:
        return False, "ascii root failed (8.3 短路径与 C:\\yhz 都拿不到)"

    def _w(p: Path) -> str:  # Windows 绝对路径（ASCII）
        return ar.rstrip("\\") + "\\" + str(p.relative_to(ROOT)).replace("/", "\\")

    def _m(p: Path) -> str:  # WSL /mnt 路径
        w = _w(p)
        return "/mnt/" + w[0].lower() + w[2:].replace("\\", "/")

    bat.write_text(
        "@echo off\r\n"
        f"del {_w(marker)} 2>nul\r\n"
        f"rmdir /s /q {_w(stems)} 2>nul\r\n"
        f"wsl.exe -d Ubuntu-22.04 -- bash {_m(ROOT / 'tools' / 'wsl_stem3_split.sh')} "
        f"{_m(in_wav)} {_m(stems)} > {_w(log)} 2>&1\r\n"
        f"echo %ERRORLEVEL% > {_w(marker)}\r\n",
        encoding="ascii")
    task = "YHLZ_wsl_split"
    # schtasks 对 /tr 的路径校验在 daemon 里会报“找不到路径”；
    # 用 cmd.exe 作程序、bat 作参数，绕开该校验。
    action = ('C:\\Windows\\System32\\cmd.exe /c "%s"' % _w(bat))
    run(["schtasks", "/delete", "/tn", task, "/f"], timeout=60, flags=0)
    r = run(["schtasks", "/create", "/tn", task, "/tr",
             action, "/sc", "once", "/st", "23:55", "/f"], timeout=60, flags=0)
    if r.returncode != 0:
        return False, "schtasks create failed: " + (r.stderr or "")[-200:]
    run(["schtasks", "/run", "/tn", task], timeout=60, flags=0)
    deadline = time.time() + timeout
    rc = None
    while time.time() < deadline:
        if marker.is_file():
            try:
                rc = int(marker.read_text(encoding="ascii").strip() or "-1")
            except ValueError:
                rc = -1
            break
        time.sleep(3)
    run(["schtasks", "/delete", "/tn", task, "/f"], timeout=60, flags=0)
    in_wav.unlink(missing_ok=True)
    if rc != 0 or not (stems / "lead.wav").is_file():
        tail = log.read_text(encoding="utf-8", errors="replace")[-300:] if log.is_file() else ""
        return False, f"task rc={rc}: {tail}"
    for name in ("lead", "backing", "bgm"):
        src = stems / f"{name}.wav"
        if src.is_file():
            shutil.copy2(src, stem_dir / f"{name}.wav")
    return True, "wsl-task-stem3"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--voice", default="bright", choices=sorted(REF))
    ap.add_argument("--presets", default="e")
    ap.add_argument("--out-dir", default=str(OUT_ROOT))
    ap.add_argument("--stems-dir", default=None)
    ap.add_argument("--reuse-stems", action="store_true",
                    help="复用 --stems-dir 里已有的三轨（只在确认同一首歌时用）")
    ap.add_argument("--sep-engine", default="auto",
                    choices=["auto", "wsl", "demucs"],
                    help="auto=WSL 优先，失败自动切原生 demucs")
    ap.add_argument("--svc-wav", default=None)
    ap.add_argument("--lead-gain", type=float, default=1.0)
    ap.add_argument("--backing-gain", type=float, default=1.5)
    ap.add_argument("--bgm-gain", type=float, default=0.7)
    ap.add_argument("--diffusion-steps", type=int, default=30)
    args = ap.parse_args()

    tgt = Path(args.target).resolve()
    if not tgt.is_file():
        print(json.dumps({"ok": False, "error": f"not found: {tgt}"}, ensure_ascii=False))
        return 2
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    stem_dir = Path(args.stems_dir).resolve() if args.stems_dir else ROOT / "cache" / "sing" / "stem3_real"
    result: dict = {"ok": False, "target": str(tgt), "voice": args.voice}
    t0 = time.time()

    if not args.reuse_stems:
        stem_dir.mkdir(parents=True, exist_ok=True)
        sep_ok = False
        if args.sep_engine in ("auto", "wsl"):
            shutil.rmtree(stem_dir, ignore_errors=True)
            stem_dir.mkdir(parents=True, exist_ok=True)
            r = run(wsl_cmd(["bash",
                             wsl_path(ROOT / "tools" / "wsl_stem3_split.sh"),
                             wsl_path(tgt), wsl_path(stem_dir)]),
                    timeout=2700, flags=0)
            sep_ok = r.returncode == 0 and (stem_dir / "lead.wav").is_file()
            if sep_ok:
                # 防 conhost/旧文件：lead 时长必须和目标一致（容忍 2s）
                try:
                    import soundfile as sf
                    lead_dur = sf.info(str(stem_dir / "lead.wav")).duration
                    tgt_dur = sf.info(str(tgt)).duration
                    if abs(lead_dur - tgt_dur) > 2.0:
                        sep_ok = False
                        result["sep_error"] = (f"stale stems: lead={lead_dur:.1f}s "
                                               f"target={tgt_dur:.1f}s")
                except Exception:  # noqa: BLE001
                    pass
            if sep_ok:
                result["sep"] = "wsl-stem3"
            elif "sep_error" not in result:
                result["sep_error"] = (r.stdout or "")[-200:] + (r.stderr or "")[-200:]
        if not sep_ok:
            # 直接 WSL 被拒（daemon 无控制台）→ 计划任务里的 cmd 跑 WSL
            ok, detail = wsl_split_via_task(tgt, stem_dir)
            if ok:
                sep_ok = True
                result["sep"] = detail
            else:
                result["task_error"] = detail
        if not sep_ok:
            ok, detail = native_demucs_split(tgt, stem_dir)
            if ok:
                sep_ok = True
                result["sep"] = detail
                # 2026-11-02：WSL 起不来，把 wsl_stem3_split.sh 的第二段（卡拉OK拆
                # lead/backing）搬到原生 MSST；成不成都要把 sep 记清楚。
                ok2, detail2 = native_karaoke_split(stem_dir)
                if ok2:
                    result["sep"] = "native-demucs+karaoke"
                else:
                    result["karaoke_error"] = detail2
            else:
                result["error"] = "separation failed (wsl + task + demucs)"
                result["tail"] = detail
                print(json.dumps(result, ensure_ascii=False))
                return 1

    if args.svc_wav:
        svc = Path(args.svc_wav).resolve()
    else:
        svc_dir = ROOT / "cache" / "svc_test" / f"seedvc_{time.strftime('%H%M%S')}"
        svc_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "HF_ENDPOINT": "https://hf-mirror.com",
            "NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com",
            "PATH": str(FFMPEG) + os.pathsep + env.get("PATH", ""),
        })
        r = run([str(GSV5_PY if GSV5_PY.is_file() else sys.executable),
                 "-X", "utf8", "inference.py",
                 "--source", str(stem_dir / "lead.wav"),
                 "--target", str(REF[args.voice]),
                 "--output", str(svc_dir),
                 "--diffusion-steps", str(args.diffusion_steps),
                 "--inference-cfg-rate", "0.7",
                 "--f0-condition", "True",
                 "--auto-f0-adjust", "False",
                 "--semi-tone-shift", "0",
                 "--checkpoint", str(SVC_CKPT),
                 "--config", str(SVC_CFG),
                 "--fp16", "True"], timeout=1800, cwd=SEEDVC, env=env)
        cands = sorted(svc_dir.glob("*.wav"))
        if r.returncode != 0 or not cands:
            result["error"] = "svc failed"
            result["tail"] = (r.stdout or "")[-400:] + (r.stderr or "")[-300:]
            print(json.dumps(result, ensure_ascii=False))
            return 1
        svc = cands[0]
    result["svc"] = str(svc)

    stem = "".join(c if c.isalnum() or c in "-_一-龥" else "_" for c in tgt.stem)[:40] or "cover"
    run_dir = Path(args.out_dir) / f"{time.strftime('%Y%m%d-%H%M%S')}_{stem}_seedvc"
    run_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for preset in presets:
        lead = ROOT / "cache" / "svc_test" / f"seedvc_{preset}_{time.strftime('%H%M%S')}.wav"
        r = run([sys.executable, str(ROOT / "tools" / "cover_v3_dsp.py"),
                 str(svc), str(lead), "--preset", preset], timeout=600)
        if r.returncode != 0 or not lead.is_file():
            result["error"] = f"dsp {preset} failed"
            continue
        out = run_dir / f"成品_{stem}_seedvc_{preset}.wav"

        def _mix() -> subprocess.CompletedProcess:
            return run([sys.executable, str(ROOT / "tools" / "wsl_mix3.py"),
                        str(lead), str(stem_dir / "backing.wav"),
                        str(stem_dir / "bgm.wav"), str(out),
                        "--lead-gain", str(args.lead_gain),
                        "--backing-gain", str(args.backing_gain),
                        "--bgm-gain", str(args.bgm_gain)], timeout=600)

        r = _mix()
        # 2026-10-21 实证：偶发混音只出伴奏（与 lead 相关≈0、与 bgm≈1），
        # 这里做一次内容校验，异常则重混一次。
        try:
            import numpy as _np
            import soundfile as _sf
            yy, _ = _sf.read(str(out), dtype="float32", always_2d=True)
            dd, _ = _sf.read(str(lead), dtype="float32", always_2d=True)
            bb, _ = _sf.read(str(stem_dir / "bgm.wav"), dtype="float32", always_2d=True)
            yy, dd, bb = yy.mean(1), dd.mean(1), bb.mean(1)
            n = min(len(yy), len(dd), len(bb))
            c_lead = float(_np.corrcoef(yy[:n], dd[:n])[0, 1])
            if c_lead < 0.3:
                r = _mix()
        except Exception:  # noqa: BLE001
            pass
        if r.returncode == 0 and out.is_file():
            outputs.append(str(out))
            shutil.copy2(stem_dir / "lead.wav", run_dir / "干声.wav")
            shutil.copy2(stem_dir / "backing.wav", run_dir / "和声.wav")
            shutil.copy2(stem_dir / "bgm.wav", run_dir / "伴奏.wav")

    result.update({"ok": bool(outputs), "out_dir": str(run_dir),
                   "outputs": outputs, "elapsed_s": round(time.time() - t0, 1)})
    print(json.dumps(result, ensure_ascii=False))
    return 0 if outputs else 1


if __name__ == "__main__":
    raise SystemExit(main())
