#!/usr/bin/env bash
# 1runOS — desktop launcher for the Electron app.
#
# Double-clickable launcher mirroring `IntelligenceOS UI.command` but
# opening the native Electron window instead of the browser. Behavior:
#   1. Start Chrome CDP (port 9222) if not already up — required for
#      Playwright/TV automation backend.
#   2. Start the UI server (uvicorn on 127.0.0.1:8788) only if not
#      already responding — won't disturb a running session.
#   3. Wait for /api/health.
#   4. Launch electron `electron .` from the electron/ dir, backgrounded
#      via nohup so Terminal can be closed without killing the app.
#
# Idempotent: re-running while the app is already up just opens a new
# Electron window against the existing server.

set -eu

REPO_DIR="/Users/pson/Desktop/IntelligenceOS"
TV_DIR="$REPO_DIR/tradingview"
ELECTRON_DIR="$REPO_DIR/electron"
UI_URL="http://127.0.0.1:8788"
CDP_URL="http://localhost:9222"
LOG="/tmp/ui_server.log"
ELECTRON_LOG="/tmp/1runos_electron.log"

echo "──────────────────────────────────────────────"
echo "  1runOS — launching Electron app"
echo "──────────────────────────────────────────────"
echo

# 1. Chrome CDP (required by tv_automation backend).
if curl -sf --max-time 2 "$CDP_URL/json/version" > /dev/null 2>&1; then
    echo "→ Chrome CDP already up at $CDP_URL"
else
    echo "→ starting Chrome with CDP…"
    cd "$TV_DIR"
    ./start_chrome_cdp.sh
fi

# 2. UI server — only start if not already healthy. Avoids disrupting
# an in-flight act/analyze/profile run.
if curl -sf --max-time 1 "$UI_URL/api/health" > /dev/null 2>&1; then
    echo "→ UI server already healthy at $UI_URL"
else
    echo "→ starting UI server…"
    cd "$TV_DIR"
    nohup ./run-ui.sh > "$LOG" 2>&1 &
    disown

    # 3. Wait for /api/health.
    echo -n "→ waiting for server"
    for _ in $(seq 1 40); do
        if curl -sf --max-time 1 "$UI_URL/api/health" > /dev/null 2>&1; then
            echo " ✓"
            break
        fi
        echo -n "."
        sleep 0.5
    done

    if ! curl -sf --max-time 1 "$UI_URL/api/health" > /dev/null 2>&1; then
        echo
        echo "ERROR: UI server didn't respond within 20s. Last log lines:" >&2
        tail -20 "$LOG" >&2
        echo
        read -r -p "Press Return to close…" _
        exit 1
    fi
fi

# 4. Launch Electron, backgrounded. ONERUN_DEV=1 puts the app in dev
# mode so it attaches to the existing Python server rather than spawning
# its own (we manage the server lifecycle in this script).
echo "→ launching Electron app…"
cd "$ELECTRON_DIR"
if [ ! -x "node_modules/.bin/electron" ]; then
    echo "ERROR: electron binary missing at $ELECTRON_DIR/node_modules/.bin/electron" >&2
    echo "       Run: cd $ELECTRON_DIR && npm install" >&2
    read -r -p "Press Return to close…" _
    exit 1
fi
ONERUN_DEV=1 nohup ./node_modules/.bin/electron . > "$ELECTRON_LOG" 2>&1 &
disown

echo
echo "──────────────────────────────────────────────"
echo "  UI:        $UI_URL"
echo "  Server log: $LOG"
echo "  App log:    $ELECTRON_LOG"
echo "  Stop UI:   pkill -f 'uvicorn ui_server'"
echo "  Stop app:  Cmd-Q in the Electron window"
echo "──────────────────────────────────────────────"
echo
echo "This Terminal window can be closed."
