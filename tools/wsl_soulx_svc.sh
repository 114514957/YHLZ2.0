#!/usr/bin/env bash
# SoulX-Singer SVC one-shot: timbre of <prompt.wav> -> cover of <target.mp3>.
# Ledger 0456. Run inside WSL2 after Windows frees the GPU (stop llama-server
# and the watchdog; SVC peaks ~7.4GB and cannot coexist with the LLM).
#
# Usage: bash tools/wsl_soulx_svc.sh <prompt.wav> <target.mp3> [out_dir]
# Note: target F0 must already exist next to the target as "<stem>_f0.npy"
#       (compute with `python -m preprocess.pipeline ... --midi_transcribe False`).
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
PROMPT="${1:?usage: wsl_soulx_svc.sh <prompt.wav> <target.mp3> [out_dir]}"
TARGET="${2:?}"
OUT="${3:-example/generated/svc}"

cp "$PROMPT" example/audio/prompt_user.wav
python -m preprocess.pipeline --audio_path example/audio/prompt_user.wav \
  --save_dir example/transcriptions/prompt_user --language Mandarin --device cuda \
  --vocal_sep False --max_merge_duration 30000 --midi_transcribe False

python -m cli.inference_svc --device cuda \
  --model_path pretrained_models/SoulX-Singer/model-svc.pt \
  --config soulxsinger/config/soulxsinger.yaml \
  --prompt_wav_path example/transcriptions/prompt_user/vocal.wav \
  --target_wav_path "$TARGET" \
  --prompt_f0_path example/transcriptions/prompt_user/vocal_f0.npy \
  --target_f0_path "${TARGET%.*}_f0.npy" \
  --save_dir "$OUT" --auto_shift --pitch_shift 0
echo "output: $HOME/soulx/SoulX-Singer/$OUT/generated.wav"
