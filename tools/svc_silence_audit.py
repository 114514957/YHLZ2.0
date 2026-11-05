"""同一首歌新旧两版：在「源干声无唱段」里 AI 主唱还剩多少能量。

结论口径：以卡拉OK lead 的有声掩码为基准（pyin），比较
  ① 旧版（demucs 两轨输入）SVC 输出 / 成品
  ② 新版（卡拉OK三轨输入）SVC 输出 / 成品
在无唱段里的 RMS —— 越低说明「器乐段硬唱」越少。
"""
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

YH = Path(r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH")
LEAD = YH / "cache" / "sing" / "stem_heian" / "lead.wav"
OLD_SVC = YH / "cache" / "svc_test" / "seedvc_e_222112.wav"
NEW_SVC = sorted((YH / "cache" / "sing").glob("rebuild_*/svc/*.wav"))[-1]
OLD_MIX = YH / "音频素材" / "翻唱产出" / "20261030-222112_黑夜梦想家_seedvc" / "成品_黑夜梦想家_seedvc_e.wav"
NEW_DIR = sorted((YH / "音频素材" / "翻唱产出").glob("*黑夜梦想家_3stem"))[-1]


def load(p):
    y, sr = sf.read(str(p), dtype="float32", always_2d=True)
    return y.mean(1), sr


def silent_mask(lead, sr):
    y = librosa.resample(lead, orig_sr=sr, target_sr=22050)
    f0, voiced, prob = librosa.pyin(y, fmin=70, fmax=1000, sr=22050,
                                    frame_length=1024, hop_length=256,
                                    fill_na=np.nan)
    return ~(voiced & np.isfinite(f0) & (prob > 0.5))


def stat(name, path, mask, hop_ratio):
    x, sr = load(path)
    n = min(len(x), int(len(mask) * hop_ratio * 22050))
    x = x[:n]
    fr = int(round(0.080 * sr))          # 80ms 帧
    nf = n // fr
    e = np.array([np.sqrt(np.mean(x[i * fr:(i + 1) * fr] ** 2)) for i in range(nf)])
    # 把 pyin 掩码重采样到 80ms 帧
    idx = np.linspace(0, len(mask) - 1, nf).astype(int)
    m = mask[idx]
    quiet = 20 * np.log10(max(float(np.mean(e[m])), 1e-9)) if m.any() else float("nan")
    loud = 20 * np.log10(max(float(np.mean(e[~m])), 1e-9)) if (~m).any() else float("nan")
    print("%-22s 无唱段 RMS=%7.1f dB   有唱段 RMS=%7.1f dB   差=%5.1f dB"
          % (name, quiet, loud, loud - quiet), flush=True)


def main():
    lead, sr = load(LEAD)
    mask = silent_mask(lead, sr)
    hr = 22050 / sr
    print("源 lead: %.1fs，无唱帧占比 %.1f%%" % (len(lead) / sr, 100 * mask.mean()))
    stat("旧 SVC 输出", OLD_SVC, mask, hr)
    stat("新 SVC 输出", NEW_SVC, mask, hr)
    stat("旧 成品混音", OLD_MIX, mask, hr)
    for f in sorted(NEW_DIR.glob("成品*.wav")):
        stat("新 成品 " + ("门控" if "门控" in f.name else "无门控"), f, mask, hr)


if __name__ == "__main__":
    sys.exit(main())
