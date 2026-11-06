"""UVR MDX-Net 卡拉OK 推理（按 audio-separator / UVR 的 demix 流程逐行照搬）。

对照实现来源：`audio_separator/separator/architectures/mdx_separator.py`
（Waveform normalize → 时域分块 → STFT(前 3 bin 置零) → 模型 → iSTFT → 汉宁窗重叠相加）。
模型：`cache/msst/UVR_MDXNET_KARA_2.onnx`（输入 [B,4,2048,256]）。

用法:
  python tools/svc_mdx_karaoke.py <vocals.wav> <out_dir> [--overlap 0.25]
输出: <out_dir>/lead.wav（主唱）、<out_dir>/backing.wav（和声 = 输入 - 主唱）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SR = 44100
N_FFT = 4096
HOP = 1024
DIM_F = 2048
SEGMENT = 256                     # dim_t
TRIM = N_FFT // 2
CHUNK = HOP * (SEGMENT - 1)       # 261120
GEN = CHUNK - 2 * TRIM
MAX_PEAK = 0.9
MIN_PEAK = 0.95

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "cache" / "msst" / "UVR_MDXNET_KARA_2.onnx"


def load(p: Path) -> np.ndarray:
    y, sr = sf.read(str(p), dtype="float32", always_2d=True)
    if sr != SR:
        import librosa
        y = librosa.resample(y.T, orig_sr=sr, target_sr=SR).T
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    return np.ascontiguousarray(y[:, :2].T)


def to_spec(x: np.ndarray) -> torch.Tensor:
    """(2,N) → (1,4,F,T)，通道顺序 L_real,L_imag,R_real,R_imag，取前 DIM_F 个频点。"""
    w = torch.hann_window(N_FFT, periodic=True)
    S = torch.stft(torch.from_numpy(x), N_FFT, HOP, window=w, center=True,
                   return_complex=True)[:, :DIM_F, :]
    return torch.cat([S.real, S.imag], dim=0)[None]


def from_spec(spec: torch.Tensor, length: int) -> np.ndarray:
    """(4,F,T) → (2,length)；频域补一个 Nyquist 点后 iSTFT。"""
    spec = torch.nn.functional.pad(spec, (0, 0, 0, 1))
    S = torch.complex(spec[0:2], spec[2:4])
    w = torch.hann_window(N_FFT, periodic=True)
    return torch.istft(S, N_FFT, HOP, window=w, center=True, length=length)


def demix(x: np.ndarray, sess, overlap: float) -> np.ndarray:
    maxv = float(np.abs(x).max())
    if maxv > MAX_PEAK:
        x = x * (MAX_PEAK / maxv)
    elif 0 < maxv < MIN_PEAK:
        x = x * (MIN_PEAK / maxv)
    pad = GEN + TRIM - (x.shape[1] % GEN)
    mix = np.concatenate([np.zeros((2, TRIM), np.float32), x,
                          np.zeros((2, pad), np.float32)], axis=1)
    step = int((1 - overlap) * CHUNK)
    res = np.zeros((2, mix.shape[1]), np.float32)
    div = np.zeros((2, mix.shape[1]), np.float32)
    name = sess.get_inputs()[0].name
    for i in range(0, mix.shape[1], step):
        start, end = i, min(i + CHUNK, mix.shape[1])
        L = end - start
        seg = mix[:, start:end]
        if end != i + CHUNK:
            seg = np.concatenate([seg, np.zeros((2, (i + CHUNK) - end), np.float32)], axis=1)
        win = np.hanning(L).astype(np.float32)
        spec = to_spec(seg)
        spec[:, :, :3, :] = 0
        pred = sess.run(None, {name: spec.numpy()})[0][0]
        y = from_spec(torch.from_numpy(pred), CHUNK).numpy()[:, :L]
        res[:, start:end] += y * win
        div[:, start:end] += win
    out = res / np.maximum(div, 1e-8)
    return out[:, TRIM:-TRIM][:, : x.shape[1]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("out_dir")
    ap.add_argument("--overlap", type=float, default=0.25)
    ap.add_argument("--model", default=str(MODEL))
    a = ap.parse_args()
    src, out = Path(a.vocals).resolve(), Path(a.out_dir).resolve()
    if not src.is_file():
        print(json.dumps({"ok": False, "error": f"missing {src}"}, ensure_ascii=False))
        return 2
    sess = ort.InferenceSession(str(a.model), providers=["CUDAExecutionProvider",
                                                         "CPUExecutionProvider"])
    x = load(src)
    lead = demix(x, sess, a.overlap)
    back = x - lead
    out.mkdir(parents=True, exist_ok=True)
    sf.write(str(out / "lead.wav"), lead.T, SR, subtype="FLOAT")
    sf.write(str(out / "backing.wav"), back.T, SR, subtype="FLOAT")
    print(json.dumps({"ok": True, "lead": str(out / "lead.wav"),
                      "backing": str(out / "backing.wav"),
                      "dur_s": round(x.shape[1] / SR, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
