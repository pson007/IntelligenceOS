#!/usr/bin/env bash
# Dispatch wrapper for scheduled IntelligenceOS jobs (launchd).
#
# Responsibilities:
#   1. Preflight — is today a market day? Is CDP up at 9222? Is the venv there?
#   2. Dispatch to the right Python CLI based on $1.
#   3. Log per-job to /tmp/intelligenceos_<job>.log (truncated per-run).
#   4. On CDP-down, fire a Mac notification so the operator knows to start
#      Chrome; exits non-zero so launchd logs the failure too.
#
# Usage:
#   scheduled_run.sh pre_session
#   scheduled_run.sh f1 | f2 | f3
#   scheduled_run.sh eod           # daily_profile + forecast_reconcile
#
# All paths are absolute — launchd runs jobs with a minimal environment
# and no assumed PWD, so don't rely on $HOME or $PATH being set the way
# a login shell sees them.

set -uo pipefail

JOB="${1:-}"
if [[ -z "$JOB" ]]; then
    echo "usage: $0 <pre_session|f1|f2|f3|eod>" >&2
    exit 64
fi

REPO="/Users/pson/Desktop/IntelligenceOS"
TV="$REPO/tradingview"
VENV_PY="$TV/.venv/bin/python"
LOG="/tmp/intelligenceos_${JOB}.log"

# Truncate per-run so each job log reflects the latest fire only. The
# audit log in $TV/audit/ retains the historical trail.
: > "$LOG"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" | tee -a "$LOG"
}

notify() {
    # macOS notification. -e form survives launchd's minimal env because
    # /usr/bin/osascript is absolute and always present on macOS.
    local title="$1" body="$2"
    /usr/bin/osascript -e "display notification \"${body//\"/\\\"}\" with title \"${title//\"/\\\"}\"" \
        >/dev/null 2>&1 || true
}

log "=== IntelligenceOS scheduled job: $JOB ==="

# High-frequency jobs run their own preflight without the shared notify
# spam. canary_evaluate fires every 5 min during the morning — if CDP is
# down, we don't want 36 notifications between 09:00 and 12:00.
if [[ "$JOB" == "canary_evaluate" ]]; then
    if ! /usr/bin/curl -sf --max-time 3 http://localhost:9222/json/version >/dev/null 2>&1; then
        log "SKIP: Chrome CDP not responding (silent — canary fires every 5min)"
        exit 0
    fi
    if ! /usr/bin/curl -sf --max-time 3 http://127.0.0.1:8788/api/health >/dev/null 2>&1; then
        log "SKIP: UI server not running on :8788 (silent — canary fires every 5min)"
        exit 0
    fi
fi

# --- Preflight: Python venv -------------------------------------------------
if [[ ! -x "$VENV_PY" ]]; then
    log "ABORT: venv python not executable at $VENV_PY"
    notify "IntelligenceOS $JOB" "venv missing — check $VENV_PY"
    exit 1
fi

# --- Preflight: market day --------------------------------------------------
if ! (cd "$TV" && "$VENV_PY" -m tv_automation.market_calendar >>"$LOG" 2>&1); then
    log "SKIP: not a market day (weekend or CME holiday)"
    exit 0
fi

# --- Preflight: CDP up ------------------------------------------------------
if ! /usr/bin/curl -sf --max-time 3 http://localhost:9222/json/version >/dev/null 2>&1; then
    log "ABORT: Chrome CDP not responding at localhost:9222"
    notify "IntelligenceOS $JOB skipped" "Start Chrome CDP (./start_chrome_cdp.sh)"
    exit 1
fi

# --- Dispatch ---------------------------------------------------------------
cd "$TV" || { log "ABORT: cd $TV failed"; exit 1; }

run_py() {
    # $@: args to "python -m tv_automation.<module>"
    log "RUN: $VENV_PY -m $*"
    if "$VENV_PY" -m "$@" >>"$LOG" 2>&1; then
        log "OK: $1 exit=0"
        return 0
    else
        local rc=$?
        log "FAIL: $1 exit=$rc"
        notify "IntelligenceOS $JOB failed" "exit=$rc — tail -f $LOG"
        return $rc
    fi
}

case "$JOB" in
    pre_session)
        run_py tv_automation.pre_session_forecast
        ;;
    f1)
        run_py tv_automation.live_forecast F1
        ;;
    f2)
        run_py tv_automation.live_forecast F2
        ;;
    f3)
        run_py tv_automation.live_forecast F3
        ;;
    eod)
        # Profile first (ground truth), then reconcile. Reconcile is
        # allowed to soft-fail — missing forecasts shouldn't kill the
        # overall job since the profile is still useful on its own.
        rc=0
        run_py tv_automation.daily_profile "$(/bin/date '+%Y-%m-%d')" || rc=$?
        if [[ $rc -eq 0 ]]; then
            run_py tv_automation.forecast_reconcile || true
        fi
        exit $rc
        ;;
    canary_evaluate)
        # Re-evaluate today's MNQ1 canary thesis against the live chart.
        # Fires every 5 min between 09:00–12:00 ET on weekdays. Restrained
        # error handling: this runs ~36×/day, so any notification surface
        # would spam — log-only, never notify, exit 0 even on transient
        # endpoint failures (the evaluator status file is the source of
        # truth, not the per-fire exit code). When no pre-session canary
        # exists for today, the endpoint returns {ok:false, reason:no_canary}
        # which is fine — we just log + exit.
        TODAY="$(/bin/date '+%Y-%m-%d')"
        # Read UI_TOKEN from .env (KEY=VALUE format); never log it.
        UI_TOKEN=""
        if [[ -f "$TV/.env" ]]; then
            UI_TOKEN="$(/usr/bin/grep -E '^UI_TOKEN=' "$TV/.env" | /usr/bin/head -n 1 | /usr/bin/sed 's/^UI_TOKEN=//')"
        fi
        if [[ -z "$UI_TOKEN" ]]; then
            log "ABORT: no UI_TOKEN in $TV/.env"
            exit 1
        fi
        URL="http://127.0.0.1:8788/api/canary/MNQ1/${TODAY}/evaluate"
        log "POST $URL"
        # -s silent, -S still surface errors, --max-time 30 — chart read
        # should be a few seconds. Capture stdout to log; non-200s flag
        # via -f, which sets exit code 22.
        RESP="$(/usr/bin/curl -sS --max-time 30 \
            -X POST \
            -H 'X-UI: 1' \
            -H "X-UI-Token: $UI_TOKEN" \
            -H 'Content-Type: application/json' \
            -w '\n__HTTP_CODE__:%{http_code}\n' \
            "$URL" 2>&1)" || true
        log "$RESP"
        # Soft exit — never escalate transient errors to launchd ABORTs.
        exit 0
        ;;
    *)
        log "ABORT: unknown job $JOB"
        exit 64
        ;;
esac
