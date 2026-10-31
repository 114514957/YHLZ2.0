#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GPT-SoVITS v5 LoRA：数据集预处理 + 训练配置生成。

用法:
  python tools/gsv5_prepare.py --corpus models/tts/voice_train/yuanheng_bright \
      --exp-name yuanheng_bright --version v5dev --steps all

步骤:
  text      -> 2-name2text.txt（BERT + G2PW 文本特征）
  hubert    -> 4-cnhubert/ + 5-wav32k/
  semantic  -> 6-name2semantic.tsv
  config    -> GPT_SoVITS/configs/tmp_s2_<version>_lora.json

v5 不需要 2-get-sv（那是 v2Pro 专用）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS"
PY = ROOT / "venv-gsv5" / "Scripts" / "python.exe"
PM = GSV / "GPT_SoVITS" / "pretrained_models"
LOGROOT = ROOT / "cache" / "logs"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(script: str, env: dict, log_path: Path) -> None:
    cmd = [str(PY), "-s", script]
    log(f"run {script}")
    base = dict(os.environ)
    ffmpeg_bin = str(ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin")
    base.update({
        "PYTHONUTF8": "1",
        # text/module/feature_extractor 在 GPT_SoVITS/ 下，tools 在仓库根，
        # 两个都要进 PYTHONPATH（脚本以 prepare_datasets 为 sys.path[0]）。
        "PYTHONPATH": str(GSV) + os.pathsep + str(GSV / "GPT_SoVITS"),
        "PYTHONIOENCODING": "utf-8",
        # GPT-SoVITS 的 load_audio 直接调 `ffmpeg`，必须进 PATH。
        "PATH": ffmpeg_bin + os.pathsep + base.get("PATH", ""),
        # 0829/0837: [::1] in NO_PROXY makes httpx raise InvalidURL
        "NO_PROXY": "localhost,127.0.0.1,::1,.maas.aliyuncs.com",
    })
    base.pop("no_proxy", None)
    base.update(env)
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write("\n=== %s %s ===\n" % (time.strftime("%H:%M:%S"), script))
        f.flush()
        p = subprocess.run(cmd, cwd=str(GSV), env=base, stdout=f,
                           stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise SystemExit(f"{script} failed exit={p.returncode}, see {log_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--exp-name", default="yuanheng_bright")
    ap.add_argument("--version", default="v5dev", choices=["v5dev", "v5turbo"])
    ap.add_argument("--steps", default="all",
                    choices=["all", "text", "hubert", "semantic", "config"])
    ap.add_argument("--batch-size", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lora-rank", type=int, default=32)
    ap.add_argument("--grad-ckpt", action="store_true")
    ap.add_argument("--gpu", default="0")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    corpus = Path(a.corpus).resolve()
    wav_dir = corpus / "wavs"
    if not wav_dir.is_dir():
        raise SystemExit(f"wav dir missing: {wav_dir}")
    exp_dir = GSV / "logs" / a.exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    LOGROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOGROOT / f"gsv5_prepare_{a.exp_name}.log"

    list_path = GSV / "data_lists" / f"{a.exp_name}.list"
    list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for line in (corpus / "data.list").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.count("|") < 3:
            continue
        rel, spk, lang, text = line.split("|", 3)
        name = Path(rel).name
        lines.append(f"{wav_dir / name}|{spk}|{lang}|{text}")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"list {list_path} n={len(lines)}")

    common = dict(
        inp_text=str(list_path), inp_wav_dir=str(wav_dir),
        exp_name=a.exp_name, opt_dir=str(exp_dir),
        i_part="0", all_parts="1", is_half="True",
        _CUDA_VISIBLE_DEVICES=a.gpu,
    )
    steps = ["text", "hubert", "semantic", "config"] if a.steps == "all" else [a.steps]

    if "text" in steps:
        run("GPT_SoVITS/prepare_datasets/1-get-text.py",
            dict(common, bert_pretrained_dir=str(PM / "chinese-roberta-wwm-ext-large")),
            log_path)
        src = exp_dir / "2-name2text-0.txt"
        if src.is_file():
            src.replace(exp_dir / "2-name2text.txt")
        log("text done")

    if "hubert" in steps:
        run("GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py",
            dict(common, cnhubert_base_dir=str(PM / "chinese-hubert-base")),
            log_path)
        log("hubert done")

    if "semantic" in steps:
        run("GPT_SoVITS/prepare_datasets/3-get-semantic.py",
            dict(inp_text=str(list_path), exp_name=a.exp_name,
                 opt_dir=str(exp_dir), i_part="0", all_parts="1",
                 is_half="True", _CUDA_VISIBLE_DEVICES=a.gpu,
                 pretrained_s2G=str(PM / "gsv-v5-pretrained" / f"s2G{a.version}.pth"),
                 s2config_path="GPT_SoVITS/configs/s2.json"),
            log_path)
        part = exp_dir / "6-name2semantic-0.tsv"
        if part.is_file():
            body = part.read_text(encoding="utf-8").strip("\n")
            (exp_dir / "6-name2semantic.tsv").write_text(
                "item_name\tsemantic_audio\n" + body + "\n", encoding="utf-8")
        log("semantic done")

    if "config" in steps:
        base = json.loads((GSV / "GPT_SoVITS" / "configs" / "s2.json")
                          .read_text(encoding="utf-8"))
        base["train"].update({
            "batch_size": a.batch_size,
            "epochs": a.epochs,
            "lora_rank": a.lora_rank,
            "pretrained_s2G": str(PM / "gsv-v5-pretrained" / f"s2G{a.version}.pth"),
            "pretrained_s2D": "",
            "if_save_latest": True,
            "if_save_every_weights": True,
            "save_every_epoch": 1,
            "gpu_numbers": a.gpu,
            "grad_ckpt": bool(a.grad_ckpt),
            "text_low_lr_rate": 0.4,
        })
        base["model"]["version"] = a.version
        base["data"]["exp_dir"] = str(exp_dir)
        base["s2_ckpt_dir"] = str(exp_dir)
        base["save_weight_dir"] = f"SoVITS_weights_{a.version}"
        base["name"] = a.exp_name
        base["version"] = a.version
        cfg = GSV / "GPT_SoVITS" / "configs" / f"tmp_s2_{a.version}_lora.json"
        cfg.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"config {cfg}")

    log("all done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
