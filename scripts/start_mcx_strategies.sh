#!/bin/bash
# Auto-start MCX strategies at 9:00 AM IST
# MCX_SILVER + MCX_GOLD (April 2026 contracts)

LOGDIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/logs"
SCRIPTDIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/scripts"
APIKEY="372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
HOST="http://127.0.0.1:5002"
PYTHON="/opt/homebrew/bin/python3"

mkdir -p "$LOGDIR"

echo "[$(date)] Starting MCX strategies..." | tee -a "$LOGDIR/startup.log"

# Kill any existing MCX strategy processes
pkill -f "mcx_commodity_momentum_strategy.py" 2>/dev/null
pkill -f "mcx_gold_momentum_strategy.py" 2>/dev/null
sleep 1

# MCX SILVER
nohup env \
  OPENALGO_APIKEY="$APIKEY" \
  OPENALGO_HOST="$HOST" \
  "$PYTHON" "$SCRIPTDIR/mcx_silver_momentum_v2.py" \
  --symbol SILVERM30APR26FUT --quantity 1 --exchange MCX --interval 15m \
  --product NRML --host "$HOST" \
  > "$LOGDIR/mcx_silver_live.log" 2>&1 &
SILVER_PID=$!
echo "[$(date)] MCX_SILVER started (PID $SILVER_PID)" | tee -a "$LOGDIR/startup.log"

# MCX GOLD
nohup env \
  OPENALGO_APIKEY="$APIKEY" \
  OPENALGO_HOST="$HOST" \
  "$PYTHON" "$SCRIPTDIR/mcx_gold_momentum_v2.py" \
  --symbol GOLDM02APR26FUT --quantity 1 --exchange MCX --interval 15m \
  --product NRML --host "$HOST" \
  > "$LOGDIR/mcx_gold_live.log" 2>&1 &
GOLD_PID=$!
echo "[$(date)] MCX_GOLD started (PID $GOLD_PID)" | tee -a "$LOGDIR/startup.log"

echo "[$(date)] MCX strategies running — Silver PID=$SILVER_PID, Gold PID=$GOLD_PID"
