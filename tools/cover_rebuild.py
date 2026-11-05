"""用已分好的三轨重做一版翻唱（Seed-VC 44k + 可选门控 + 柔化 e + 三轨混回）。

和 cover_seedvc.py 的区别：分离这一步由调用者提供（--stems），因此不依赖 WSL；
另可选 svc_gate（按源干声有声区门控）来堵"在器乐段硬唱"。

用法：
  python tools/cover_rebuild.py --stems cache/sing/stem_heian --name 黑夜梦想家 \
      --preset e --gate both
  --gate both  产出「门控/不门控」两版，方便 A/B
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
sys.path.insert(0, str(ROOT))  # 让 backend.* 可导入（脚本在 tools/ 下时）
SEEDVC = ROOT / "Seed-VC"
OUT_ROOT = ROOT / "音频素材" / "翻唱产出"
FFMPEG = ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin"
REF = ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.wav"
GSV5_PY = ROOT / "venv-gsv5" / "Scripts" / "python.exe"
SVC_CKPT = SEEDVC / "checkpoints" / "DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth"
SVC_CFG = SEEDVC / "configs" / "presets" / "config_44k_local.yml"


def run(cmd, timeout, cwd=None, env=None):
    print("[run]", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env,
                          creationflags=0x08000000)


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
    ap.add_argument("--stems", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--preset", default="e")
    ap.add_argument("--gate", default="both", choices=["off", "on", "both"])
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--lead-gain", type=float, default=1.0)
    ap.add_argument("--backing-gain", type=float, default=1.0)
    ap.add_argument("--bgm-gain", type=float, default=0.7)
    ap.add_argument("--svc-wav", default="", help="复用已有 SVC 输出，跳过推理")
    ap.add_argument("--clarity", type=float, default=0.65,
                    help="清晰增强：把原干声 >6kHz 按此增益叠回（10-10 老爹选定 V2b=0.65）")
    args = ap.parse_args()

    stem_dir = Path(args.stems).resolve()
    lead, backing, bgm = (stem_dir / "lead.wav", stem_dir / "backing.wav",
                          stem_dir / "bgm.wav")
    for p in (lead, backing, bgm):
        if not p.is_file():
            print(json.dumps({"ok": False, "error": f"missing {p}"}, ensure_ascii=False))
            return 2

    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = OUT_ROOT / f"{ts}_{args.name}_3stem"
    work = ROOT / "cache" / "sing" / f"rebuild_{ts}"
    work.mkdir(parents=True, exist_ok=True)

    info: dict = {"stems": str(stem_dir), "name": args.name, "free_before": free_mb()}

    # ── 1. SVC（需要显存，走唱窗）──────────────────────────────
    svc = None
    if args.svc_wav:
        svc = Path(args.svc_wav).resolve()
    else:
        from backend import gpu_window  # noqa: E402

        info["window"] = gpu_window.open_window()
        try:
            deadline = time.time() + 180
            while time.time() < deadline and free_mb() < 5200:
                time.sleep(5)
            info["free_after_window"] = free_mb()
            if info["free_after_window"] < 5200:
                info["error"] = ("显存不足：free=%dMB（唱窗未成功）"
                                 % info["free_after_window"])
                print(json.dumps(info, ensure_ascii=False))
                return 3
            env = dict(os.environ)
            env.update({
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                "HF_ENDPOINT": "https://hf-mirror.com",
                "NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com",
                "PATH": str(FFMPEG) + os.pathsep + env.get("PATH", ""),
            })
            svc_dir = work / "svc"
            svc_dir.mkdir(parents=True, exist_ok=True)
            r = run([GSV5_PY if GSV5_PY.is_file() else sys.executable,
                     "-X", "utf8", "inference.py",
                     "--source", str(lead),
                     "--target", str(REF),
                     "--output", str(svc_dir),
                     "--diffusion-steps", str(args.steps),
                     "--inference-cfg-rate", "0.7",
                     "--f0-condition", "True",
                     "--auto-f0-adjust", "False",
                     "--semi-tone-shift", "0",
                     "--checkpoint", str(SVC_CKPT),
                     "--config", str(SVC_CFG),
                     "--fp16", "True"], timeout=3600, cwd=SEEDVC, env=env)
            cands = sorted(svc_dir.glob("*.wav"))
            if r.returncode != 0 or not cands:
                info["error"] = "svc failed"
                info["tail"] = (r.stdout or "")[-500:] + (r.stderr or "")[-400:]
                print(json.dumps(info, ensure_ascii=False))
                return 1
            svc = cands[0]
        finally:
            try:
                info["window_close"] = gpu_window.close_window()
            except Exception as ex:  # noqa: BLE001
                info["window_close_error"] = repr(ex)
    info["svc"] = str(svc)

    # ── 1.5 清晰增强（10-22 那条链的固定步骤；纯 python，不依赖 WSL）──
    if args.clarity > 0:
        enh = work / "clarity.wav"
        r = run([sys.executable, ROOT / "tools" / "wsl_clarity_enhance.py",
                 svc, lead, enh, "--gain", str(args.clarity)], timeout=1800)
        if r.returncode == 0 and enh.is_file():
            svc = enh
            info["clarity"] = args.clarity
        else:
            info["clarity_error"] = ((r.stdout or "")[-200:] + (r.stderr or "")[-200:])

    # ── 2. 门控（可选）＋柔化 DSP ＋ 三轨混回 ──────────────────
    sys.path.insert(0, str(ROOT / "tools"))
    variants = ["on", "off"] if args.gate == "both" else [args.gate]
    outputs = []
    run_dir.mkdir(parents=True, exist_ok=True)
    for v in variants:
        src = svc
        if v == "on":
            gated = work / "gated.wav"
            r = run([sys.executable, ROOT / "tools" / "svc_gate.py",
                     lead, svc, gated], timeout=1800)
            if r.returncode != 0 or not gated.is_file():
                info.setdefault("gate_error", (r.stdout or "")[-300:] + (r.stderr or "")[-300:])
                continue
            src = gated
        dsp = work / f"dsp_{args.preset}_{v}.wav"
        r = run([sys.executable, ROOT / "tools" / "cover_v3_dsp.py",
                 src, dsp, "--preset", args.preset], timeout=600)
        if r.returncode != 0 or not dsp.is_file():
            info.setdefault("dsp_error", (r.stderr or "")[-300:])
            continue
        tag = "门控" if v == "on" else "无门控"
        out = run_dir / f"成品_{args.name}_seedvc_{args.preset}_{tag}.wav"
        r = run([sys.executable, ROOT / "tools" / "wsl_mix3.py",
                 dsp, backing, bgm, out,
                 "--lead-gain", str(args.lead_gain),
                 "--backing-gain", str(args.backing_gain),
                 "--bgm-gain", str(args.bgm_gain)], timeout=600)
        if r.returncode == 0 and out.is_file():
            outputs.append(str(out))
    # 分层留存，便于事后查
    for nm, p in (("干声", lead), ("和声", backing), ("伴奏", bgm),
                  ("AI主唱", svc)):
        try:
            import shutil
            shutil.copy2(p, run_dir / f"{nm}_{args.name}.wav")
        except Exception:  # noqa: BLE001
            pass
    info.update({"ok": bool(outputs), "outputs": outputs, "out_dir": str(run_dir)})
    print(json.dumps(info, ensure_ascii=False))
    return 0 if outputs else 1


if __name__ == "__main__":
    raise SystemExit(main())
