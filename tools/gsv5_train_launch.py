#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动 GPT-SoVITS v5 LoRA 训练（负责修 Windows 环境坑）。

用法:
  python tools/gsv5_train_launch.py [config.json]

修的坑:
  1. PYTHONUTF8=1 —— 项目路径含全角破折号，默认 GBK 读 JSON 会炸；
  2. PYTHONPATH=GPT-SoVITS 根 —— 脚本内 `from tools.my_utils ...` 需要；
  3. NO_PROXY 去掉 `[::1]` —— 否则 httpx 抛 InvalidURL（ledger 0829/0837）；
  4. CWD 切到 GPT-SoVITS 根 —— 权重相对目录 SoVITS_weights_* 落在这里。
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GSV = ROOT / "GPT-SoVITS"
DEFAULT_CFG = GSV / "GPT_SoVITS" / "configs" / "tmp_s2_v5dev_lora.json"

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONPATH"] = str(GSV) + os.pathsep + str(GSV / "GPT_SoVITS")
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1,.maas.aliyuncs.com"
os.environ.pop("no_proxy", None)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
# 数据加载器用 ffmpeg 读 32k wav；必须进 PATH。
_FFMPEG = ROOT / "cache" / "tools" / "ffmpeg-9.0.1-essentials_build" / "bin"
os.environ["PATH"] = str(_FFMPEG) + os.pathsep + os.environ.get("PATH", "")

cfg = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_CFG
if not cfg.is_file():
    raise SystemExit(f"config not found: {cfg}")

os.chdir(str(GSV))
sys.path.insert(0, str(GSV / "GPT_SoVITS"))
sys.path.insert(0, str(GSV))
sys.argv = ["s2_train_v3_lora.py", "--config", str(cfg)]

print(f"[launch] cwd={os.getcwd()} cfg={cfg}", flush=True)
runpy.run_path(str(GSV / "GPT_SoVITS" / "s2_train_v3_lora.py"),
               run_name="__main__")
