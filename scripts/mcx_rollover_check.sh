#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# mcx_rollover_check.sh
# Check MCX futures contract expiry and generate rollover commands.
# Run weekly (every Thursday) via openclaw cron.
# Sends WhatsApp alert if any contract expires within 7 days.
#
# Current MCX contracts (April 2026):
#   Silver Mini: SILVERM30APR26FUT (expiry: ~30 Apr 2026)
#   Gold Mini:   GOLDM02APR26FUT   (expiry: ~02 Apr 2026)
#
# MCX naming convention:
#   SILVERM{DD}{MMM}{YY}FUT → Silver Mini, DD=expiry day, MMM=month, YY=year
#   GOLDM{DD}{MMM}{YY}FUT  → Gold Mini
#   GOLD{DD}{MMM}{YY}FUT   → Gold Standard
#
# Usage:
#   ./scripts/mcx_rollover_check.sh    # manual check
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TODAY=$(date +"%Y-%m-%d")

# Load gateway credentials
if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
  set -a; . "$PROJECT_ROOT/.env.openclaw"; set +a
fi
if [ -z "$OPENCLAW_GATEWAY_TOKEN" ] && [ -f "$HOME/.openclaw/.env" ]; then
  OPENCLAW_GATEWAY_TOKEN=$(grep '^OPENCLAW_GATEWAY_TOKEN=' "$HOME/.openclaw/.env" 2>/dev/null | cut -d= -f2-)
fi

GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-30cb0d5aedbb9698659253de29db5a064eb4b41d823b7306}"

PROMPT="MCX contract rollover check. Today: $TODAY.

Current active MCX contracts:
- Silver Mini: SILVERM30APR26FUT (last trading day ~30 Apr 2026)
- Gold Mini:   GOLDM02APR26FUT   (last trading day ~02 Apr 2026)

Please:
1. Calculate days remaining until each contract's expiry from today ($TODAY)
2. For any contract expiring within 7 days:
   a. Determine the next month contract symbol using MCX naming convention
   b. Output the exact new symbol (e.g., SILVERM28MAY26FUT)
   c. Output the full deployment command with the new symbol
   d. Call send_whatsapp_alert with: 'MCX ROLLOVER NEEDED: [old symbol] expires in [N] days. New: [new symbol]. Run: [key part of deployment command]'
3. If no rollover needed: respond 'MCX contracts OK — [days] days to nearest expiry.'

MCX naming rules:
- Month abbreviations: JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC
- Silver Mini lot = 30 kg. Gold Mini lot = 100g.
- Deployment env vars:
  OPENALGO_APIKEY=372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb
  OPENALGO_HOST=http://127.0.0.1:5002

Deployment command template:
nohup env OPENALGO_APIKEY=... OPENALGO_HOST=http://127.0.0.1:5002 \\
  python3 /Users/mac/sksoopenalgo/openalgo/openalgo/strategies/scripts/[script].py \\
  --symbol [NEW_SYMBOL] --quantity 1 --exchange MCX --interval 15m \\
  --product NRML --host http://127.0.0.1:5002 > logs/[strategy]_live.log 2>&1 &"

echo "📋 MCX rollover check for $TODAY"

RESP=$(curl -sS -w "\n%{http_code}" "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-agent-id: main" \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"model":"openclaw","messages":[{"role":"user","content":sys.argv[1]}]}))' "$PROMPT")" 2>&1)

HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
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
