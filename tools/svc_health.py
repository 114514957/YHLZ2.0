"""翻唱成品客观体检：峰值/削波/RMS/亮度(8k+)/谱质心/立体声宽度。

用法: python svc_health.py [产出目录根]
输出每首一行；与听感相关的指标里，削波率和 8k+ 最值得看。
"""
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH\音频素材\翻唱产出")


def metrics(p: Path):
    y, sr = librosa.load(str(p), sr=None, mono=False)
    if y.ndim == 1:
        y = y[None, :]
    mono = y.mean(0)
    peak = float(np.max(np.abs(y)))
    clip = int(np.sum(np.abs(y) >= 0.9985))
    rms = float(np.sqrt(np.mean(mono ** 2)))
    # 高频能量占比（>8k）
    S = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    hi = S[freqs >= 8000].sum()
    tot = S.sum() + 1e-12
    centroid = float(np.sum(freqs[:, None] * S) / tot)
    width = 0.0
    if y.shape[0] == 2:
        l, r = y[0], y[1]
        width = float(np.mean(np.abs(l - r)) / (np.mean(np.abs(l + r)) + 1e-9))
    return dict(sr=sr, dur=len(mono) / sr, peak=peak, clip=clip,
                clip_pct=100.0 * clip / max(1, y.size),
                rms_db=20 * np.log10(rms + 1e-9),
                hi_pct=100.0 * hi / tot, centroid=centroid, width=width)


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    rows = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("成品*")):
            try:
                m = metrics(f)
            except Exception as e:  # noqa: BLE001
                print("%-46s ERR %r" % (f.name, e))
                continue
            rows.append((d.name, f.name, m))
            print("%-34s %-34s sr=%-6d %5.1fs peak=%.3f clip=%d(%.3f%%) "
                  "RMS=%6.1fdB 8k+=%4.2f%% cen=%4.0f w=%.2f"
                  % (d.name[:34], f.name[:34], m["sr"], m["dur"], m["peak"],
                     m["clip"], m["clip_pct"], m["rms_db"], m["hi_pct"],
                     m["centroid"], m["width"]), flush=True)


if __name__ == "__main__":
    main()
