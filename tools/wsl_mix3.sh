#!/usr/bin/env bash
# Runner for wsl_mix3.py (soulx venv has numpy/soundfile/librosa).
exec "$HOME/soulx/venv/bin/python" "$(dirname "$0")/wsl_mix3.py" "$@"
