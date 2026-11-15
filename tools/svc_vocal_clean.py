# -*- coding: utf-8 -*-
"""干声预处理：参考谱减 + 高通 + 谱门限（2026-11-13，老爹「分离不干净，以后干声分离完要做预处理」）

问题：Kim/RoFormer 分出来的 vocals 里仍混着伴奏（尤其鼓、贝斯、弦乐的谐波），
听起来"不干净"。换声（Seed-VC）会把这些残留也一并"唱"出来，所以必须在换声前清。

做法（不需要歌词、不需要额外模型，纯 DSP）：
  1. **高通 70 Hz**：切掉隆隆声/低频泄漏
  2. **参考谱减**：拿 instrumental 当参考，在 STFT 域按"干声-伴奏的谱相干"估计泄漏量，
     只在相干高的时频点做减法（α 控制力度），并留 β 比例的底，避免过度减薄
  3. **谱门限降噪**：用最安静 10% 帧估噪声底，按 oversubtraction 压一遍
  4. 输出 + 打报告（与伴奏的相关性、被压掉的能量占比）

用法：
  python tools/svc_vocal_clean.py <vocals.wav> <instrumental.wav> <out.wav>
        [--alpha 0.8] [--floor 0.15] [--hp 70]
"""
from __future__ import annotations

import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("instrumental")
    ap.add_argument("out")
    ap.add_argument("--alpha", type=float, default=0.8, help="谱减力度（0=不减，1=全减）")
    ap.add_argument("--floor", type=float, default=0.15, help="每个时频点保留的底（避免过薄）")
    ap.add_argument("--hp", type=float, default=70.0, help="高通截止 Hz")
    ap.add_argument("--n-fft", type=int, default=2048)
    ap.add_argument("--hop", type=int, default=512)
    args = ap.parse_args()

    import librosa
    import numpy as np
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    v, sr = sf.read(args.vocals, always_2d=True, dtype="float32")
    i, sr2 = sf.read(args.instrumental, always_2d=True, dtype="float32")
    if sr != sr2:
        sys.exit("两轨采样率不同：%d vs %d" % (sr, sr2))
    n = min(len(v), len(i))
    v, i = v[:n], i[:n]

    # 1) 高通
    sos = butter(2, args.hp / (sr / 2), btype="highpass", output="sos")
    v_hp = np.stack([sosfilt(sos, v[:, c]) for c in range(v.shape[1])], axis=1)

    # 2) 参考谱减（逐声道）
    out = np.zeros_like(v_hp)
    stats = []
    for c in range(v.shape[1]):
        V = librosa.stft(v_hp[:, c], n_fft=args.n_fft, hop_length=args.hop)
        I = librosa.stft(i[:, c], n_fft=args.n_fft, hop_length=args.hop)
        mv, mi = np.abs(V), np.abs(I)
        # 谱相干（逐频带、按时间统计）：相干高＝该频带里人声与伴奏同源，多半是泄漏
        num = np.abs(np.mean(V * np.conj(I), axis=1))
        den = (np.mean(mv, axis=1) * np.mean(mi, axis=1)) + 1e-9
        rho = np.clip(num / den, 0.0, 1.0)[:, None]
        # 减法：把"与伴奏相干"的那部分按 α 减掉，但保留 floor 底
        sub = mv - args.alpha * rho * mi
        mag = np.maximum(sub, args.floor * mv)
        V2 = mag * np.exp(1j * np.angle(V))
        out[:, c] = librosa.istft(V2, hop_length=args.hop, length=n)
        before_rms = float(np.sqrt((v_hp[:, c] ** 2).mean()) + 1e-12)
        after_rms = float(np.sqrt((out[:, c] ** 2).mean()) + 1e-12)
        stats.append({"ch": c, "rho_mean": round(float(rho.mean()), 3),
                      "rms_db_before": round(20 * np.log10(before_rms), 1),
                      "rms_db_after": round(20 * np.log10(after_rms), 1),
                      "removed_pct": round(100 * (1 - after_rms / before_rms), 1)})

    # 3) 谱门限降噪（单遍，用安静帧估底）
    def denoise(x):
        S = librosa.stft(x, n_fft=args.n_fft, hop_length=args.hop)
        mag, phase = np.abs(S), np.angle(S)
        frame_e = mag.mean(axis=0)
        q = np.quantile(frame_e, 0.10)
        quiet = frame_e <= max(q, 1e-6)
        noise = mag[:, quiet].mean(axis=1, keepdims=True) if quiet.any() else mag.min(axis=1, keepdims=True)
        clean = np.maximum(mag - 1.2 * noise, 0.05 * mag)
        return librosa.istft(clean * np.exp(1j * phase), hop_length=args.hop, length=len(x))

    out = np.stack([denoise(out[:, c]) for c in range(out.shape[1])], axis=1)

    # 4) 峰值归一 + 限幅（给 Seed-VC 留 3dB 余量）
    pk = float(np.max(np.abs(out)) + 1e-12)
    target = 10 ** (-3 / 20)
    if pk > target:
        out *= target / pk
    np.clip(out, -1.0, 1.0, out=out)
    sf.write(args.out, out, sr, subtype="FLOAT")

    def corr(a, b):
        a, b = a.mean(axis=1), b.mean(axis=1)
        return float(np.corrcoef(a, b)[0, 1])

    info = {
        "ok": True, "out": args.out, "sr": sr, "seconds": round(n / sr, 1),
        "alpha": args.alpha, "floor": args.floor, "hp": args.hp,
        "corr_with_instrumental_before": round(corr(v, i), 3),
        "corr_with_instrumental_after": round(corr(out, i), 3),
        "peak_db": round(20 * np.log10(float(np.max(np.abs(out))) + 1e-12), 1),
        "clip": int((np.abs(out) >= 0.999).sum()),
        "channels": stats,
    }
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
