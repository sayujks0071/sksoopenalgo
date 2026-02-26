#!/bin/bash
# ── OpenAlgo Daily Maintenance ────────────────────────────────────────────────
# Runs at 4:00 AM IST (after market close, before next session)
# Rotates logs, optimizes DBs, health checks, cleans temp files
# ──────────────────────────────────────────────────────────────────────────────
set +e  # don't abort on individual failures

LOG="/Users/mac/openalgo/log/maintenance.log"
OPENALGO_DIR="/Users/mac/openalgo"
DB_DIR="$OPENALGO_DIR/db"
TS=$(date "+%Y-%m-%d %H:%M:%S")

log() { echo "[$TS] $1" >> "$LOG"; }

log "=== DAILY MAINTENANCE START ==="

# ── 1. LOG ROTATION (keep last 500 lines of each log) ─────────────────────────
rotate_log() {
    local f="$1"
    local keep="${2:-500}"
    if [ -f "$f" ] && [ "$(wc -l < "$f" 2>/dev/null)" -gt "$keep" ]; then
        tail -"$keep" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        log "Rotated $(basename "$f") to $keep lines"
    fi
}

rotate_log "$OPENALGO_DIR/app.log" 500
rotate_log "$OPENALGO_DIR/ic_monitor.log" 1000
rotate_log "$OPENALGO_DIR/webhook_receiver.log" 500
rotate_log "$OPENALGO_DIR/claude_remote.log" 200
rotate_log "$OPENALGO_DIR/wave1_execution.log" 200
rotate_log "$OPENALGO_DIR/log/cron_dhan_login.log" 300
rotate_log "$OPENALGO_DIR/log/app_live.log" 500

# Delete dated logs older than 7 days
find "$OPENALGO_DIR/log" -name "openalgo_*.log" -mtime +7 -delete 2>/dev/null
log "Cleaned dated logs older than 7 days"

# ── 2. SQLITE OPTIMIZATION (incremental VACUUM + ANALYZE) ─────────────────────
optimize_db() {
    local db="$1"
    if [ -f "$db" ]; then
        # Set WAL mode if not already (faster concurrent reads)
        sqlite3 "$db" "PRAGMA journal_mode=WAL;" 2>/dev/null
        # Run ANALYZE for query planner
        sqlite3 "$db" "ANALYZE;" 2>/dev/null
        # Incremental vacuum (reclaims space without full rewrite)
        sqlite3 "$db" "PRAGMA incremental_vacuum(100);" 2>/dev/null
        local sz=$(du -sh "$db" 2>/dev/null | cut -f1)
        log "Optimized $(basename "$db") ($sz)"
    fi
}

optimize_db "$DB_DIR/openalgo.db"
optimize_db "$DB_DIR/health.db"
optimize_db "$DB_DIR/logs.db"
optimize_db "$DB_DIR/latency.db"
optimize_db "$DB_DIR/sandbox.db"

# ── 3. CLEAN __pycache__ (root level only, not venvs) ──────────────────────────
find "$OPENALGO_DIR" -maxdepth 3 -name "__pycache__" \
    -not -path "*/.venv/*" -not -path "*/venv/*" \
    -exec rm -rf {} + 2>/dev/null
log "Cleaned __pycache__ directories"

# ── 4. CLEAN .DS_Store ─────────────────────────────────────────────────────────
find "$OPENALGO_DIR" -maxdepth 5 -name ".DS_Store" -delete 2>/dev/null

# ── 5. HEALTH CHECK — OpenAlgo port 5002 ──────────────────────────────────────
if curl -sf -o /dev/null -m 3 http://127.0.0.1:5002/; then
    log "HEALTH OK: OpenAlgo port 5002 responsive"
else
    log "HEALTH WARN: OpenAlgo port 5002 NOT responding"
fi

# ── 6. PID FILE CLEANUP ───────────────────────────────────────────────────────
# Remove stale PID files where process is dead
for pid_file in /tmp/ic_monitor.pid /tmp/webhook_receiver.pid; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
            log "Cleaned stale PID file: $pid_file (PID $pid dead)"
        fi
    fi
done

# ── 7. DISK USAGE REPORT ──────────────────────────────────────────────────────
TOTAL=$(du -sh "$OPENALGO_DIR" 2>/dev/null | cut -f1)
DB_TOTAL=$(du -sh "$DB_DIR" 2>/dev/null | cut -f1)
log "Disk: total=$TOTAL | databases=$DB_TOTAL"

log "=== DAILY MAINTENANCE COMPLETE ==="
