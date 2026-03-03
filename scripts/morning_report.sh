#!/bin/bash
# Morning pre-market report — runs at 8:45 AM IST
# Checks: strategy health, open positions, fund balance, logs

LOGDIR="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/logs"
APIKEY="372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
HOST="http://127.0.0.1:5002"

echo "=== MORNING REPORT $(date '+%Y-%m-%d %H:%M IST') ==="
echo ""

# Funds check
echo "[FUNDS]"
curl -s -X POST "$HOST/api/v1/funds" \
  -H "Content-Type: application/json" \
  -d "{\"apikey\":\"$APIKEY\"}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('status')=='success':
    f=d['data']
    print(f'  Available Cash : ₹{float(f.get(\"availabelBalance\",0)):,.2f}')
    print(f'  M2M Realized   : ₹{float(f.get(\"m2mRealised\",0)):,.2f}')
    print(f'  Utilised       : ₹{float(f.get(\"utilisedAmount\",0)):,.2f}')
else:
    print('  ERROR:', d)
" 2>/dev/null || echo "  Funds API unavailable"

echo ""
echo "[STRATEGY LOGS — last 3 lines each]"
for log in "$LOGDIR"/*.log; do
  name=$(basename "$log" .log)
  echo "  -- $name --"
  tail -3 "$log" 2>/dev/null | sed 's/^/    /'
done

echo ""
echo "[OPEN POSITIONS]"
curl -s -X POST "$HOST/api/v1/openposition" \
  -H "Content-Type: application/json" \
  -d "{\"apikey\":\"$APIKEY\",\"strategy\":\"all\",\"exchange\":\"all\",\"symbol\":\"all\",\"product\":\"all\",\"positiontype\":\"all\"}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if isinstance(d,list) and d:
    for p in d:
        print(f'  {p.get(\"tradingsymbol\",\"?\")} qty={p.get(\"quantity\",0)} avg={p.get(\"averageprice\",0):.2f} pnl=₹{p.get(\"pnl\",0):,.2f}')
elif isinstance(d,dict) and d.get('status')=='success':
    for p in d.get('data',[]):
        print(f'  {p.get(\"tradingsymbol\",\"?\")} qty={p.get(\"quantity\",0)} avg={p.get(\"averageprice\",0):.2f}')
else:
    print('  No open positions')
" 2>/dev/null || echo "  Positions API unavailable"

echo ""
echo "=== END ==="
