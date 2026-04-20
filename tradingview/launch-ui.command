#!/usr/bin/env bash
# IntelligenceOS — fresh launch.
#
# Double-clickable launcher for the trading console. Restarts the UI
# server cleanly, starts the attached Chrome (with CDP on 9222) if it's
# not already running, and opens the console in the browser.
#
# "Fresh clean" means: UI server restarted (kills any stale uvicorn,
# brings up a new one). Chrome is NOT restarted if it's already running
# — cookies + open tabs persist. To force a full Chrome reset, close
# the Chromium-Automation window manually and re-run this launcher.

set -eu

REPO_DIR="/Users/pson/Desktop/IntelligenceOS/tradingview"
UI_URL="http://127.0.0.1:8788"
CDP_URL="http://localhost:9222"
LOG="/tmp/ui_server.log"

echo "──────────────────────────────────────────────"
echo "  IntelligenceOS — fresh launch"
echo "──────────────────────────────────────────────"
echo

cd "$REPO_DIR" || {
    echo "ERROR: repo not found at $REPO_DIR" >&2
    exit 1
}

# 1. Kill any stale UI server. `|| true` so an empty-kill doesn't
# exit -e the script.
if pgrep -f 'uvicorn ui_server' > /dev/null 2>&1; then
    echo "→ stopping existing UI server…"
    pkill -f 'uvicorn ui_server' || true
    sleep 1
    # Belt + suspenders: SIGKILL anything that ignored SIGTERM.
    pkill -9 -f 'uvicorn ui_server' 2>/dev/null || true
fi

# 2. Start Chrome CDP if not reachable. The start script is idempotent
# for the profile — it kills any prior Chrome on the same profile
# before relaunching — so we call it unconditionally when CDP is down.
if curl -sf --max-time 2 "$CDP_URL/json/version" > /dev/null 2>&1; then
    echo "→ Chrome CDP already up at $CDP_URL"
else
    echo "→ starting Chrome with CDP…"
    ./start_chrome_cdp.sh
fi

# 3. Start UI server, backgrounded, logs to /tmp/ui_server.log.
echo "→ starting UI server…"
nohup ./run-ui.sh > "$LOG" 2>&1 &
disown

# 4. Wait for the server to bind. Poll /api/health; give up at 20s so
# a stuck start doesn't leave the launcher hanging.
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

# 5. Open the console. `open` hands off to the user's default browser.
echo "→ opening $UI_URL"
open "$UI_URL"

echo
echo "──────────────────────────────────────────────"
echo "  UI:      $UI_URL"
echo "  Log:     $LOG  (tail -f for streaming)"
echo "  Stop:    pkill -f 'uvicorn ui_server'"
echo "──────────────────────────────────────────────"
echo
echo "This Terminal window can be closed."
