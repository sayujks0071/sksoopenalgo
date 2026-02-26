#!/bin/bash
# ── OpenAlgo Weekly Maintenance ───────────────────────────────────────────────
# Runs Saturday 6:00 AM IST — deeper cleanup + trade history archival
# ──────────────────────────────────────────────────────────────────────────────
set +e

LOG="/Users/mac/openalgo/log/maintenance.log"
OPENALGO_DIR="/Users/mac/openalgo"
DB_DIR="$OPENALGO_DIR/db"
TRADE_DIR="$HOME/.openclaw/workspace/memory/trading"
ARCHIVE_DIR="$TRADE_DIR/archive"
TS=$(date "+%Y-%m-%d %H:%M:%S")

log() { echo "[$TS] $1" >> "$LOG"; }

log "=== WEEKLY MAINTENANCE START ==="

# ── 1. FULL VACUUM on all databases ───────────────────────────────────────────
full_vacuum() {
    local db="$1"
    if [ -f "$db" ]; then
        local before=$(du -sh "$db" 2>/dev/null | cut -f1)
        sqlite3 "$db" "VACUUM;" 2>/dev/null
        sqlite3 "$db" "ANALYZE;" 2>/dev/null
        local after=$(du -sh "$db" 2>/dev/null | cut -f1)
        log "VACUUM $(basename "$db"): $before -> $after"
    fi
}

full_vacuum "$DB_DIR/openalgo.db"
full_vacuum "$DB_DIR/health.db"
full_vacuum "$DB_DIR/logs.db"
full_vacuum "$DB_DIR/latency.db"
full_vacuum "$DB_DIR/sandbox.db"

# ── 2. ARCHIVE OLD TRADE HISTORY ──────────────────────────────────────────────
mkdir -p "$ARCHIVE_DIR"
WEEK=$(date "+%Y-W%V")

# Archive trade_history.jsonl entries older than 30 days
if [ -f "$TRADE_DIR/trade_history.jsonl" ]; then
    LINES=$(wc -l < "$TRADE_DIR/trade_history.jsonl")
    if [ "$LINES" -gt 100 ]; then
        # Keep last 100 entries, archive the rest
        head -n -100 "$TRADE_DIR/trade_history.jsonl" >> "$ARCHIVE_DIR/trade_history_$WEEK.jsonl"
        tail -100 "$TRADE_DIR/trade_history.jsonl" > "$TRADE_DIR/trade_history.jsonl.tmp"
        mv "$TRADE_DIR/trade_history.jsonl.tmp" "$TRADE_DIR/trade_history.jsonl"
        log "Archived $(($LINES - 100)) trade history entries to archive/trade_history_$WEEK.jsonl"
    fi
fi

# Archive agent_log.jsonl
if [ -f "$TRADE_DIR/agent_log.jsonl" ]; then
    LINES=$(wc -l < "$TRADE_DIR/agent_log.jsonl")
    if [ "$LINES" -gt 50 ]; then
        head -n -50 "$TRADE_DIR/agent_log.jsonl" >> "$ARCHIVE_DIR/agent_log_$WEEK.jsonl"
        tail -50 "$TRADE_DIR/agent_log.jsonl" > "$TRADE_DIR/agent_log.jsonl.tmp"
        mv "$TRADE_DIR/agent_log.jsonl.tmp" "$TRADE_DIR/agent_log.jsonl"
        log "Archived $(($LINES - 50)) agent log entries"
    fi
fi

# ── 3. PURGE OLD ARCHIVES (keep last 8 weeks) ─────────────────────────────────
find "$ARCHIVE_DIR" -name "*.jsonl" -mtime +56 -delete 2>/dev/null
log "Purged archives older than 8 weeks"

# ── 4. DEEP CACHE CLEANUP ─────────────────────────────────────────────────────
# .mypy_cache, .pytest_cache, .ruff_cache
rm -rf "$OPENALGO_DIR/.mypy_cache" 2>/dev/null
rm -rf "$OPENALGO_DIR/.pytest_cache" 2>/dev/null
rm -rf "$OPENALGO_DIR/.ruff_cache" 2>/dev/null
rm -rf "$OPENALGO_DIR/strategies/.cache" 2>/dev/null
find "$OPENALGO_DIR" -maxdepth 4 -name "__pycache__" \
    -not -path "*/.venv/*" -not -path "*/venv/*" \
    -exec rm -rf {} + 2>/dev/null
log "Deep cache cleanup complete"

# ── 5. COMPRESS OLD LOG FILES ─────────────────────────────────────────────────
find "$OPENALGO_DIR/log" -name "*.log" -mtime +3 -size +10k \
    -not -name "maintenance.log" \
    -exec gzip -q {} \; 2>/dev/null
log "Compressed old log files"

# ── 6. WEEKLY DISK REPORT ─────────────────────────────────────────────────────
TOTAL=$(du -sh "$OPENALGO_DIR" 2>/dev/null | cut -f1)
DB_TOTAL=$(du -sh "$DB_DIR" 2>/dev/null | cut -f1)
TRADE_TOTAL=$(du -sh "$TRADE_DIR" 2>/dev/null | cut -f1)
FREE=$(df -h / 2>/dev/null | tail -1 | awk '{print $4}')
log "WEEKLY REPORT: app=$TOTAL | db=$DB_TOTAL | trading=$TRADE_TOTAL | disk_free=$FREE"

log "=== WEEKLY MAINTENANCE COMPLETE ==="
