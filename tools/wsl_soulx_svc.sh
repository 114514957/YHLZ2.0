#!/usr/bin/env bash
# SoulX-Singer SVC one-shot: timbre of <prompt.wav> -> cover of <target song>.
# Ledger 0456/0457. Run inside WSL2 after Windows frees the GPU (the daemon's
# gpu_window does that; SVC peaks ~7.4GB and cannot coexist with the LLM).
#
# Usage: bash tools/wsl_soulx_svc.sh <prompt.wav> <target_audio> [out_dir]
# Both prompt and target are preprocessed here (F0 only, no vocal separation);
# dry vocals / humming convert best, full songs are acceptable for a demo.
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
PROMPT="${1:?usage: wsl_soulx_svc.sh <prompt.wav> <target_audio> [out_dir]}"
TARGET="${2:?}"
OUT="${3:-example/generated/svc}"

echo "[1/3] prompt preprocess (f0 only)"
cp "$PROMPT" example/audio/prompt_user.wav
python -m preprocess.pipeline --audio_path example/audio/prompt_user.wav \
  --save_dir example/transcriptions/prompt_user --language Mandarin --device cuda \
  --vocal_sep False --max_merge_duration 30000 --midi_transcribe False

echo "[2/3] target preprocess (f0 only)"
EXT="${TARGET##*.}"
cp "$TARGET" "example/audio/target_user.$EXT"
python -m preprocess.pipeline --audio_path "example/audio/target_user.$EXT" \
  --save_dir example/transcriptions/target_user --language Mandarin --device cuda \
  --vocal_sep False --max_merge_duration 120000 --midi_transcribe False

echo "[3/3] SVC inference"
python -m cli.inference_svc --device cuda \
  --model_path pretrained_models/SoulX-Singer/model-svc.pt \
  --config soulxsinger/config/soulxsinger.yaml \
  --prompt_wav_path example/transcriptions/prompt_user/vocal.wav \
  --target_wav_path example/transcriptions/target_user/vocal.wav \
  --prompt_f0_path example/transcriptions/prompt_user/vocal_f0.npy \
  --target_f0_path example/transcriptions/target_user/vocal_f0.npy \
  --save_dir "$OUT" --auto_shift --pitch_shift 0
echo "output: $OUT/generated.wav"
