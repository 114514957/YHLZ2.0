#!/usr/bin/env bash
# Stage B (ledger 0458): SoulX-Singer SVC inference ONLY, using the prompt and
# target prepared by wsl_soulx_prep.sh. Needs the exclusive GPU window
# (peaks ~7.4GB). Usage: wsl_soulx_svc.sh <out_dir> [voice_tag] [raw|auto]
#
# STANDARD (v7, ledger 0488): keep n_steps/cfg at defaults — do NOT pass
# --n_steps/--cfg overrides here (v8 proved cfg>3 destroys timbre/level).
set -e
cd "$HOME/soulx/SoulX-Singer"
export PATH="$HOME/soulx/venv/bin:$PATH"
export HF_ENDPOINT=https://hf-mirror.com
OUT="${1:?usage: wsl_soulx_svc.sh <out_dir> [tag] [raw|auto]}"
TAG="${2:-xiaoyi}"
MODE="${3:-raw}"
PDIR="example/transcriptions/prompt_$TAG"
if [ "$MODE" = "raw" ]; then
  SHIFT_ARGS=()
else
  SHIFT_ARGS=(--auto_shift --pitch_shift 0)
fi
# fp16 on by default: 10x faster + much lower VRAM on the 8GB card (ledger 0466)
FP16_ARGS=(--fp16)
if [ "${SOULX_FP16:-1}" = "0" ]; then
  FP16_ARGS=()
fi
python -m cli.inference_svc --device cuda \
  --model_path pretrained_models/SoulX-Singer/model-svc.pt \
  --config soulxsinger/config/soulxsinger.yaml \
  --prompt_wav_path "$PDIR/vocal.wav" \
  --target_wav_path example/transcriptions/target_user/vocal.wav \
  --prompt_f0_path "$PDIR/vocal_f0.npy" \
  --target_f0_path example/transcriptions/target_user/vocal_f0.npy \
  --save_dir "$OUT" "${SHIFT_ARGS[@]}" "${FP16_ARGS[@]}"
echo "output: $OUT/generated.wav"
