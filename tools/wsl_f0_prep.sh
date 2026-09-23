#!/usr/bin/env bash
# F0-only target prep for SVC (input: an already-separated vocal stem).
# Usage: wsl_f0_prep.sh <vocal.wav>
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
VOCAL="${1:?usage: wsl_f0_prep.sh <vocal.wav>}"
rm -rf example/transcriptions/target_user
mkdir -p example/transcriptions/target_user
python -m preprocess.pipeline --audio_path "$VOCAL" \
  --save_dir example/transcriptions/target_user --language Mandarin \
  --device cuda --vocal_sep False --max_merge_duration 120000 \
  --midi_transcribe False
ls -la example/transcriptions/target_user
echo "[f0-prep] done"
