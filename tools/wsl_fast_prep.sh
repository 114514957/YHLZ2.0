#!/usr/bin/env bash
# Fast-lane prep (2026-09-23): demucs htdemucs separation (seconds on GPU)
# instead of the BS-Roformer pipeline (tens of minutes). Writes the target
# vocal + F0 into example/transcriptions/target_user for wsl_soulx_svc.sh.
# Usage: wsl_fast_prep.sh <target_audio> [tag]
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
TARGET="${1:?usage: wsl_fast_prep.sh <target_audio> [tag]}"
TAG="${2:-xiaoyi}"

echo "[fast-prep] demucs vocal separation"
rm -rf "$HOME/soulx/demucs_out"
python -m demucs.separate --two-stems=vocals -d cuda -n htdemucs \
  -o "$HOME/soulx/demucs_out" "$TARGET"
STEM=$(basename "$TARGET")
STEM="${STEM%.*}"
VOC="$HOME/soulx/demucs_out/htdemucs/$STEM/vocals.wav"
if [ ! -f "$VOC" ]; then
  VOC=$(find "$HOME/soulx/demucs_out" -name "vocals.wav" | head -1)
fi
echo "[fast-prep] vocal: $VOC"

echo "[fast-prep] F0 extraction (rmvpe)"
rm -rf example/transcriptions/target_user
mkdir -p example/transcriptions/target_user
python -m preprocess.pipeline --audio_path "$VOC" \
  --save_dir example/transcriptions/target_user --language Mandarin \
  --device cuda --vocal_sep False --max_merge_duration 120000 \
  --midi_transcribe False
ls -la example/transcriptions/target_user
echo "[fast-prep] done"
