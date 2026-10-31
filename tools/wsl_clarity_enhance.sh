#!/usr/bin/env bash
# Runner for wsl_clarity_enhance.py (soulx venv has librosa/soundfile/scipy).
exec "$HOME/soulx/venv/bin/python" "$(dirname "$0")/wsl_clarity_enhance.py" "$@"
