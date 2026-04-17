#!/usr/bin/env bash
# Relaunch your real Chrome with the Chrome DevTools Protocol exposed on
# localhost:9222 so Playwright can attach to it (set TV_CDP_URL=http://localhost:9222
# in tradingview/.env). Once running, leave this Chrome window open and
# scripts (create_layout.py, bridge.py, etc.) will drive it directly —
# no separate Chromium, no second login.
#
# Usage:
#     ./start_chrome_cdp.sh
#
# IMPORTANT — why a separate profile:
#   Since Chrome 136, --remote-debugging-port is SILENTLY DISABLED if
#   --user-data-dir points at the default profile. (Security: stops
#   malicious extensions from sniffing the debug port.) So we launch
#   Chrome against a dedicated automation profile. Sign into TradingView
#   once in it; cookies persist between runs just like a normal profile.
#
# IMPORTANT — single-instance lock:
#   Chrome won't open a second instance against a profile that's already
#   in use. Since the automation profile is separate, that's not an issue
#   here — your normal Chrome can keep running alongside.

set -euo pipefail

# We launch Playwright's BUNDLED Chromium rather than /Applications/Google Chrome.
# Why: retail Chrome 147 has a CDP protocol quirk around browser-level context
# management that Playwright (even 1.58) can't negotiate when attaching to an
# already-running browser. The bundled Chromium is version-matched to the
# Playwright client, so every CDP command works correctly. It's the same
# rendering engine — just the exact build Playwright ships with.
CHROME_BIN="$(
    ls -d "$HOME/Library/Caches/ms-playwright"/chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium 2>/dev/null \
      | sort -V | tail -1
)"
# Dedicated automation profile — separate from your real Chrome. Sign into
# TradingView ONCE in it; cookies persist here indefinitely.
CHROME_PROFILE_DIR="$HOME/Library/Application Support/Chromium-Automation"
DEBUG_PORT="${TV_CDP_PORT:-9222}"

if [[ -z "$CHROME_BIN" || ! -x "$CHROME_BIN" ]]; then
    echo "Error: Playwright Chromium not found. Run:" >&2
    echo "    .venv/bin/playwright install chromium" >&2
    exit 1
fi
echo "Using: $CHROME_BIN"

# Kill any prior automation-profile Chrome (your normal Chrome is untouched
# because it uses a different --user-data-dir and so is a separate process tree).
if pgrep -f -- "--user-data-dir=$CHROME_PROFILE_DIR" >/dev/null; then
    echo "Stopping prior automation Chrome..."
    pkill -f -- "--user-data-dir=$CHROME_PROFILE_DIR" || true
    sleep 1
fi

echo "Launching Chrome with CDP on port $DEBUG_PORT..."
echo "  Profile: $CHROME_PROFILE_DIR"
"$CHROME_BIN" \
    --remote-debugging-port="$DEBUG_PORT" \
    --user-data-dir="$CHROME_PROFILE_DIR" \
    --restore-last-session \
    >/dev/null 2>&1 &

# Verify the debug endpoint comes up. Chromium needs a few seconds of
# profile init on first run — poll for up to 30 seconds.
for _ in {1..60}; do
    if curl -sf "http://localhost:$DEBUG_PORT/json/version" >/dev/null; then
        echo "Chrome CDP ready: http://localhost:$DEBUG_PORT"
        echo
        echo "Set in tradingview/.env:"
        echo "    TV_CDP_URL=http://localhost:$DEBUG_PORT"
        exit 0
    fi
    sleep 0.5
done

echo "Chrome launched but CDP endpoint never came up on port $DEBUG_PORT." >&2
echo "Check that no other process is using the port and that the flag was honored." >&2
exit 3
