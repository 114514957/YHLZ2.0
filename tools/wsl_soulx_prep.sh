#!/usr/bin/env bash
# Stage A (ledger 0458): prepare prompt + target OUTSIDE the GPU window.
# Vocal separation (optional) and F0 extraction fit next to the LLM, so the
# chat stays online; only the SVC stage needs the exclusive window.
#
# Usage: wsl_soulx_prep.sh <prompt.wav> <target_audio> <sep:0|1> [voice_tag]
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
PROMPT="${1:?usage: wsl_soulx_prep.sh <prompt.wav> <target> <sep:0|1> [tag]}"
TARGET="${2:?}"
SEP="${3:-1}"
TAG="${4:-xiaoyi}"
PDIR="example/transcriptions/prompt_$TAG"

# prompt: cache it per voice tag (fixed reference for every job)
if [ ! -f "$PDIR/vocal_f0.npy" ]; then
  echo "[prep] prompt ($TAG, cached after first run)"
  cp "$PROMPT" "example/audio/prompt_$TAG.wav"
  python -m preprocess.pipeline --audio_path "example/audio/prompt_$TAG.wav" \
    --save_dir "$PDIR" --language Mandarin \
    --device cuda --vocal_sep False --max_merge_duration 30000 \
    --midi_transcribe False
else
  echo "[prep] prompt cache hit ($TAG)"
fi

# target: separation (optional) + F0
EXT="${TARGET##*.}"
cp "$TARGET" "example/audio/target_user.$EXT"
if [ "$SEP" = "1" ]; then
  echo "[prep] target: vocal separation + F0 (slow, chat stays online)"
  python -m preprocess.pipeline --audio_path "example/audio/target_user.$EXT" \
    --save_dir example/transcriptions/target_user --language Mandarin \
    --device cuda --vocal_sep True --max_merge_duration 120000 \
    --midi_transcribe False
else
  echo "[prep] target: F0 only (fast)"
  python -m preprocess.pipeline --audio_path "example/audio/target_user.$EXT" \
    --save_dir example/transcriptions/target_user --language Mandarin \
    --device cuda --vocal_sep False --max_merge_duration 120000 \
    --midi_transcribe False
fi
ls -la example/transcriptions/target_user | head -8
echo "[prep] done"
