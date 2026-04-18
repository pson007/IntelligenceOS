#!/usr/bin/env bash
# Start the IntelligenceOS Console UI server with auto-reload.
# Edits to .py files restart uvicorn; edits to ui/*.html|css|js are live
# because the server reads them fresh on each request.
#
# Usage:
#   ./run-ui.sh            # default: 127.0.0.1:8788, --reload
#   PORT=9000 ./run-ui.sh  # override port
set -euo pipefail
cd "$(dirname "$0")"
: "${HOST:=127.0.0.1}"
: "${PORT:=8788}"
exec .venv/bin/uvicorn ui_server:app --host "$HOST" --port "$PORT" --reload
