#!/usr/bin/env bash
# MSST toolkit chain (2026-09-23): vocals/instrumental (Kim) ->
# lead(主唱)/harmony(和声) (aufr33 karaoke) -> outputs {lead,backing,bgm}.wav
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
rm -rf "$TMP"; mkdir -p "$TMP/in" "$TMP/voc" "$TMP/kara/in" "$TMP/kara/out"
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
cp "$VOC" "$TMP/kara/in/"

echo "[chain] 2/2 lead+harmony (aufr33 karaoke)"
"$PY" inference.py --model_type mel_band_roformer \
  --config_path configs/config_mel_band_roformer_karaoke.yaml \
  --start_check_point pretrain/mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt \
  --input_folder "$TMP/kara/in" --store_dir "$TMP/kara/out" --extract_instrumental \
  > "$TMP/kara.log" 2>&1

LEAD=$(find "$TMP/kara/out" -name "karaoke.wav" | head -1)
HARM=$(find "$TMP/kara/out" -name "instrumental.wav" | head -1)
[ -n "$LEAD" ] && [ -n "$HARM" ] || { echo "[chain] karaoke step failed"; tail -5 "$TMP/kara.log"; exit 3; }

mkdir -p "$OUT"
cp "$LEAD" "$OUT/lead.wav"
cp "$HARM" "$OUT/backing.wav"
cp "$BGM" "$OUT/bgm.wav"
ls -la "$OUT"
echo "[chain] done"
