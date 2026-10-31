#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 GPT-SoVITS v5（含 LoRA 权重）合成一句，输出 wav + 指标。

用法:
  python -X utf8 tools/gsv5_infer_test.py --weights <lora.pth> \
      --text "元亨，能听到吗？" --out out.wav [--steps 4] [--cfg 0] [--speed 1.0]

注意：必须用 `-X utf8` 启动（项目路径含全角破折号）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS"
PM = GSV / "GPT_SoVITS" / "pretrained_models"

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1,.maas.aliyuncs.com"
os.environ.pop("no_proxy", None)
os.environ["PATH"] = (str(ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin")
                      + os.pathsep + os.environ.get("PATH", ""))
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, str(GSV / "GPT_SoVITS"))
sys.path.insert(0, str(GSV))
os.chdir(str(GSV))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True, help="LoRA 权重 pth（07 头）")
    ap.add_argument("--text", default="元亨，能听到吗？")
    ap.add_argument("--ref", default=str(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.wav"))
    ap.add_argument("--ref-text", default=(ROOT / "models" / "tts" / "refs" / "design_bright" / "ref01.txt")
                    .read_text(encoding="utf-8-sig").strip())
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--cfg", type=float, default=0.0)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--version", default="v5dev")
    a = ap.parse_args()

    cfg = {
        "device": "cuda",
        "is_half": True,
        "version": a.version,
        "t2s_weights_path": str(PM / "s1v3.ckpt"),
        "vits_weights_path": str(Path(a.weights).resolve()),
        "cnhuhbert_base_path": str(PM / "chinese-hubert-base"),
        "bert_base_path": str(PM / "chinese-roberta-wwm-ext-large"),
    }
    t0 = time.time()
    # TTS_Config 只认 {"custom": {...}}，顶层键会被忽略并回退 v2 默认。
    tts = TTS(TTS_Config({"custom": cfg}))
    load_s = time.time() - t0
    req = {
        "text": a.text, "text_lang": "zh",
        "ref_audio_path": str(a.ref), "prompt_text": a.ref_text, "prompt_lang": "zh",
        "text_split_method": "cut5", "batch_size": 1, "media_type": "wav",
        "streaming_mode": False, "sample_steps": a.steps, "cfg_rate": a.cfg,
        "speed_factor": a.speed, "parallel_infer": True,
    }
    t1 = time.time()
    gen = tts.run(req)
    sr, audio = next(gen)
    gen_s = time.time() - t1
    audio = np.asarray(audio, dtype="float32").squeeze()
    # v5 返回 int16 量纲的 float（峰值可达 3 万），不归一会直接削平成方波。
    peak_raw = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak_raw > 1.5:
        audio = audio / 32768.0
    out_path = Path(a.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, sr)
    print(json.dumps({
        "out": a.out, "sr": int(sr), "dur": round(len(audio) / sr, 2),
        "peak": round(float(np.max(np.abs(audio))), 3),
        "load_s": round(load_s, 1), "gen_s": round(gen_s, 1),
        "rtf": round(gen_s / max(len(audio) / sr, 1e-6), 3),
        "steps": a.steps, "cfg": a.cfg, "speed": a.speed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
