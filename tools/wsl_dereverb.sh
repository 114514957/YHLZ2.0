#!/usr/bin/env bash
# MSST 去混响 wrapper (v3 定版, 2026-10-11, 老爹选定 V3-e)：干声先过 anvuew
# mel-band-roformer（SDR 19.17）再去 SVC。GPU 小，可与聊天共享（不用唱窗）。
# Usage: wsl_dereverb.sh <in.wav> <out.wav>
set -e
IN="${1:?usage: wsl_dereverb.sh <in.wav> <out.wav>}"
OUT="${2:?usage: wsl_dereverb.sh <in.wav> <out.wav>}"
GUI="$HOME/msst-gui-src"
PY="$HOME/soulx/venv/bin/python"
TMP="$HOME/msst_derev"
cd "$GUI"
export HF_ENDPOINT=https://hf-mirror.com
rm -rf "$TMP"; mkdir -p "$TMP/in" "$TMP/out"
cp "$IN" "$TMP/in/"
echo "[dereverb] anvuew mel_band_roformer"
"$PY" inference.py --model_type mel_band_roformer \
  --config_path configs/dereverb_mel_band_roformer_anvuew.yaml \
  --start_check_point pretrain/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt \
  --input_folder "$TMP/in" --store_dir "$TMP/out" > "$TMP/run.log" 2>&1
F=$(find "$TMP/out" -name "*.wav" | head -1)
if [ -z "$F" ]; then echo "[dereverb] failed"; tail -5 "$TMP/run.log"; exit 2; fi
cp "$F" "$OUT"
ls -la "$OUT"
echo "[dereverb] done"
