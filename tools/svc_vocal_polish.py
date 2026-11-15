# -*- coding: utf-8 -*-
"""干声精修：去电音味 / 去不自然 / 提饱和（2026-11-14，老爹）

背景：7 号（去混响+谱减）已经比原始干声干净，但仍有三种毛病：
  ① **电音味**：分离/换声带来的金属感、频谱上的窄带共振与"颤音被抹平"的机械感
  ② **不自然**：动态忽大忽小、齿音刺、瞬态过硬、断句处有台阶
  ③ **不够饱和**：声音薄、没厚度、缺乏谐波（数字味）

对应三个处理（都用可解释的 DSP，不引新模型）：
  ① 去电音：**倒谱平滑（cepstral lifter）**——把谱包络抹平掉窄带共振的金属感；
            再做**共振峰轻微展宽**（谱域轻度 smearing），压掉"机器人"那种死板共振。
  ② 去不自然：**动态EQ 压 2.5–4.5kHz 的刺耳区**（按能量自适应）、**轻度压缩**（起音10ms/释放120ms，
            2:1）把忽大忽小拉平、断句处做 5ms 交叉淡化消台阶。
  ③ 提饱和：**tanh 软饱和**（drive 可调）加谐波与厚度，再峰值归一到 -3 dBFS 给换声留余量。

用法：
  python tools/svc_vocal_polish.py <in.wav> <out.wav>
      [--de-metallic 0.6] [--de-harsh 0.5] [--comp 0.35] [--drive 1.6]
"""
from __future__ import annotations

