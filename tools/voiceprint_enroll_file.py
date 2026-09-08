"""Voiceprint enrollment from an audio FILE (ledger 0218).

The live-mic enroll (voiceprint_enroll.py) suffers the weak-mic failure mode
(0158/0159): RMS ~0.002 is far below cam++-friendly levels, so the stored
embedding is poor and wake similarity drifts. Feeding a close-mic recording
('标准录音 7.mp3' etc.) produces a stable reference vector.

Usage:
    python tools/voiceprint_enroll_file.py --input "C:\\Users\\ACE_WAN——PROJECT\\Desktop\\音频素材\\标准录音 7.mp3"
    python tools/voiceprint_enroll_file.py --input ... --keep-backup   # don't overwrite cache/voiceprint/user_embedding.npy.bak
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _decode_16k_mono(path: Path) -> tuple[object, int]:
    """mp3/any -> 16 kHz mono float32 numpy via bundled ffmpeg."""
    import subprocess

    import imageio_ffmpeg
    import numpy as np

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    p = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, timeout=180)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("ffmpeg decode failed: "
                           + p.stderr.decode("utf-8", "replace")[-300:])
    audio = np.frombuffer(p.stdout, dtype="<f4").astype("float32")
    return audio, 16000


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="voice sample (mp3/wav/...)")
    ap.add_argument("--window-s", type=float, default=12.0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default="cache/voiceprint/user_embedding.npy")
    a = ap.parse_args()

    import numpy as np
    import torch

    if a.device == "cuda" and not torch.cuda.is_available():
        print("[warn] cuda unavailable, using cpu", flush=True)
        a.device = "cpu"
    path = Path(a.input)
    if not path.exists():
        print("input not found:", path, flush=True)
        return 1
    audio, rate = _decode_16k_mono(path)
    print(f"decoded {path.name}: {len(audio)/rate:.1f}s @16k mono", flush=True)
    if len(audio) < rate * 2:
        print("sample too short (<2s)", flush=True)
        return 1

    # pick the loudest continuous window (up to window_s)
    from funasr import AutoModel

    w = 1600
    energies = [float(np.sqrt(np.mean(np.square(audio[i:i + w]))))
                for i in range(0, len(audio) - w, w)]
    best = max(range(len(energies)), key=lambda i: energies[i])
    seg_start = max(0, best * w - int(3 * rate))
    seg = audio[seg_start: seg_start + int(a.window_s * rate)]
    peak = float(np.abs(audio).max())
    print(f"loudest window rms={float(np.sqrt(np.mean(np.square(seg)))):.4f} "
          f"peak={peak:.3f}", flush=True)

    model = AutoModel(model=str(Path("models/voice/sv/campplus")),
                      device=a.device, disable_update=True,
                      disable_pbar=True, disable_log=True)
    r = model.generate(input=seg)
    e = np.asarray(r[0]["spk_embedding"], dtype="float32").reshape(-1)
    e = e / (np.linalg.norm(e) + 1e-9)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bak = out.with_suffix(".npy.bak")
    if out.exists() and not bak.exists():
        bak.write_bytes(out.read_bytes())
        print("backup ->", bak, flush=True)
    np.save(str(out), e)
    print(f"saved {out} (dim={e.size})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
