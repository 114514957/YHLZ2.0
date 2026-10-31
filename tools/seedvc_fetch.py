#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拉取 Seed-VC 代码与权重（B 路线：更强的零样本 SVC）。

用法: python tools/seedvc_fetch.py
产物: Seed-VC/ + Seed-VC/checkpoints/
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "Seed-VC"
CKPT = DST / "checkpoints"
MIRROR = "https://hf-mirror.com"
REPO = "Plachta/Seed-VC"

CODE_ZIP = "https://codeload.github.com/Plachtaa/seed-vc/zip/refs/heads/main"

FILES = [
    ("config_dit_mel_seed_uvit_whisper_base_f0_44k.yml", 2408),
    ("DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth", 820865494),
    ("se_db.pt", 102405286),
    ("hift.pt", 81896716),
    ("DiT_uvit_tat_xlsr_ema.pth", 142112203),
    ("config_dit_mel_seed_uvit_xlsr_tiny.yml", 2100),
]


def log(msg, **kw):
    print(f"[{time.strftime('%H:%M:%S')}] {msg} " +
          " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def fetch(url, dest, size=None):
    if dest.is_file() and (size is None or dest.stat().st_size == size):
        log("skip", name=dest.name)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    have = 0
    for attempt in range(1, 6):
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True,
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
                        if have // (200 << 20) > (have - len(chunk)) // (200 << 20):
                            log("progress", name=dest.name,
                                mb=round(have / 1e6, 1))
        except (requests.RequestException, OSError) as exc:
            log("retry", name=dest.name, attempt=attempt,
                have_mb=round(have / 1e6, 1), err=type(exc).__name__)
            time.sleep(2)
            continue
        if size is None or part.stat().st_size == size:
            break
    part.replace(dest)
    log("done", name=dest.name, mb=round(dest.stat().st_size / 1e6, 1))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if not (DST / "inference.py").is_file():
        tmp = ROOT / "cache" / "tmp" / "seedvc.zip"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        fetch(CODE_ZIP, tmp)
        stage = ROOT / "cache" / "tmp" / "seedvc_stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(stage)
        roots = [p for p in stage.iterdir() if p.is_dir()]
        src = roots[0] if roots else stage
        shutil.rmtree(DST, ignore_errors=True)
        shutil.move(str(src), str(DST))
        log("code-done", path=str(DST))
        tmp.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
    for name, size in FILES:
        fetch(f"{MIRROR}/{REPO}/resolve/main/{name}", CKPT / name, size)
    log("all-done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
