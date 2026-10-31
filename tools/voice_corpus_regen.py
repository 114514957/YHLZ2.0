#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用定版音色样本重生成元亨语料（Qwen3-TTS 克隆，锁死音色）。

输入：data.list（path|speaker|lang|text）——只复用文本，不复用音频
输出：<out>/wavs/NNNNN.wav + <out>/data.list + metadata.jsonl

用法:
  # 先 20 条试跑，听克隆是否守住定版音色
  python tools/voice_corpus_regen.py --ref 音频素材/08_音色设计_v2/samples/06_活泼好奇.wav ^
      --ref-text "老爹，我是元亨呀。今天风挺大的，你出门记得穿外套，我在这儿等你回来。" --limit 20

  # 全量（可断点续跑；已存在的 wav 会跳过）
  python tools/voice_corpus_regen.py --ref ... --ref-text ... --mode cuda

注意：0.6B 克隆在 8 GB 卡上与 Gemma 共存会慢；全量建议开「语料窗」（停 llama）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "qwen3-tts" / "Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_LIST = ROOT / "models" / "tts" / "voice_train" / "yuanheng_2h" / "data.list"
DEFAULT_OUT = ROOT / "models" / "tts" / "voice_train" / "yuanheng_v2"


def _load(model_path: Path, mode: str, gpu_mib: int, backend: str = "qwen"):
    import torch

    if backend == "faster":
        from faster_qwen3_tts import FasterQwen3TTS

        t0 = time.time()
        if mode == "cpu":
            raise SystemExit("faster backend 只支持 CUDA（CUDA Graph）")
        m = FasterQwen3TTS.from_pretrained(str(model_path), device="cuda",
                                           dtype=torch.bfloat16)
        print(json.dumps({"event": "loaded", "model": model_path.name,
                          "backend": "faster", "elapsed_s": round(time.time() - t0, 1)}),
              flush=True)
        return m

    from qwen_tts import Qwen3TTSModel

    kwargs = dict(torch_dtype=torch.bfloat16, attn_implementation="sdpa",
                  low_cpu_mem_usage=True)
    if mode == "cpu":
        kwargs["device_map"] = "cpu"
    elif mode == "cuda":
        kwargs["device_map"] = "cuda:0"
    else:
        kwargs["device_map"] = "auto"
        if gpu_mib > 0:
            kwargs["max_memory"] = {0: f"{gpu_mib}MiB", "cpu": "24GiB"}
    t0 = time.time()
    m = Qwen3TTSModel.from_pretrained(str(model_path), **kwargs)
    print(json.dumps({"event": "loaded", "model": model_path.name, "mode": mode,
                      "elapsed_s": round(time.time() - t0, 1)}), flush=True)
    return m


def _f0_std(x, sr: int) -> float:
    """F0 起伏（半音标准差）：C 配方按它三次择优。

    用 yin 而不是 pyin：pyin 一条 5 s 要 6.6 s，yin 只要 0.02 s（实测），
    这里只做「同句三次谁更有起伏」的相对比较，yin 足够。
    """
    import librosa

    f0 = librosa.yin(x, fmin=70, fmax=700, sr=sr,
                     frame_length=1024, hop_length=256)
    v = f0[np.isfinite(f0)]
    if len(v) < 4:
        return 0.0
    return float(np.std(12 * np.log2(v / 55.0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="定版音色样本 wav")
    ap.add_argument("--ref-text", required=True, help="样本对应的文本（ICL 模式需要）")
    ap.add_argument("--list", default=str(DEFAULT_LIST))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--speaker", default="yuanheng")
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--gpu-mib", type=int, default=2500)
    ap.add_argument("--xvec-only", action="store_true",
                    help="只用说话人向量（更快，但音色细节弱）")
    ap.add_argument("--backend", choices=["qwen", "faster"], default="qwen",
                    help="faster=生产同款 CUDA Graph 后端，约 14 倍速")
    ap.add_argument("--instruct", default="",
                    help="生成时的风格指令（去客服腔）；空=不用")
    ap.add_argument("--takes", type=int, default=1,
                    help="每条生成几次，按 F0 起伏择优（C 配方=3）")
    ap.add_argument("--temp", type=float, default=0.0, help="0=用后端默认")
    ap.add_argument("--top-k", type=int, default=0, help="0=用后端默认")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    out = Path(a.out)
    (out / "wavs").mkdir(parents=True, exist_ok=True)
    list_path = out / "data.list"
    meta_path = out / "metadata.jsonl"

    rows = []
    for line in Path(a.list).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.count("|") < 3:
            continue
        _p, _spk, lang, text = line.split("|", 3)
        if text.strip():
            rows.append((lang, text.strip()))
    if a.limit:
        rows = rows[: a.limit]

    done = 0
    model = _load(Path(a.model), a.mode, a.gpu_mib, a.backend)
    t_all = time.time()
    with list_path.open("a", encoding="utf-8") as fl, meta_path.open("a", encoding="utf-8") as fm:
        for idx, (lang, text) in enumerate(rows):
            name = f"{idx + 1:05d}.wav"
            dst = out / "wavs" / name
            if dst.is_file() and dst.stat().st_size > 1000:
                done += 1
                continue
            t0 = time.time()
            spoken = text if text[-1:] in "。！？!?…" else text + "。"
            gen_kwargs = dict(text=spoken, language="Chinese", ref_audio=a.ref,
                              ref_text=a.ref_text)
            if a.instruct:
                gen_kwargs["instruct"] = a.instruct
            if a.temp > 0:
                gen_kwargs["temperature"] = a.temp
            if a.top_k > 0:
                gen_kwargs["top_k"] = a.top_k
            if a.backend == "faster":
                gen_kwargs["xvec_only"] = a.xvec_only
            else:
                gen_kwargs["x_vector_only_mode"] = a.xvec_only
                gen_kwargs["non_streaming_mode"] = True
            best = None
            for take in range(max(1, a.takes)):
                import torch

                torch.manual_seed(20261018 + idx * 7 + take)
                wavs, sr = model.generate_voice_clone(**gen_kwargs)
                cand = np.asarray(wavs[0], dtype="float32").squeeze()
                score = _f0_std(cand, sr)
                if best is None or score > best[0]:
                    best = (score, cand, sr)
            _, audio, sr = best
            sf.write(dst, audio, sr)
            rel = f"wavs/{name}"
            fl.write(f"{rel}|{a.speaker}|{lang}|{spoken}\n")
            fl.flush()
            fm.write(json.dumps({"path": rel, "speaker": a.speaker, "lang": lang,
                                 "text": spoken, "sr": int(sr),
                                 "duration_s": round(len(audio) / float(sr), 2),
                                 "peak": round(float(np.max(np.abs(audio))), 3),
                                 "elapsed_s": round(time.time() - t0, 1)},
                                ensure_ascii=False) + "\n")
            fm.flush()
            done += 1
            if done % 10 == 0 or idx < 3:
                print(json.dumps({"event": "progress", "done": done,
                                  "total": len(rows),
                                  "elapsed_s": round(time.time() - t_all, 1)},
                                 ensure_ascii=False), flush=True)
    print(json.dumps({"event": "done", "done": done, "total": len(rows),
                      "out": str(out),
                      "elapsed_s": round(time.time() - t_all, 1)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
