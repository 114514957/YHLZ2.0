#!/usr/bin/env bash
# Stage B (ledger 0458): SoulX-Singer SVC inference ONLY, using the prompt and
# target prepared by wsl_soulx_prep.sh. Needs the exclusive GPU window
# (peaks ~7.4GB). Usage: wsl_soulx_svc.sh <out_dir> [voice_tag]
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
OUT="${1:?usage: wsl_soulx_svc.sh <out_dir> [tag]}"
TAG="${2:-xiaoyi}"
PDIR="example/transcriptions/prompt_$TAG"
python -m cli.inference_svc --device cuda \
  --model_path pretrained_models/SoulX-Singer/model-svc.pt \
  --config soulxsinger/config/soulxsinger.yaml \
  --prompt_wav_path "$PDIR/vocal.wav" \
  --target_wav_path example/transcriptions/target_user/vocal.wav \
  --prompt_f0_path "$PDIR/vocal_f0.npy" \
  --target_f0_path example/transcriptions/target_user/vocal_f0.npy \
  --save_dir "$OUT" --auto_shift --pitch_shift 0
echo "output: $OUT/generated.wav"
