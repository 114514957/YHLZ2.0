"""UVR MDX-Net 卡拉OK 分轨（投产版：audio-separator 原版）。

台账 1064 的结论：自写 onnxruntime 版对不上验收（主唱 corr 0.28 / 和声 0.89），
**MDX 这一段必须用 audio-separator 原版**（vocals corr 0.9988 / instrumental 0.9997）。
所以默认走 audio-separator；旧的逐行复刻实现保留在 `--legacy` 里，只作对照实验。

用法：
    python tools/svc_mdx_karaoke.py <vocals.wav> <out_dir>
    python tools/svc_mdx_karaoke.py <vocals.wav> <out_dir> --legacy

输出（两种模式一致）：`lead.wav`（主唱）、`backing.wav`（和声/伴唱）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "cache" / "msst" / "UVR_MDXNET_KARA_2.onnx"
SR = 44100


def _ensure_ffmpeg_on_path() -> None:
    """audio-separator 用 `ffmpeg -version` 探测，需要 PATH 里有名叫 ffmpeg.exe 的文件。

    本机没有系统级 ffmpeg，用 imageio 自带的那份；它叫
    `ffmpeg-win-x86_64-v7.1.exe`，所以建一个硬链接别名 `cache/bin/ffmpeg.exe`。
    """
    import os
    import shutil

    candidates: list[Path] = []
    try:
        import imageio_ffmpeg

        candidates.append(Path(imageio_ffmpeg.get_ffmpeg_exe()))
    except Exception:  # noqa: BLE001
        pass
    # venv-gsv5 里没装 imageio，直接用运行时 .venv 里那份（台账 1092 的路径）
    candidates.extend((ROOT / ".venv" / "Lib" / "site-packages" /
                       "imageio_ffmpeg" / "binaries").glob("ffmpeg*.exe"))
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(Path(which))
    exe = next((p for p in candidates if p and p.is_file()), None)
    if exe is None:
        return
    bin_dir = ROOT / "cache" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    alias = bin_dir / "ffmpeg.exe"
    if not alias.exists():
        try:
            os.link(exe, alias)  # 同卷硬链接，不占额外空间
        except OSError:
            shutil.copy2(exe, alias)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("FFMPEG_BINARY", str(alias))


def _run_audio_separator(src: Path, out: Path, model: Path) -> dict:
    _ensure_ffmpeg_on_path()
    from audio_separator.separator import Separator

    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    sep = Separator(
        model_file_dir=str(model.parent),
        output_dir=str(out),
        output_format="WAV",
        sample_rate=SR,
    )
    sep.load_model(model.name)
    files = sep.separate(str(src)) or []
    produced = [out / str(f) if not Path(str(f)).is_absolute() else Path(str(f))
                for f in files]
    produced = [p for p in produced if p.is_file()]

    def _pick(kind: str):
        # audio-separator 的命名是 `<输入名>_(<Stem>)_<模型>.wav`，输入名本身可能
        # 就叫 vocals，所以必须按 `(Vocals)` / `(Instrumental)` 标记匹配。
        for p in produced:
            low = p.name.lower()
            if kind == "vocals" and "(vocals)" in low:
                return p
            if kind == "instrumental" and "(instrumental)" in low:
                return p
        return None

    lead, back = _pick("vocals"), _pick("instrumental")
    if lead is None or back is None:
        return {"ok": False, "engine": "audio-separator",
                "error": "expected vocals/instrumental outputs",
                "files": [p.name for p in produced],
                "elapsed_s": round(time.time() - t0, 1)}
    shutil.copy2(lead, out / "lead.wav")
    shutil.copy2(back, out / "backing.wav")
    return {"ok": True, "engine": "audio-separator",
            "lead": str(out / "lead.wav"), "backing": str(out / "backing.wav"),
            "sep": "native-kim+mdx",
            "files": [p.name for p in produced],
            "elapsed_s": round(time.time() - t0, 1)}


def _run_legacy(src: Path, out: Path, model: Path, overlap: float) -> dict:
    """旧的自写 onnxruntime 复刻（不投产，只做对照；corr 对不上验收）。"""
    import onnxruntime as ort
    import soundfile as sf

    sys.path.insert(0, str(ROOT / "tools"))
    from svc_mdx_karaoke_legacy import demix, load  # type: ignore

    sess = ort.InferenceSession(str(model), providers=["CUDAExecutionProvider",
                                                       "CPUExecutionProvider"])
    x = load(src)
    lead = demix(x, sess, overlap)
    back = x - lead
    out.mkdir(parents=True, exist_ok=True)
    sf.write(str(out / "lead.wav"), lead.T, SR, subtype="FLOAT")
    sf.write(str(out / "backing.wav"), back.T, SR, subtype="FLOAT")
    return {"ok": True, "engine": "legacy-ort", "lead": str(out / "lead.wav"),
            "backing": str(out / "backing.wav"), "sep": "native-kim+mdx-legacy",
            "dur_s": round(x.shape[1] / SR, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("out_dir")
    ap.add_argument("--model", default=str(MODEL))
    ap.add_argument("--legacy", action="store_true",
                    help="用旧的自写 onnxruntime 版（对照实验，不投产）")
    ap.add_argument("--overlap", type=float, default=0.25)
    a = ap.parse_args()
    src, out, model = Path(a.vocals).resolve(), Path(a.out_dir).resolve(), Path(a.model)
    if not src.is_file():
        print(json.dumps({"ok": False, "error": f"missing {src}"}, ensure_ascii=False))
        return 2
    if not model.is_file():
        print(json.dumps({"ok": False, "error": f"missing model {model}"},
                         ensure_ascii=False))
        return 2
    try:
        if a.legacy:
            info = _run_legacy(src, out, model, a.overlap)
        else:
            info = _run_audio_separator(src, out, model)
    except Exception as exc:  # noqa: BLE001
        info = {"ok": False, "engine": "audio-separator" if not a.legacy else "legacy-ort",
                "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(info, ensure_ascii=False))
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
