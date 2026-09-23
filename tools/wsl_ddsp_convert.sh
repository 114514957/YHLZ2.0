#!/usr/bin/env bash
# Standard DDSP conversion wrapper (ledger 0474):
#   peak-normalize (-1dB) -> main.py -k 0 -e true -pe rmvpe -th -80
# Normalization matters: main.py gates by ABSOLUTE volume (-60dB default),
# so quiet stems lost syllables (holes). -th -80 keeps quiet phrases.
# Usage: wsl_ddsp_convert.sh <vocal.wav> <out.wav> [model.pt]
set -e
IN="${1:?usage: wsl_ddsp_convert.sh <vocal.wav> <out.wav> [model.pt]}"
OUT="${2:?usage: wsl_ddsp_convert.sh <vocal.wav> <out.wav> [model.pt]}"
MODEL="${3:-$HOME/ddsp/DDSP-SVC/exp/combsub-test/model_400000.pt}"
cd "$HOME/ddsp/DDSP-SVC"
TMP="$HOME/ddsp/convert_tmp"
rm -rf "$TMP"; mkdir -p "$TMP"
"$HOME/soulx/venv/bin/python" - "$IN" "$TMP/norm.wav" <<'PY'
import sys, numpy as np, soundfile as sf
w, sr = sf.read(sys.argv[1], dtype="float32", always_2d=True)
pk = float(np.abs(w).max()) + 1e-9
sf.write(sys.argv[2], w * (0.891 / pk), sr)
print(f"[ddsp-convert] normalized input peak {pk:.3f} -> 0.891")
PY
"$HOME/ddsp/venv/bin/python" main.py -i "$TMP/norm.wav" -m "$MODEL" \
  -o "$OUT" -k 0 -e true -pe rmvpe -th -80
echo "[ddsp-convert] done: $OUT"
