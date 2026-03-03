#!/bin/bash
# Auto-start NSE Equity strategies at 9:15 AM IST
# ORB_SBIN + VWAP_RELIANCE + EMA_HDFCBANK

LOGDIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/logs"
SCRIPTDIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/scripts"
APIKEY="372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
HOST="http://127.0.0.1:5002"
PYTHON="/opt/homebrew/bin/python3"

mkdir -p "$LOGDIR"

echo "[$(date)] Starting NSE Equity strategies..." | tee -a "$LOGDIR/startup.log"

# Kill any existing equity strategy processes
pkill -f "orb_equity_volume.py" 2>/dev/null
pkill -f "vwap_rsi_equity.py" 2>/dev/null
pkill -f "ema_supertrend_equity.py" 2>/dev/null
sleep 1

# ORB SBIN
nohup env \
  SYMBOL=SBIN EXCHANGE=NSE PRODUCT=MIS QUANTITY=333 \
  OPENALGO_APIKEY="$APIKEY" \
  OPENALGO_HOST="$HOST" \
  "$PYTHON" "$SCRIPTDIR/orb_equity_volume.py" \
  > "$LOGDIR/orb_sbin_live.log" 2>&1 &
SBIN_PID=$!
echo "[$(date)] ORB_SBIN started (PID $SBIN_PID)" | tee -a "$LOGDIR/startup.log"

# VWAP RELIANCE
nohup env \
  SYMBOL=RELIANCE EXCHANGE=NSE PRODUCT=MIS QUANTITY=268 \
  OPENALGO_APIKEY="$APIKEY" \
  OPENALGO_HOST="$HOST" \
  "$PYTHON" "$SCRIPTDIR/vwap_rsi_equity.py" \
  > "$LOGDIR/vwap_reliance_live.log" 2>&1 &
REL_PID=$!
echo "[$(date)] VWAP_RELIANCE started (PID $REL_PID)" | tee -a "$LOGDIR/startup.log"

# EMA HDFCBANK
nohup env \
  SYMBOL=HDFCBANK EXCHANGE=NSE PRODUCT=MIS QUANTITY=696 \
  OPENALGO_APIKEY="$APIKEY" \
  OPENALGO_HOST="$HOST" \
  "$PYTHON" "$SCRIPTDIR/ema_supertrend_equity.py" \
  > "$LOGDIR/ema_hdfcbank_live.log" 2>&1 &
HDFC_PID=$!
echo "[$(date)] EMA_HDFCBANK started (PID $HDFC_PID)" | tee -a "$LOGDIR/startup.log"

echo "[$(date)] Equity strategies running — SBIN=$SBIN_PID, RELIANCE=$REL_PID, HDFCBANK=$HDFC_PID"
