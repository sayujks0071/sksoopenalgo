#!/bin/bash
# Emergency / EOD square-off — kills all strategy processes + calls closeall
APIKEY="372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
HOST="http://127.0.0.1:5002"

echo "[$(date)] Square-off initiated"

# Kill all strategy processes
pkill -f "orb_equity_volume.py" 2>/dev/null && echo "  Stopped ORB_SBIN"
pkill -f "vwap_rsi_equity.py" 2>/dev/null && echo "  Stopped VWAP_RELIANCE"
pkill -f "ema_supertrend_equity.py" 2>/dev/null && echo "  Stopped EMA_HDFCBANK"
pkill -f "mcx_commodity_momentum_strategy.py" 2>/dev/null && echo "  Stopped MCX_SILVER"
pkill -f "mcx_gold_momentum_strategy.py" 2>/dev/null && echo "  Stopped MCX_GOLD"

sleep 1

# Call closeall on OpenAlgo
echo "  Calling closeall..."
curl -s -X POST "$HOST/api/v1/closeall" \
  -H "Content-Type: application/json" \
  -d "{\"apikey\":\"$APIKEY\"}" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print('  CloseAll response:', d.get('status','?'), d.get('message',''))
except: print('  CloseAll: non-JSON response')
" 2>/dev/null

echo "[$(date)] Square-off complete"
