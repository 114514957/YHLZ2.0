#!/usr/bin/env bash
# Runner (WSL side) for verify_cover.py; usage:
#   wsl_verify_cover.sh <source_vocal.wav> <cover.wav> [--asr]
exec "$HOME/ddsp/venv/bin/python" "$(dirname "$0")/verify_cover.py" "$@"
