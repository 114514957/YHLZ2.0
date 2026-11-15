"""一首歌跑完整条投产链路（2026-11-02 设计，2026-11-06 接线）。

S1 规范化 → S2 Kim 人声分离 → S3 MDX 卡拉OK（audio-separator 原版）→
S4 Seed-VC → S5 柔化 e → S6 三轨混回 → S7 归档 + 说明。

设计依据：docs/报告/翻唱链路_投产设计_20261102.md（台账 1064/1066）。
出口 JSON 里必须带 `sep`，工作台靠它显示用的是哪条分轨链。

用法：
    python tools/cover_produce.py "音频素材/翻唱投入/xxx.m4a" [--voice bright] [--presets e]
    python tools/cover_produce.py ... --dry-run     # 只走 S1-S3
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
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
GSV5_PY = ROOT / "venv-gsv5" / "Scripts" / "python.exe"
OUT_ROOT = ROOT / "音频素材" / "翻唱产出"


def _run(cmd: list[str], *, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, cwd=str(ROOT),
                          env=env, creationflags=0x08000000)


def _json_tail(text: str) -> dict | None:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and '"ok"' in line:
            try:
                return json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return None


def _slug(name: str) -> str:
    keep = [c for c in name if c.isalnum() or c in "-_"]
    return "".join(keep)[:40] or "song"


def _say(stage: str, **kw) -> None:
    """每个阶段结束就打印一行（flush），供上层流式读取实时进度。

    2026-11-13：原来整个成功路径**只在最后打一个 JSON**，所以上层哪怕改成流式读文件，
    中途也永远是空的（实测 150 秒 0 字节）。要能看进度，必须这里逐阶段吐。
    """
    try:
        print(json.dumps({"stage": stage, **kw}, ensure_ascii=False), flush=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--voice", default="bright")
    ap.add_argument("--presets", default="e")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--dry-run", action="store_true", help="只跑 S1-S3 分轨，不做 Seed-VC")
    ap.add_argument("--no-prep", action="store_true",
                    help="跳过去混响/谱减预处理（默认做，2026-11-13 起）")
    args = ap.parse_args()

    tgt = Path(args.target).resolve()
    info: dict = {"ok": False, "target": str(tgt), "stages": {}}
    if not tgt.is_file():
        info["error"] = f"目标文件不存在：{args.target}"
        print(json.dumps(info, ensure_ascii=False))
        return 2

    ts = time.strftime("%Y%m%d-%H%M%S")
    name = _slug(args.name or tgt.stem)
    work = ROOT / "cache" / "sing" / f"produce_{ts}"
    stems = work / "stems"
    work.mkdir(parents=True, exist_ok=True)
    stems.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ── S1 规范化：44.1k / stereo / wav（原文件不动）──────────────────
    try:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        norm = work / "input.wav"
        r = _run([ff, "-y", "-i", str(tgt), "-ar", "44100", "-ac", "2", str(norm)],
                 timeout=600)
        if r.returncode != 0 or not norm.is_file():
            info["stages"]["S1"] = {"ok": False, "tail": (r.stderr or "")[-300:]}
            print(json.dumps(info, ensure_ascii=False))
            return 1
        info["stages"]["S1"] = {"ok": True, "file": str(norm),
                                "elapsed_s": round(time.time() - t0, 1)}
        _say("S1", ok=True, elapsed_s=info["stages"]["S1"]["elapsed_s"])
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"S1 {type(exc).__name__}: {exc}"
        print(json.dumps(info, ensure_ascii=False))
        return 1

    # ── S2 Kim 人声分离（脚本自带唱窗）────────────────────────────────
    t = time.time()
    r = _run([str(VENV_PY), str(ROOT / "tools" / "svc_kim_split.py"),
              str(norm), str(stems)], timeout=7200)
    s2 = _json_tail(r.stdout) or {"ok": False, "tail": (r.stderr or "")[-400:]}
    s2["elapsed_s"] = round(time.time() - t, 1)
    info["stages"]["S2"] = s2
    _say("S2", ok=bool(s2.get("ok")), elapsed_s=s2.get("elapsed_s"))
    if not s2.get("ok"):
        info["error"] = "S2 kim split failed"
        print(json.dumps(info, ensure_ascii=False))
        return 1
    vocals = Path(s2["vocals"])
    instrumental = Path(s2["instrumental"])

    # ── S2.5 电平归一（2026-11-13，老爹「干声分离需要调整」）────────────
    # 实测：RoFormer 出来的 vocals 峰值 -0.0 dB、instrumental +0.8 dB（**已削顶 10 个样本**）。
    # 顶满刻度进 Seed-VC 没有余量，换声容易破音；伴奏溢出了还会把失真带进成片。
    # 这里统一按峰值压到 -3 dBFS（只降不升），给下游留 headroom。
    t = time.time()
    r = _run([str(VENV_PY), str(ROOT / "tools" / "svc_stage_level.py"),
              str(stems), "--peak-db", "-3"], timeout=600)
    info["stages"]["S2.5"] = {"ok": r.returncode == 0,
                              "tail": (r.stdout or "")[-500:],
                              "elapsed_s": round(time.time() - t, 1)}
    _say("S2.5", ok=r.returncode == 0, elapsed_s=info["stages"]["S2.5"]["elapsed_s"])

    # ── S2.6 干声预处理（2026-11-13，老爹「以后干声分离完要做预处理」）──────
    # 分离模型只分"人声/伴奏"，不分"直达声/混响"；混响会让换声后又糊又散。
    # 这里用仓库里的 dereverb 模型（871MB）去混响，再做轻参考谱减压伴奏残留。
    # 失败不致命：退回未预处理的干声，流程继续（记 S2.6 失败原因）。
    if getattr(args, "no_prep", False):
        info["stages"]["S2.6"] = {"ok": True, "skipped": True}
        _say("S2.6", ok=True, skipped=True)
    else:
        t = time.time()
        _clean = stems / "vocals_clean.wav"
        r = _run([str(VENV_PY), str(ROOT / "tools" / "svc_prep_vocal.py"),
                  str(vocals), str(instrumental), str(_clean)], timeout=3600)
        _ok = (r.returncode == 0 and _clean.is_file())
        info["stages"]["S2.6"] = {"ok": _ok, "elapsed_s": round(time.time() - t, 1),
                                  "tail": (r.stdout or "")[-400:]}
        _say("S2.6", ok=_ok, elapsed_s=info["stages"]["S2.6"]["elapsed_s"])
        if _ok:
            # 预处理后的干声顶替原干声，后续 S3 与换声都用它
            shutil.copy2(_clean, vocals)
        else:
            info["error"] = (info.get("error") or "") + " S2.6 预处理失败(已退回)"
    if r.returncode != 0:
        # 只是电平，不致命：记下来继续（别把整单搞挂）
        info["error"] = (info.get("error") or "") + " S2.5 归一失败(已忽略)"

    # ── S3 MDX 卡拉OK（audio-separator 原版，跑在 venv-gsv5）──────────
    t = time.time()
    r = _run([str(GSV5_PY), "-X", "utf8", str(ROOT / "tools" / "svc_mdx_karaoke.py"),
              str(vocals), str(stems)], timeout=5400)
    s3 = _json_tail(r.stdout) or {"ok": False, "tail": (r.stderr or "")[-400:]}
    s3["elapsed_s"] = round(time.time() - t, 1)
    info["stages"]["S3"] = s3
    _say("S3", ok=bool(s3.get("ok")), elapsed_s=s3.get("elapsed_s"))
    if not s3.get("ok"):
        info["error"] = "S3 mdx karaoke failed（不静默降级，降级需显式实现）"
        info["sep"] = "native-kim+mdx-failed"
        print(json.dumps(info, ensure_ascii=False))
        return 1
    sep = s3.get("sep") or "native-kim+mdx"
    info["sep"] = sep

    # cover_rebuild 需要 lead/backing/bgm 三轨
    shutil.copy2(instrumental, stems / "bgm.wav")

    if args.dry_run:
        info.update({"ok": True, "dry_run": True, "stems": str(stems),
                     "elapsed_s": round(time.time() - t0, 1)})
        print(json.dumps(info, ensure_ascii=False))
        return 0

    # ── S4-S6 Seed-VC + 柔化 e + 三轨混回（cover_rebuild 自带唱窗）────
    t = time.time()
    cmd = [str(VENV_PY), str(ROOT / "tools" / "cover_rebuild.py"),
           "--stems", str(stems), "--name", name,
           "--preset", args.presets, "--gate", "both"]
    r = _run(cmd, timeout=10800)
    s4 = _json_tail(r.stdout) or {"ok": False, "tail": (r.stderr or "")[-500:]}
    s4["elapsed_s"] = round(time.time() - t, 1)
    info["stages"]["S4-S6"] = s4
    _say("S4-S6", ok=bool(s4.get("ok")), elapsed_s=s4.get("elapsed_s"))
    if not s4.get("ok"):
        info["error"] = "S4-S6 rebuild failed"
        print(json.dumps(info, ensure_ascii=False))
        return 1

    out_dir = Path(s4.get("out_dir") or "")
    final = (s4.get("outputs") or [None])[0]

    # ── S7 归档：说明 + 可选拷贝到指定目录 ────────────────────────────
    try:
        if out_dir.is_dir():
            note = out_dir / "说明.txt"
            note.write_text(
                f"歌名：{name}\n"
                f"来源：{tgt}\n"
                f"时间：{ts}\n"
                f"链路：S1 规范化 → S2 Kim(MSST) → S3 MDX(audio-separator) → "
                f"S4 Seed-VC → S5 柔化 {args.presets} → S6 混音 1.0/1.5/0.7\n"
                f"分轨链：{sep}\n"
                f"成品：{final}\n",
                encoding="utf-8")
            info["note"] = str(note)
    except Exception as exc:  # noqa: BLE001
        info["note_error"] = f"{type(exc).__name__}: {exc}"

    if args.out_dir:
        try:
            dest = Path(args.out_dir).resolve()
            dest.mkdir(parents=True, exist_ok=True)
            if final:
                shutil.copy2(final, dest / Path(final).name)
                info["copied_to"] = str(dest / Path(final).name)
        except Exception as exc:  # noqa: BLE001
            info["copy_error"] = f"{type(exc).__name__}: {exc}"

    info.update({"ok": bool(final), "out_dir": str(out_dir), "final": final,
                 "elapsed_s": round(time.time() - t0, 1)})
    print(json.dumps(info, ensure_ascii=False))
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
