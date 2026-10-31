#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""元亨音色设计批处理（Qwen3-TTS VoiceDesign 1.7B）。

用法:
  python tools/voice_design_batch.py --limit 1 --gpu-mib 2300
  python tools/voice_design_batch.py --gpu-mib 2300
  python tools/voice_design_batch.py --cpu-only

设计:
  - 默认 device_map="auto" + max_memory：GPU 只放前 N MiB，其余层落到 CPU
    （8 GB 卡与 Gemma 共存时用；纯 GPU 可传 --gpu-mib 0 表示不限制）。
  - 每条候选单独存 wav，同时生成 盲测/ 目录（A..L 随机命名 + 答案文件）。
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_SPEC = ROOT / "config" / "voice_design_v1.json"
DEFAULT_OUT = ROOT / "音频素材" / "08_音色设计_v2"


def _load_model(model_path: Path, mode: str, gpu_mib: int, load_8bit: bool = False):
    import torch
    from qwen_tts import Qwen3TTSModel

    kwargs = dict(
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    if load_8bit:
        kwargs["load_in_8bit"] = True
    if mode == "cpu":
        kwargs["device_map"] = "cpu"
    elif mode == "cuda":
        kwargs["device_map"] = "cuda:0"
    else:
        kwargs["device_map"] = "auto"
        if gpu_mib > 0:
            kwargs["max_memory"] = {0: f"{gpu_mib}MiB", "cpu": "24GiB"}
    t0 = time.time()
    model = Qwen3TTSModel.from_pretrained(str(model_path), **kwargs)
    print(json.dumps({"event": "loaded", "mode": mode, "gpu_mib": gpu_mib,
                      "8bit": load_8bit,
                      "elapsed_s": round(time.time() - t0, 1)}), flush=True)
    return model


def _peak(x: np.ndarray) -> float:
    return float(np.max(np.abs(x))) if x.size else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟）")
    ap.add_argument("--mode", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--gpu-mib", type=int, default=2300,
                    help="auto 模式下 GPU 预算；0=不限制")
    ap.add_argument("--seed", type=int, default=20261018)
    ap.add_argument("--load-8bit", action="store_true",
                    help="8-bit 量化，约 1.9 GB，可整模型上 GPU（候选筛选够用）")
    a = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    text = spec["_test_text"]
    items = spec["candidates"][: a.limit or None]

    out = Path(a.out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    (out / "盲测").mkdir(parents=True, exist_ok=True)

    import torch

    model = _load_model(Path(a.model), a.mode, a.gpu_mib, a.load_8bit)

    manifest = []
    for idx, item in enumerate(items):
        seed = a.seed + idx
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        t0 = time.time()
        try:
            wavs, sr = model.generate_voice_design(
                text=text, instruct=item["instruct"], language="Chinese",
                non_streaming_mode=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"event": "failed", "id": item["id"],
                              "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False), flush=True)
            raise
        audio = np.asarray(wavs[0], dtype="float32").squeeze()
        path = out / "samples" / f"{item['id']}_{item['tag']}.wav"
        sf.write(path, audio, sr)
        row = {
            "id": item["id"], "tag": item["tag"], "instruct": item["instruct"],
            "path": str(path.relative_to(ROOT)), "sr": int(sr),
            "duration_s": round(len(audio) / float(sr), 2),
            "peak": round(_peak(audio), 3), "seed": seed,
            "elapsed_s": round(time.time() - t0, 1),
        }
        manifest.append(row)
        print(json.dumps({"event": "ok", **row}, ensure_ascii=False), flush=True)

    # 盲测包：随机 A.. 命名，答案单独存
    letters = [chr(ord("A") + i) for i in range(len(manifest))]
    order = list(range(len(manifest)))
    random.Random(a.seed).shuffle(order)
    key = {}
    for slot, pos in zip(letters, order):
        row = manifest[pos]
        dst = out / "盲测" / f"{slot}.wav"
        shutil.copy2(ROOT / row["path"], dst)
        key[slot] = {"id": row["id"], "tag": row["tag"]}
    (out / "盲测" / "答案_先别打开.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")

    (out / "manifest.json").write_text(
        json.dumps({"test_text": text, "model": str(DEFAULT_MODEL.name),
                    "mode": a.mode, "gpu_mib": a.gpu_mib,
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "items": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    lines = ["元亨音色设计 v1（Qwen3-TTS VoiceDesign 1.7B）", "=" * 46,
             f"测试文本：{text}", f"生成方式：{a.mode}（GPU 预算 {a.gpu_mib} MiB）", "",
             "候选："]
    for row in manifest:
        lines.append(f"  {row['id']}  {row['tag']:<6} {row['duration_s']:>5.2f}s  "
                     f"peak={row['peak']:.2f}  {row['instruct']}")
    lines += ["", "盲测：盲测/A.wav … 按字母顺序试听；答案在 盲测/答案_先别打开.json。",
              "定版流程：选出 1 条 → 记下 instruct → 用该样本做克隆语料（下一步）。"]
    (out / "说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"event": "done", "n": len(manifest), "out": str(out)},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
