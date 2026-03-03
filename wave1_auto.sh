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
  log "🟡 CAUTION — proceeding with 20 lots (~60% position, monitoring closely)"
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

log "✅ Wave 1 COMPLETE — verifying positions..."

# 1.10: Wait for fill propagation, verify positions exist
sleep 5
POS_COUNT=$(python3 -c "
import requests, json
from ic_config import OPENALGO_KEY, OPENALGO_URL
r = requests.post(f'{OPENALGO_URL}/positionbook', json={'apikey': OPENALGO_KEY}, timeout=10)
data = r.json().get('data', []) or []
count = sum(1 for p in data if abs(int(p.get('quantity', 0))) > 0
            and ('CE' in p.get('symbol','') or 'PE' in p.get('symbol','')))
print(count)
" 2>/dev/null || echo "0")
log "Open option positions found: $POS_COUNT"

if [ "$POS_COUNT" -lt 2 ]; then
    log "⚠️  <2 positions after 5s — waiting 10s more for propagation..."
    sleep 10
    POS_COUNT=$(python3 -c "
import requests, json
from ic_config import OPENALGO_KEY, OPENALGO_URL
r = requests.post(f'{OPENALGO_URL}/positionbook', json={'apikey': OPENALGO_KEY}, timeout=10)
data = r.json().get('data', []) or []
count = sum(1 for p in data if abs(int(p.get('quantity', 0))) > 0
            and ('CE' in p.get('symbol','') or 'PE' in p.get('symbol','')))
print(count)
" 2>/dev/null || echo "0")
    log "Open option positions after retry: $POS_COUNT"
    if [ "$POS_COUNT" -lt 2 ]; then
        log "❌ Still <2 positions. Check positions manually."
    fi
fi

# ic_monitor is managed by OpenAlgo's Python Strategy system (ic_nifty_monitor).
# It auto-starts at 9:20 AM via the strategy scheduler and will detect these
# positions on its next positionbook poll. No action needed here.
log "✅ Wave 1 done. ic_monitor running via OpenAlgo strategy host (ic_nifty_monitor)."
