#!/usr/bin/env bash
# MSST toolkit chain (2026-09-23; fixed 0472): vocals/instrumental (Kim) ->
# lead(主唱+同度叠唱)/harmony(真和三度) via MDX karaoke -> {lead,backing,bgm}.wav
# NOTE: aufr33 roformer karaoke was replaced — it left the original unison
# double in the "harmony" stem, so the original voice stayed in the mix.
# Usage: wsl_msst_chain.sh <mix_audio> <out_dir>
set -e
MIX="${1:?usage: wsl_msst_chain.sh <mix> <out_dir>}"
OUT="${2:?usage: wsl_msst_chain.sh <mix> <out_dir>}"
GUI="$HOME/msst-gui-src"
PY="$HOME/soulx/venv/bin/python"
TMP="$HOME/msst_chain"
cd "$GUI"
export HF_ENDPOINT=https://hf-mirror.com

echo "[chain] reset tmp"
rm -rf "$TMP"; mkdir -p "$TMP/in" "$TMP/voc" "$TMP/kara/out"
cp "$MIX" "$TMP/in/"

echo "[chain] 1/2 vocals+instrumental (Kim)"
"$PY" inference.py --model_type mel_band_roformer \
  --config_path configs/config_vocals_mel_band_roformer_kim.yaml \
  --start_check_point pretrain/MelBandRoformer_kim.ckpt \
  --input_folder "$TMP/in" --store_dir "$TMP/voc" --extract_instrumental \
  > "$TMP/voc.log" 2>&1

VOC=$(find "$TMP/voc" -name "vocals.wav" | head -1)
BGM=$(find "$TMP/voc" -name "instrumental.wav" | head -1)
[ -n "$VOC" ] && [ -n "$BGM" ] || { echo "[chain] vocals step failed"; tail -5 "$TMP/voc.log"; exit 2; }

echo "[chain] 2/2 lead+harmony (MDX karaoke; keeps unison doubles with lead)"
"$HOME/soulx/venv/bin/audio-separator" "$VOC" \
  --model_filename UVR_MDXNET_KARA_2.onnx \
  --model_file_dir "$HOME/soulx/sep_models" \
  --output_dir "$TMP/kara/out" --output_format WAV > "$TMP/kara.log" 2>&1

LEAD=$(find "$TMP/kara/out" -name "*_(Vocals)_*" | head -1)
HARM=$(find "$TMP/kara/out" -name "*_(Instrumental)_*" | head -1)
[ -n "$LEAD" ] && [ -n "$HARM" ] || { echo "[chain] karaoke step failed"; tail -5 "$TMP/kara.log"; exit 3; }

mkdir -p "$OUT"
cp "$LEAD" "$OUT/lead.wav"
cp "$HARM" "$OUT/backing.wav"
cp "$BGM" "$OUT/bgm.wav"
ls -la "$OUT"
echo "[chain] done"
