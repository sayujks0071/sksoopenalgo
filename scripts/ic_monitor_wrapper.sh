#!/bin/bash
# ── IC Monitor Wrapper — Auto-restart on crash with market-hours guard ────────
# Used by LaunchAgent com.openalgo.ic-monitor to keep ic_monitor.py alive
# Only runs during market hours (Mon-Fri 9:15 AM - 3:35 PM IST)
# ──────────────────────────────────────────────────────────────────────────────
LOG="/Users/mac/openalgo/log/ic_monitor_wrapper.log"
IC_MONITOR="/Users/mac/openalgo/ic_monitor.py"
PID_FILE="/tmp/ic_monitor.pid"
MAX_RESTARTS=3
RESTART_COUNT=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

is_market_hours() {
    local dow=$(date +%u)  # 1=Mon, 7=Sun
    local hhmm=$(TZ="Asia/Kolkata" date +%H%M)
    # Mon-Fri, 9:15 AM to 3:35 PM IST
    [ "$dow" -le 5 ] && [ "$hhmm" -ge 0915 ] && [ "$hhmm" -le 1535 ]
}

cleanup() {
    log "Wrapper received signal — shutting down"
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null
            sleep 2
            kill -9 "$pid" 2>/dev/null
        fi
    fi
    exit 0
}
trap cleanup SIGTERM SIGINT

log "=== IC Monitor Wrapper Started ==="

while true; do
    if ! is_market_hours; then
        log "Outside market hours — sleeping 60s"
        sleep 60
        RESTART_COUNT=0  # reset restarts at market open
        continue
    fi

    if [ "$RESTART_COUNT" -ge "$MAX_RESTARTS" ]; then
        log "ERROR: Max restarts ($MAX_RESTARTS) reached — stopping until next market open"
        while is_market_hours; do sleep 300; done
        RESTART_COUNT=0
        continue
    fi

    # Clean stale PID
    if [ -f "$PID_FILE" ]; then
        old_pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            log "ic_monitor already running (PID $old_pid) — monitoring"
            wait "$old_pid" 2>/dev/null || sleep 30
            continue
        else
            rm -f "$PID_FILE"
        fi
    fi

    log "Starting ic_monitor.py (restart #$RESTART_COUNT)"
    cd /Users/mac/openalgo
    python3 "$IC_MONITOR" >> "$LOG" 2>&1 &
    IC_PID=$!
    echo "$IC_PID" > "$PID_FILE"
    log "ic_monitor.py PID=$IC_PID"

    wait "$IC_PID"
    EXIT_CODE=$?
    log "ic_monitor.py exited with code $EXIT_CODE"

    rm -f "$PID_FILE"

    if [ $EXIT_CODE -eq 0 ]; then
        log "Clean exit — no restart needed"
        break
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))
    log "Crash detected — will restart in 15s (attempt $RESTART_COUNT/$MAX_RESTARTS)"
    sleep 15
done

log "=== IC Monitor Wrapper Stopped ==="
