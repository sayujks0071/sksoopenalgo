#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# trading_risk_check.sh
# Intraday portfolio risk watchdog — runs every 30 minutes during market hours.
# Sends a gateway request to the OpenClaw agent which checks positions and
# sends a WhatsApp alert if any risk threshold is breached.
#
# Risk thresholds:
#   - Unrealised loss > 1.5% of allocated capital per strategy → WhatsApp alert
#   - Total portfolio loss > ₹29,000 → critical WhatsApp alert
#   - Strategy process died unexpectedly → WhatsApp alert
#
# Capital allocation per strategy:
#   ORB_SBIN: ₹200,000 | VWAP_RELIANCE: ₹150,000 | EMA_HDFCBANK: ₹150,000
#   MCX strategies: per-lot exposure
#
# Usage:
#   ./scripts/trading_risk_check.sh          # manual run
#
# Cron usage (added via openclaw cron):
#   Runs every 30 min from 09:15–15:00 IST via openclaw cron
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
NOW=$(date +"%H:%M IST, %Y-%m-%d")

# Load gateway credentials
if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
  set -a; . "$PROJECT_ROOT/.env.openclaw"; set +a
fi
if [ -z "$OPENCLAW_GATEWAY_TOKEN" ] && [ -f "$HOME/.openclaw/.env" ]; then
  OPENCLAW_GATEWAY_TOKEN=$(grep '^OPENCLAW_GATEWAY_TOKEN=' "$HOME/.openclaw/.env" 2>/dev/null | cut -d= -f2-)
fi

GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-30cb0d5aedbb9698659253de29db5a064eb4b41d823b7306}"

PROMPT="Intraday risk check at $NOW.

Capital allocations:
- ORB_SBIN: ₹2,00,000 (1.5% SL = ₹3,000)
- VWAP_RELIANCE: ₹1,50,000 (1.5% SL = ₹2,250)
- EMA_HDFCBANK: ₹1,50,000 (1.5% SL = ₹2,250)
- MCX_SILVER + MCX_GOLD: per-lot exposure

Please:
1. Call get_live_positions — check unrealised P&L per position
2. Call check_strategy_processes — confirm all 5 strategies are running
3. For each position with unrealised loss > 1.5% of capital allocation:
   - Call send_whatsapp_alert with: symbol, loss amount, recommendation
4. If any strategy process is NOT running (unexpected stop):
   - Call send_whatsapp_alert with: 'ALERT: [strategy] process died. Restart needed.'
5. If total unrealised loss > ₹29,000:
   - Call send_whatsapp_alert with: 'CRITICAL: Daily loss limit breached. Consider emergency square-off.'
6. If everything is within limits, just respond 'All clear at [time].' (no WhatsApp needed)

Be concise. This runs every 30 minutes automatically."

echo "🔍 Risk check at $NOW"

RESP=$(curl -sS -w "\n%{http_code}" "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"model":"openclaw","messages":[{"role":"user","content":sys.argv[1]}]}))' "$PROMPT")" 2>&1)

HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
  # Extract and print agent response
  python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    c = d.get('choices', [])
    if c:
        print(c[0].get('message', {}).get('content', '(no content)'))
except Exception as e:
    print('Parse error:', e)
" <<< "$BODY"
else
  echo "⚠️  Gateway returned HTTP $HTTP_CODE" >&2
fi
