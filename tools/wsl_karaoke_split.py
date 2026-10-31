#!/usr/bin/env python3
"""Lead/backing split for a vocal stem (karaoke Mel-Band-Roformer).

Runs in the SoulX venv with cwd = ~/soulx/SoulX-Singer (relative model paths).
Usage: python wsl_karaoke_split.py <vocal.wav> <out_dir>
Writes out_dir/lead.wav (主唱) and out_dir/backing.wav (和声).
"""
from __future__ import annotations

import pathlib
import sys
import time

import numpy as np
import soundfile as sf

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SOULX = pathlib.Path.home() / "soulx" / "SoulX-Singer"
sys.path.insert(0, str(_SOULX))

from preprocess.tools.vocal_separation.model import VocalSeparator  # noqa: E402

SEP_DIR = "pretrained_models/SoulX-Singer-Preprocess/mel-band-roformer-karaoke"


def main() -> int:
    src = pathlib.Path(sys.argv[1]).resolve()
    out_dir = pathlib.Path(sys.argv[2]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    sep = VocalSeparator(
        sep_model_path=f"{SEP_DIR}/mel_band_roformer_karaoke_becruily.ckpt",
        sep_config_path=f"{SEP_DIR}/config_karaoke_becruily.yaml",
        der_model_path="",
        der_config_path="",
        use_der=False,
        device="cuda",
        disable_detailed_pbar=False,
        verbose=True,
    )
    print(f"[karaoke] model ready in {time.time() - t0:.1f}s", flush=True)
    t1 = time.time()
    out = sep.process(str(src))
    lead = np.asarray(out.vocals)
    backing = np.asarray(out.accompaniment)
    sr = out.sample_rate
    if lead.ndim == 2 and lead.shape[0] <= 2:
        lead = lead.T
        backing = backing.T
    sf.write(str(out_dir / "lead.wav"), lead, sr)
    sf.write(str(out_dir / "backing.wav"), backing, sr)
    print(f"[karaoke] done lead+backing in {time.time() - t1:.1f}s "
          f"sr={sr} shape={lead.shape}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
