#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补 Seed-VC v2 所需权重：AR/CFM、ASTRAL、Whisper-small、HuBERT-large、BigVGAN。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CK = ROOT / "Seed-VC" / "checkpoints"
MIRROR = "https://hf-mirror.com"

FILES = [
    ("Plachta/Seed-VC", "v2/ar_base.pth", CK / "v2" / "ar_base.pth", 358846893),
    ("Plachta/Seed-VC", "v2/cfm_small.pth", CK / "v2" / "cfm_small.pth", 353349694),
    ("Plachta/ASTRAL-quantization", "bsq32/bsq32_light.pth", CK / "bsq32_bsq32_light.pth", 78156693),
    ("Plachta/ASTRAL-quantization", "bsq2048/bsq2048_light.pth", CK / "bsq2048_bsq2048_light.pth", 78181599),
    ("openai/whisper-small", "config.json", CK / "whisper-small" / "config.json", 1967),
    ("openai/whisper-small", "preprocessor_config.json", CK / "whisper-small" / "preprocessor_config.json", 184990),
    ("openai/whisper-small", "model.safetensors", CK / "whisper-small" / "model.safetensors", 966995080),
    ("facebook/hubert-large-ll60k", "config.json", CK / "hubert-large" / "config.json", 1600),
    ("facebook/hubert-large-ll60k", "preprocessor_config.json", CK / "hubert-large" / "preprocessor_config.json", 212),
    ("facebook/hubert-large-ll60k", "pytorch_model.bin", CK / "hubert-large" / "pytorch_model.bin", 1261920069),
    ("nvidia/bigvgan_v2_22khz_80band_256x", "config.json", CK / "bigvgan_22k" / "config.json", 1405),
    ("nvidia/bigvgan_v2_22khz_80band_256x", "bigvgan_generator.pt", CK / "bigvgan_22k" / "bigvgan_generator.pt", 449228171),
]


def log(msg, **kw):
    print(f"[{time.strftime('%H:%M:%S')}] {msg} " +
          " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def fetch(repo, name, dest, size):
    if dest.is_file() and dest.stat().st_size == size:
        log("skip", name=dest.name)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    for _ in range(6):
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(f"{MIRROR}/{repo}/resolve/main/{name}",
                              headers=headers, stream=True,
                              timeout=(20, 300)) as r:
                if have and r.status_code != 206:
                    part.unlink(missing_ok=True)
                    have = 0
                    continue
                r.raise_for_status()
                with part.open("ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
                        if have // (300 << 20) > (have - len(chunk)) // (300 << 20):
                            log("progress", name=dest.name, mb=round(have / 1e6, 1))
        except (requests.RequestException, OSError) as exc:
            log("retry", name=dest.name, have_mb=round(have / 1e6, 1),
                err=type(exc).__name__)
            continue
        if part.stat().st_size >= size:
            break
    part.replace(dest)
    log("done", name=dest.name, mb=round(dest.stat().st_size / 1e6, 1))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    for repo, name, dest, size in FILES:
        fetch(repo, name, dest, size)
    log("all-done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
