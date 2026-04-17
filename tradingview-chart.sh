#!/bin/bash
# tradingview-chart.sh
# Opens TradingView in Safari, loads a specific ticker/symbol, sets the timeframe,
# and optionally captures a screenshot of the chart.
#
# Usage:
#   ./tradingview-chart.sh AAPL              # Load AAPL on current timeframe
#   ./tradingview-chart.sh AAPL 1D           # Load AAPL on Daily
#   ./tradingview-chart.sh AAPL 15m          # Load AAPL on 15-minute
#   ./tradingview-chart.sh AAPL 1h --screenshot  # Load + screenshot
#   ./tradingview-chart.sh --screenshot      # Screenshot current chart
#
# Timeframes: 1m, 2m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1D, 1W, 1M
#
# Screenshots are saved to ~/Desktop/TradingView/

set -euo pipefail

SYMBOL=""
TIMEFRAME=""
SCREENSHOT=false

# ── Parse arguments ──────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --screenshot|-s)
            SCREENSHOT=true
            ;;
        1m|2m|3m|5m|15m|30m|1h|2h|4h|1D|1W|1M)
            TIMEFRAME="$arg"
            ;;
        *)
            if [ -z "$SYMBOL" ]; then
                SYMBOL="$arg"
            fi
            ;;
    esac
done

# ── Map timeframe to TradingView URL interval parameter ──────────
get_interval() {
    case "$1" in
        1m)   echo "1"   ;;
        2m)   echo "2"   ;;
        3m)   echo "3"   ;;
        5m)   echo "5"   ;;
        15m)  echo "15"  ;;
        30m)  echo "30"  ;;
        1h)   echo "60"  ;;
        2h)   echo "120" ;;
        4h)   echo "240" ;;
        1D)   echo "D"   ;;
        1W)   echo "W"   ;;
        1M)   echo "M"   ;;
        *)    echo ""     ;;
    esac
}

# ── Step 1: Build TradingView URL and open in Safari ─────────────
BASE_URL="https://www.tradingview.com/chart/"
PARAMS=""

if [ -n "$SYMBOL" ]; then
    PARAMS="?symbol=${SYMBOL}"
fi

if [ -n "$TIMEFRAME" ]; then
    INTERVAL=$(get_interval "$TIMEFRAME")
    if [ -n "$INTERVAL" ]; then
        if [ -n "$PARAMS" ]; then
            PARAMS="${PARAMS}&interval=${INTERVAL}"
        else
            PARAMS="?interval=${INTERVAL}"
        fi
    fi
fi

URL="${BASE_URL}${PARAMS}"

# Check if Safari already has a TradingView tab open
EXISTING_TAB=$(osascript -e '
tell application "Safari"
    set tabIndex to 0
    set winIndex to 0
    repeat with w in windows
        set winIndex to winIndex + 1
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            if URL of t contains "tradingview.com/chart" then
                return (winIndex as text) & "," & (tabIndex as text)
            end if
        end repeat
    end repeat
    return ""
end tell
' 2>/dev/null || echo "")

if [ -n "$EXISTING_TAB" ] && [ -n "$SYMBOL" -o -n "$TIMEFRAME" ]; then
    # Reuse existing TradingView tab
    WIN_IDX=$(echo "$EXISTING_TAB" | cut -d',' -f1)
    TAB_IDX=$(echo "$EXISTING_TAB" | cut -d',' -f2)
    osascript -e "
    tell application \"Safari\"
        activate
        set current tab of window ${WIN_IDX} to tab ${TAB_IDX} of window ${WIN_IDX}
        set URL of tab ${TAB_IDX} of window ${WIN_IDX} to \"${URL}\"
    end tell
    "
    echo "Updated existing TradingView tab: ${URL}"
elif [ -n "$EXISTING_TAB" ]; then
    # Just activate the existing tab (no new symbol/timeframe requested)
    WIN_IDX=$(echo "$EXISTING_TAB" | cut -d',' -f1)
    TAB_IDX=$(echo "$EXISTING_TAB" | cut -d',' -f2)
    osascript -e "
    tell application \"Safari\"
        activate
        set current tab of window ${WIN_IDX} to tab ${TAB_IDX} of window ${WIN_IDX}
    end tell
    "
    echo "Activated existing TradingView tab."
else
    # Open new tab
    osascript -e "
    tell application \"Safari\"
        activate
        if (count of windows) = 0 then
            make new document with properties {URL:\"${URL}\"}
        else
            tell front window
                set newTab to make new tab with properties {URL:\"${URL}\"}
                set current tab to newTab
            end tell
        end if
    end tell
    "
    echo "Opened TradingView in Safari: ${URL}"
fi

[ -n "$SYMBOL" ] && echo "Loaded symbol: $SYMBOL"
[ -n "$TIMEFRAME" ] && echo "Set timeframe: $TIMEFRAME"

# ── Step 2: Wait for chart to render ─────────────────────────────
# Allow extra time for initial page load vs. just a symbol change
if [ -n "$EXISTING_TAB" ] && [ -n "$SYMBOL" -o -n "$TIMEFRAME" ]; then
    sleep 3
else
    sleep 5
fi

# ── Step 3: Capture screenshot ───────────────────────────────────
if [ "$SCREENSHOT" = true ]; then
    SCREENSHOT_DIR="$HOME/Desktop/TradingView"
    mkdir -p "$SCREENSHOT_DIR"

    # Extra render time for screenshot
    sleep 1.5

    # Build filename
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    if [ -n "$SYMBOL" ] && [ -n "$TIMEFRAME" ]; then
        FILENAME="${SYMBOL}_${TIMEFRAME}_${TIMESTAMP}.png"
    elif [ -n "$SYMBOL" ]; then
        FILENAME="${SYMBOL}_${TIMESTAMP}.png"
    else
        FILENAME="chart_${TIMESTAMP}.png"
    fi

    FILEPATH="${SCREENSHOT_DIR}/${FILENAME}"

    # Capture Safari's front window via window ID
    WINDOW_ID=$(osascript -e '
    tell application "System Events"
        tell process "Safari"
            set frontWin to front window
            return id of frontWin
        end tell
    end tell
    ' 2>/dev/null || echo "")

    if [ -n "$WINDOW_ID" ] && [ "$WINDOW_ID" != "0" ]; then
        screencapture -l "$WINDOW_ID" "$FILEPATH"
    else
        # Fallback: capture frontmost window silently
        screencapture -w -o "$FILEPATH" 2>/dev/null || \
        screencapture -x "$FILEPATH"
    fi

    echo "Screenshot saved: $FILEPATH"
fi

echo "TradingView automation complete."
