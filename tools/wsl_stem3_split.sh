#!/usr/bin/env bash
# 3-stem split (2026-09-23): demucs -> vocals/no_vocals; MDX karaoke on vocals
# -> lead(主唱)/backing(和声). Outputs <out_dir>/{lead,backing,bgm}.wav
# Usage: wsl_stem3_split.sh <mix_audio> <out_dir>
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
MIX="${1:?usage: wsl_stem3_split.sh <mix> <out_dir>}"
OUT="${2:?usage: wsl_stem3_split.sh <mix> <out_dir>}"
mkdir -p "$OUT"

echo "[stem3] demucs: vocals / no_vocals"
rm -rf "$HOME/soulx/demucs_out"
python -m demucs.separate --two-stems=vocals -d cuda -n htdemucs \
  -o "$HOME/soulx/demucs_out" "$MIX" >/dev/null 2>&1
VOC=$(find "$HOME/soulx/demucs_out" -name "vocals.wav" | head -1)
NOVOC=$(find "$HOME/soulx/demucs_out" -name "no_vocals.wav" | head -1)
if [ -z "$VOC" ] || [ -z "$NOVOC" ]; then
  echo "[stem3] demucs failed"; exit 2
fi
cp "$NOVOC" "$OUT/bgm.wav"

echo "[stem3] MDX karaoke: lead / backing"
TMP="$HOME/soulx/stem3_tmp"
rm -rf "$TMP"; mkdir -p "$TMP"
audio-separator "$VOC" --model_filename UVR_MDXNET_KARA_2.onnx \
  --model_file_dir "$HOME/soulx/sep_models" --output_dir "$TMP" \
  --output_format WAV >/dev/null 2>&1
LEAD=$(find "$TMP" -name "*Vocals*" | head -1)
BACK=$(find "$TMP" -name "*Instrumental*" | head -1)
if [ -z "$LEAD" ] || [ -z "$BACK" ]; then
  echo "[stem3] karaoke split failed"; exit 3
fi
cp "$LEAD" "$OUT/lead.wav"
cp "$BACK" "$OUT/backing.wav"
ls -la "$OUT"
echo "[stem3] done"
