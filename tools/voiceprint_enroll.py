"""Voiceprint enrollment (ledger 0159): register the user's voice for
voiceprint-based wake.  Hold the mic close (5-15 cm) and speak naturally.

Saves cache/voiceprint/user_embedding.npy
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-s", type=float, default=15.0)
    parser.add_argument("--device", type=int, default=1)
    args = parser.parse_args()

    import numpy as np
    import sounddevice as sd

    out = Path("cache/voiceprint")
    out.mkdir(parents=True, exist_ok=True)

    print("把麦克风靠近嘴边 5-15cm。倒计时后请自然说几句话（任意内容）…", flush=True)
    for i in range(3, 0, -1):
        print(f"{i}...", flush=True)
        time.sleep(1)
    print("开始录音（说 4-5 句话）…", flush=True)

    buf: list[np.ndarray] = []
    loud = 0.0
    t0 = time.time()
    with sd.InputStream(device=args.device, samplerate=16000, channels=1,
                        dtype="float32", blocksize=1600) as inp:
        while time.time() - t0 < args.duration_s:
            d, _ = inp.read(1600)
            mono = np.asarray(d[:, 0] if d.ndim > 1 else d, dtype="float32")
            peak = float(np.abs(mono).max())
            loud = max(loud, peak)
            buf.append(mono)
            if int(time.time() - t0) % 3 == 0 and peak < 0.01:
                print("  提示：声音偏小，请靠近麦克风或提高音量", flush=True)
    audio = np.concatenate(buf)
    print(f"录音完成 peak={round(loud, 4)}", flush=True)
    if loud < 0.02:
        print("录音过弱（peak<0.02），声纹将不可靠；建议换麦或贴近后再试。", flush=True)

    from funasr import AutoModel

    model = AutoModel(model="models/voice/sv/campplus", device="cpu",
                      disable_update=True, disable_pbar=True, disable_log=True)
    # embed the loudest continuous window (up to 12 s)
    w = 1600
    energies = [float(np.sqrt(np.mean(np.square(audio[i:i + w]))))
                for i in range(0, len(audio) - w, w)]
    best = max(range(len(energies)), key=lambda i: energies[i])
    seg_start = max(0, best * w - int(4 * 16000))
    seg = audio[seg_start: seg_start + int(12 * 16000)]
    r = model.generate(input=seg)
    e = np.asarray(r[0]["spk_embedding"], dtype="float32").reshape(-1)
    e = e / (np.linalg.norm(e) + 1e-9)
    np.save(str(out / "user_embedding.npy"), e)
    print(f"声纹已注册: cache/voiceprint/user_embedding.npy (dim={e.size})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
