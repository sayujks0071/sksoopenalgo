#!/bin/bash
# Auto Wave1 — scheduled for 9:20 AM IST
# Lots and expiry auto-computed via ic_config + ic_order_executor.py
LOG="/Users/mac/openalgo/wave1_execution.log"

log() { echo "[$(date '+%H:%M:%S IST')] $*" | tee -a "$LOG"; }

# ── Wait until 9:20 AM IST ──────────────────────────────────────────────────
SECS=$(python3 -c "
import pytz, datetime
ist = pytz.timezone('Asia/Kolkata')
now = datetime.datetime.now(ist)
target = now.replace(hour=9, minute=20, second=0, microsecond=0)
if target < now: target = target  # already past — start immediately
print(max(0, int((target - now).total_seconds())))
")
log "=== IC Wave 1 Scheduler started — waiting ${SECS}s until 09:20 IST ==="
sleep "$SECS"

# ── Pre-entry gate ───────────────────────────────────────────────────────────
log "Running pre-entry gate check..."
python3 /Users/mac/openalgo/ic_pre_entry.py >> "$LOG" 2>&1
STATUS=$?
if [ $STATUS -eq 2 ]; then
  log "🔴 SKIP — gate says DO NOT TRADE today. Aborting."
  exit 0
elif [ $STATUS -eq 1 ]; then
  log "🟡 CAUTION — proceeding with 12 lots (monitoring closely)"
fi

# ── ORDERS: delegate to ic_order_executor.py (atomic + fill-verified) ──────
log "Fetching expiry from ic_config..."
EXPIRY=$(cd /Users/mac/openalgo && python3 -c "from ic_config import get_next_expiry; print(get_next_expiry())" 2>/dev/null || echo "")
if [ -z "$EXPIRY" ]; then
  log "❌ Could not get expiry from ic_config. Aborting."
  exit 1
fi
log "Expiry: $EXPIRY — placing IC Wave 1 via ic_order_executor.py..."

cd /Users/mac/openalgo
EXEC_OUT=$(python3 ic_order_executor.py --wave 1 --expiry "$EXPIRY" 2>&1)
EXEC_EXIT=$?
log "Executor: $EXEC_OUT"

if [ $EXEC_EXIT -ne 0 ]; then
    log "❌ Wave 1 FAILED — fill verification failed. Check positions manually."
    python3 -c "
import requests
requests.post('https://sayujks20417.app.n8n.cloud/webhook/ic-trading-alert',
    json={'event':'WAVE1_FAILED','reason':'fill unconfirmed'}, timeout=4)" 2>/dev/null || true
    exit 1
fi

log "✅ Wave 1 COMPLETE — starting ic_monitor.py..."
pkill -f ic_monitor.py 2>/dev/null; sleep 1
nohup /opt/homebrew/bin/python3 /Users/mac/openalgo/ic_monitor.py \
    >> /Users/mac/openalgo/ic_monitor.log 2>&1 &
log "ic_monitor.py started PID=$!"
