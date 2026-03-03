#!/bin/bash
# Start NIFTY + SENSEX IC strategies for today
# Run at 9:30 AM IST on Wednesdays (entry day for both weekly cycles)

STRAT_DIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies"
APIKEY="372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
HOST="http://127.0.0.1:5002"
PYTHON="/opt/homebrew/bin/python3"

mkdir -p "$STRAT_DIR/logs" "$STRAT_DIR/state"

echo "[$(date)] Starting NIFTY + SENSEX IC strategies"

# NIFTY Weekly IC (10-MAR-26, 6 DTE, sd=1.6, vix≤20)
nohup env OPENALGO_APIKEY="$APIKEY" OPENALGO_HOST="$HOST" \
  $PYTHON "$STRAT_DIR/scripts/nifty_sensex_ic_live.py" \
  --index NIFTY --expiry 10MAR26 --mode weekly --lots 1 --auto \
  > "$STRAT_DIR/logs/nifty_weekly_ic.log" 2>&1 &
echo "NIFTY Weekly IC started (PID $!)"

sleep 3

# SENSEX Weekly IC (12-MAR-26, 8 DTE, sd=1.6, vix≤22)
nohup env OPENALGO_APIKEY="$APIKEY" OPENALGO_HOST="$HOST" \
  $PYTHON "$STRAT_DIR/scripts/nifty_sensex_ic_live.py" \
  --index SENSEX --expiry 12MAR26 --mode weekly --lots 1 --auto \
  > "$STRAT_DIR/logs/sensex_weekly_ic.log" 2>&1 &
echo "SENSEX Weekly IC started (PID $!)"

echo "[$(date)] All option strategies launched"
echo "Logs:"
echo "  tail -f $STRAT_DIR/logs/nifty_weekly_ic.log"
echo "  tail -f $STRAT_DIR/logs/sensex_weekly_ic.log"
