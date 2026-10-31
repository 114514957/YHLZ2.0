#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拉取 GPT-SoVITS v5：代码分支 + 预训练权重（走系统代理）。

用法:
  python tools/gsv5_fetch.py            # 全部
  python tools/gsv5_fetch.py --code     # 只拉代码
  python tools/gsv5_fetch.py --weights  # 只拉权重

产物:
  GPT-SoVITS/                                  v5 分支源码
  GPT-SoVITS/GPT_SoVITS/pretrained_models/gsv-v5-pretrained/*.pth
  .../s1v3.ckpt, sv/, chinese-hubert-base/, chinese-roberta-wwm-ext-large/
  GPT_SoVITS/text/G2PWModel/
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS"
PM = GSV / "GPT_SoVITS" / "pretrained_models"
MIRROR = "https://hf-mirror.com"
REPO = "lj1995/GPT-SoVITS"

CODE_ZIP = ("https://codeload.github.com/RVC-Boss/GPT-SoVITS/zip/refs/heads/"
            "cuda_graph_accel_v5")

WEIGHTS = [
    (f"{MIRROR}/{REPO}/resolve/main/gsv-v5-pretrained/s2Gv5dev.pth",
     PM / "gsv-v5-pretrained" / "s2Gv5dev.pth", 766385517),
    (f"{MIRROR}/{REPO}/resolve/main/gsv-v5-pretrained/s2Gv5turbo.pth",
     PM / "gsv-v5-pretrained" / "s2Gv5turbo.pth", 766406144),
    (f"{MIRROR}/{REPO}/resolve/main/gsv-v5-pretrained/vocoder.pth",
     PM / "gsv-v5-pretrained" / "vocoder.pth", 57761163),
    (f"{MIRROR}/{REPO}/resolve/main/s1v3.ckpt", PM / "s1v3.ckpt", 155284856),
    (f"{MIRROR}/{REPO}/resolve/main/sv/pretrained_eres2netv2w24s4ep4.ckpt",
     PM / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt", 107528697),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-hubert-base/config.json",
     PM / "chinese-hubert-base" / "config.json", 1449),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-hubert-base/preprocessor_config.json",
     PM / "chinese-hubert-base" / "preprocessor_config.json", 212),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-hubert-base/pytorch_model.bin",
     PM / "chinese-hubert-base" / "pytorch_model.bin", 188811417),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-roberta-wwm-ext-large/config.json",
     PM / "chinese-roberta-wwm-ext-large" / "config.json", 963),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-roberta-wwm-ext-large/tokenizer.json",
     PM / "chinese-roberta-wwm-ext-large" / "tokenizer.json", 268962),
    (f"{MIRROR}/{REPO}/resolve/main/chinese-roberta-wwm-ext-large/pytorch_model.bin",
     PM / "chinese-roberta-wwm-ext-large" / "pytorch_model.bin", 651225145),
    (f"{MIRROR}/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/G2PWModel.zip",
     ROOT / "cache" / "tmp" / "G2PWModel.zip", None),
]


def _log(event: str, **kw) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {event} " +
          " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def fetch_code() -> None:
    if (GSV / "webui.py").is_file():
        _log("code-skip", path=str(GSV))
        return
    tmp = ROOT / "cache" / "tmp" / "gsv5_code.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    _log("code-download", url=CODE_ZIP)
    with requests.get(CODE_ZIP, stream=True, timeout=(20, 180)) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    _log("code-unzip", size_mb=round(tmp.stat().st_size / 1e6, 1))
    stage = ROOT / "cache" / "tmp" / "gsv5_stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(stage)
    roots = [p for p in stage.iterdir() if p.is_dir()]
    src = roots[0] if roots else stage
    shutil.rmtree(GSV, ignore_errors=True)
    shutil.move(str(src), str(GSV))
    _log("code-done", path=str(GSV))
    tmp.unlink(missing_ok=True)
    shutil.rmtree(stage, ignore_errors=True)


def fetch_one(url: str, dest: Path, size: int | None) -> None:
    if dest.is_file() and (size is None or dest.stat().st_size == size):
        _log("skip", name=dest.name)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    t0 = time.time()
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        if size is not None and have > size:
            part.unlink()
            have = 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, stream=True, headers=headers,
                              timeout=(20, 300)) as r:
                if have and r.status_code != 206:
                    _log("range-unsupported-restart", name=dest.name)
                    part.unlink(missing_ok=True)
                    have = 0
                    continue
                r.raise_for_status()
                total = have + int(r.headers.get("content-length") or 0)
                with part.open("ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
                        if have // (200 << 20) > (have - len(chunk)) // (200 << 20):
                            _log("progress", name=dest.name,
                                 mb=round(have / 1e6, 1),
                                 total_mb=round(total / 1e6, 1),
                                 attempt=attempt)
        except (requests.RequestException, OSError) as exc:
            _log("retry", name=dest.name, attempt=attempt,
                 have_mb=round(have / 1e6, 1), err=type(exc).__name__)
            time.sleep(2)
            continue
        if size is None or part.stat().st_size == size:
            break
        _log("size-mismatch", name=dest.name, have=part.stat().st_size, want=size)
    part.replace(dest)
    _log("done", name=dest.name, mb=round(dest.stat().st_size / 1e6, 1),
         secs=round(time.time() - t0, 1))


def fetch_weights() -> None:
    for url, dest, size in WEIGHTS:
        fetch_one(url, dest, size)
    zip_path = ROOT / "cache" / "tmp" / "G2PWModel.zip"
    g2pw = GSV / "GPT_SoVITS" / "text" / "G2PWModel"
    if zip_path.is_file() and not g2pw.is_dir():
        _log("g2pw-unzip")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(GSV / "GPT_SoVITS" / "text")
        _log("g2pw-done", path=str(g2pw))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", action="store_true")
    ap.add_argument("--weights", action="store_true")
    a = ap.parse_args()
    do_code = a.code or not a.weights
    do_weights = a.weights or not a.code
    if do_code:
        fetch_code()
    if do_weights:
        fetch_weights()
    _log("all-done")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
