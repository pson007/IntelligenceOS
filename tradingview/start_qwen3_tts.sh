#!/usr/bin/env bash
# Boot the Qwen3-TTS sidecar in the 1runapp MLX venv.
#
# Why a separate venv: this stack pulls in mlx, mlx-audio, qwen_tts,
# and bf16 weights — different version pins than IntelligenceOS's
# Playwright/OpenAI/Anthropic deps. Disjoint venvs avoid conflicts;
# localhost HTTP is the integration boundary.
#
# The MLX model loads ~once and stays warm across IntelligenceOS
# uvicorn reloads, which an in-process implementation cannot offer.
set -euo pipefail

VENV="${QWEN3_TTS_VENV:-$HOME/Library/Application Support/1runapp/qwen3-tts-venv}"
PORT="${QWEN3_TTS_PORT:-8790}"
HOST="${QWEN3_TTS_HOST:-127.0.0.1}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "qwen3-tts venv not found at: $VENV" >&2
  echo "Set QWEN3_TTS_VENV to override." >&2
  exit 1
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec "$VENV/bin/python" "$SCRIPT_DIR/tts_sidecar.py" \
  --host "$HOST" \
  --port "$PORT" \
  "$@"
