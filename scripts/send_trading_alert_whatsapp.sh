#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# send_trading_alert_whatsapp.sh
# Send a trading alert directly to WhatsApp via the OpenClaw gateway.
#
# Usage:
#   ./scripts/send_trading_alert_whatsapp.sh "SBIN SL hit at ₹820"
#   ./scripts/send_trading_alert_whatsapp.sh "EOD: SBIN +₹3,200 | RELIANCE +₹1,800 | NET +₹5,000"
#
# Called from:
#   - trading_risk_check.sh (intraday watchdog)
#   - cron jobs (morning brief, EOD review)
#   - Manually from terminal for urgent alerts
#
# Env (loaded from .env.openclaw or ~/.openclaw/.env):
#   OPENCLAW_GATEWAY_URL    — default: http://127.0.0.1:18789
#   OPENCLAW_GATEWAY_TOKEN  — required (gateway auth token)
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

# Load tokens from .env.openclaw (project-level, gitignored)
if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$PROJECT_ROOT/.env.openclaw"
  set +a
fi

# Fallback to ~/.openclaw/.env
if [ -z "$OPENCLAW_GATEWAY_TOKEN" ] && [ -f "$HOME/.openclaw/.env" ]; then
  OPENCLAW_GATEWAY_TOKEN=$(grep '^OPENCLAW_GATEWAY_TOKEN=' "$HOME/.openclaw/.env" 2>/dev/null | cut -d= -f2-)
fi

GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-30cb0d5aedbb9698659253de29db5a064eb4b41d823b7306}"
MESSAGE="${1:-🤖 Trading alert from OpenAlgo (no message provided)}"

if [ -z "$TOKEN" ]; then
  echo "❌ Error: OPENCLAW_GATEWAY_TOKEN not set. Check ~/.openclaw/.env or .env.openclaw" >&2
  exit 1
fi

# Build JSON payload (escape message for JSON)
JSON_PAYLOAD=$(python3 -c "
import json, sys
msg = sys.argv[1]
payload = {
    'model': 'openclaw',
    'messages': [{'role': 'user', 'content': '[TRADING ALERT — route to WhatsApp]: ' + msg}]
}
print(json.dumps(payload))
" "$MESSAGE")

echo "📱 Sending WhatsApp alert via OpenClaw gateway..."
echo "   Message: $MESSAGE"

RESP=$(curl -sS -w "\n%{http_code}" "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -H "x-openclaw-channel: whatsapp" \
  -d "$JSON_PAYLOAD" 2>&1)

HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
  echo "✅ Alert sent (HTTP 200)"
else
  echo "⚠️  Gateway returned HTTP $HTTP_CODE" >&2
  echo "$BODY" | head -5 >&2
fi
