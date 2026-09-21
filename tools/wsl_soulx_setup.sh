#!/usr/bin/env bash
# WSL2 (Ubuntu-22.04) setup for SoulX-Singer SVC/SVS — ledger 0456.
# Code source: official HF Space mirror (hf-mirror reachable from CN).
# Models: ~11.8GB (SVS 5.3G + Preprocess 6.5G). sageattention is only needed by
# the vocal-separation module, so it is skipped here.
set -e
mkdir -p "$HOME/soulx" && cd "$HOME/soulx"
if [ ! -d SoulX-Singer ]; then
  git clone --depth 1 https://hf-mirror.com/spaces/Soul-AILab/SoulX-Singer.git
fi
[ -x "$HOME/soulx/venv/bin/pip" ] || python3 -m venv "$HOME/soulx/venv"
"$HOME/soulx/venv/bin/pip" install -q -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
cd SoulX-Singer
grep -v '^sageattention' requirements.txt > /tmp/req_core.txt
"$HOME/soulx/venv/bin/pip" install -r /tmp/req_core.txt \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
export HF_ENDPOINT=https://hf-mirror.com
"$HOME/soulx/venv/bin/hf" download Soul-AILab/SoulX-Singer \
  --local-dir pretrained_models/SoulX-Singer
"$HOME/soulx/venv/bin/hf" download Soul-AILab/SoulX-Singer-Preprocess \
  --local-dir pretrained_models/SoulX-Singer-Preprocess
echo "setup done: $HOME/soulx/SoulX-Singer"