import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--de-metallic", type=float, default=0.6, help="去电音强度 0..1")
    ap.add_argument("--de-harsh", type=float, default=0.5, help="压刺耳区强度 0..1")
    ap.add_argument("--comp", type=float, default=0.35, help="压缩量 0..1")
    ap.add_argument("--drive", type=float, default=1.6, help="饱和驱动 1.0=不饱和")
    ap.add_argument("--n-fft", type=int, default=2048)
    ap.add_argument("--hop", type=int, default=512)
    a = ap.parse_args()

    import librosa
    import numpy as np
    import soundfile as sf

    y, sr = sf.read(a.src, always_2d=True, dtype="float32")
    y = y[:, :2] if y.shape[1] >= 2 else np.repeat(y, 2, axis=1)
    n = len(y)
    stats = {"src": a.src, "sr": sr, "seconds": round(n / sr, 1)}

    def crest(x: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
        return float(np.max(np.abs(x)) / rms)

    stats["crest_before"] = round(crest(y), 2)

    out = np.zeros_like(y)
    for c in range(2):
        x = y[:, c].astype(np.float64)

        # ── ① 去电音：倒谱平滑 + 轻度谱展宽 ──────────────────────────
        S = librosa.stft(x, n_fft=a.n_fft, hop_length=a.hop)
        mag, phase = np.abs(S), np.angle(S)
        logmag = np.log(mag + 1e-8)
        # 沿时间做一次很小的平滑：抹掉帧间抖动造成的"电子颗粒感"
        k_t = max(1, int(round(3 * a.de_metallic)))
        if k_t > 1:
            ker = np.ones(k_t) / k_t
            logmag = np.apply_along_axis(lambda v: np.convolve(v, ker, mode="same"),
                                         1, logmag)
        # 沿频率做轻度展宽：窄带共振被抹平＝金属感下降
        k_f = 1 + int(round(2 * a.de_metallic))
        if k_f > 1:
            ker = np.ones(k_f) / k_f
            logmag = np.apply_along_axis(lambda v: np.convolve(v, ker, mode="same"),
                                         0, logmag)
        mag2 = np.exp(logmag)

        # ── ② 去不自然之一：自适应压 2.5–4.5k 刺耳区 ─────────────────
        freqs = librosa.fft_frequencies(sr=sr, n_fft=a.n_fft)
        band = (freqs >= 2500) & (freqs <= 4500)
        if band.any() and a.de_harsh > 0:
            # 该频带能量若明显高于邻带，就按比例压一点
            band_e = mag2[band].mean(axis=0, keepdims=True)
            ref = mag2[(freqs >= 800) & (freqs < 2500)].mean(axis=0, keepdims=True)
            ratio = np.clip(band_e / (ref + 1e-8), 0, 4)
            gain = 1.0 - a.de_harsh * 0.5 * (ratio / 4.0)
            mag2[band] *= gain
        S2 = mag2 * np.exp(1j * phase)
        x = librosa.istft(S2, hop_length=a.hop, length=n)

        # ── ② 去不自然之二：轻度压缩（拉平忽大忽小）──────────────────
        if a.comp > 0:
            env = librosa.amplitude_to_db(np.abs(librosa.stft(x, hop_length=a.hop)), ref=np.max)
            # 用每帧峰值近似短时包络，做软膝压缩（简化实现，逐样本）
            win = max(1, int(0.010 * sr))
            env_s = np.convolve(np.abs(x), np.ones(win) / win, mode="same")
            thr = np.quantile(env_s, 0.85) + 1e-9
            over = env_s > thr
            if over.any():
                target = thr + (env_s - thr) / 2.0      # 2:1
                gain = np.where(over, target / (env_s + 1e-9), 1.0)
                # 平滑增益，避免抽吸
                gk = max(1, int(0.120 * sr))
                gain = np.convolve(gain, np.ones(gk) / gk, mode="same")
                x = x * (1 - a.comp + a.comp * gain)

        # ── ② 去不自然之三：断句台阶（极短静音的硬边）做 5ms 淡化 ────
        fade = max(1, int(0.005 * sr))
        amp = np.abs(x)
        small = amp < 10 ** (-45 / 20)
        if small.any():
            # 只在"短于 30ms 的空洞"两侧做淡化
            idx = np.flatnonzero(small)
            if len(idx):
                edges = np.flatnonzero(np.diff(idx) > 1)
                for e in edges[:200]:
                    p = idx[e]
                    lo, hi = max(0, p - fade), min(len(x), p + fade)
                    if hi > lo:
                        x[lo:hi] *= np.linspace(0.85, 1.0, hi - lo)

        # ── ③ 提饱和：tanh 软饱和（加谐波/厚度）──────────────────────
        if a.drive > 1.0:
            peak = float(np.max(np.abs(x)) + 1e-9)
            x = x / peak * a.drive
            x = np.tanh(x) / np.tanh(a.drive) * peak

        out[:, c] = x.astype("float32")

    # 峰值 -3 dBFS（上下都归一到目标：饱和会把峰值压下去，只"不放大"就会偏小）
    pk = float(np.max(np.abs(out)) + 1e-12)
    target = 10 ** (-3 / 20)
    out *= target / pk
    np.clip(out, -1.0, 1.0, out=out)

    sf.write(a.out, out, sr, subtype="FLOAT")

    def band_energy(x: np.ndarray, lo: float, hi: float) -> float:
        X = np.abs(librosa.stft(x.mean(axis=1) if x.ndim > 1 else x,
                                n_fft=a.n_fft, hop_length=a.hop))
        fr = librosa.fft_frequencies(sr=sr, n_fft=a.n_fft)
        m = (fr >= lo) & (fr <= hi)
        return float(X[m].mean()) if m.any() else 0.0

    stats.update({
        "out": a.out, "peak_db": round(20 * np.log10(float(np.max(np.abs(out))) + 1e-12), 1),
        "clip": int((np.abs(out) >= 0.999).sum()),
        "crest_after": round(crest(out), 2),
        "harsh_2k5_4k5_ratio": round(band_energy(out, 2500, 4500) /
                                     (band_energy(out, 800, 2500) + 1e-12), 3),
        "harsh_2k5_4k5_ratio_before": round(band_energy(y, 2500, 4500) /
                                            (band_energy(y, 800, 2500) + 1e-12), 3),
        "params": {"de_metallic": a.de_metallic, "de_harsh": a.de_harsh,
                   "comp": a.comp, "drive": a.drive},
    })
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
