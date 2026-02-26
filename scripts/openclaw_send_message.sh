#!/bin/bash
# Send a message to OpenClaw from the terminal (so you can run from Cursor/IDE).
#
# Modes:
#   openclaw://  - Open the OpenClaw macOS app with a pre-filled message (default).
#   gateway      - POST to OpenClaw gateway HTTP API (no app window). Requires gateway
#                  running on 18789 and OPENCLAW_GATEWAY_TOKEN (or OPENCLAW_AGENT_KEY) set.
#
# Usage:
#   ./scripts/openclaw_send_message.sh "Your message here"
#   OPENCLAW_USE_GATEWAY=1 ./scripts/openclaw_send_message.sh "Your message"
#
# When OPENCLAW_USE_GATEWAY=1, the agent reply is printed and saved to:
#   log/openclaw_response.txt (plain text) and log/openclaw_response.json (raw API).
# Override dir with OPENCLAW_RESPONSE_DIR.
#
# Env (optional):
#   Gateway HTTP auth: OPENCLAW_GATEWAY_TOKEN or OPENCLAW_GATEWAY_PASSWORD (or OPENCLAW_AGENT_KEY if same).
#   Deep link: OPENCLAW_AGENT_KEY.
#   OPENCLAW_USE_GATEWAY=1  - Use gateway HTTP instead of opening app.
#   OPENCLAW_GATEWAY_URL    - Default: http://127.0.0.1:18789
#   Optional: .env.openclaw with OPENCLAW_GATEWAY_TOKEN=... or OPENCLAW_AGENT_KEY=... (gitignore it); script loads it.

set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$PROJECT_ROOT/.env.openclaw"
  set +a
fi

MESSAGE="${1:-Hello from terminal}"
GATEWAY_URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
# Gateway HTTP expects Bearer = gateway token or gateway password (see gateway.auth.mode in OpenClaw config)
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-${OPENCLAW_GATEWAY_PASSWORD:-$OPENCLAW_AGENT_KEY}}"

# Safe encoding via Python (handles quotes and special chars)
ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$MESSAGE")
JSON_PAYLOAD=$(python3 -c "import json,sys; print(json.dumps({'model':'openclaw','messages':[{'role':'user','content':sys.argv[1]}]}))" "$MESSAGE")

if [ -n "$OPENCLAW_USE_GATEWAY" ] && [ "$OPENCLAW_USE_GATEWAY" = "1" ]; then
  if [ -z "$TOKEN" ]; then
    echo "Set OPENCLAW_AGENT_KEY or OPENCLAW_GATEWAY_TOKEN for gateway auth." >&2
    exit 1
  fi
  RESP_DIR="${OPENCLAW_RESPONSE_DIR:-$PROJECT_ROOT/log}"
  mkdir -p "$RESP_DIR"
  RAW_FILE="$RESP_DIR/openclaw_response.json"
  TEXT_FILE="$RESP_DIR/openclaw_response.txt"
  echo "Sending to gateway $GATEWAY_URL..."
  RESP=$(curl -sS -w "\n%{http_code}" "$GATEWAY_URL/v1/chat/completions" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "x-openclaw-agent-id: main" \
    -d "$JSON_PAYLOAD")
  HTTP_CODE=$(echo "$RESP" | tail -n1)
  BODY=$(echo "$RESP" | sed '$d')
  echo "$BODY" > "$RAW_FILE"
  if [ "$HTTP_CODE" = "200" ]; then
    python3 -c "
import json, sys
try:
    d = json.load(open('$RAW_FILE'))
    c = d.get('choices') or []
    if c and c[0].get('message', {}).get('content'):
        text = c[0]['message']['content']
        open('$TEXT_FILE', 'w').write(text)
        print('--- OpenClaw response ---')
        print(text)
        print('---')
        print('Saved to $TEXT_FILE (text) and $RAW_FILE (raw JSON)')
    else:
        open('$TEXT_FILE', 'w').write('(no content in response)')
        print('Saved raw response to $RAW_FILE')
        print('(no choices[0].message.content found)')
except Exception as e:
    open('$TEXT_FILE', 'w').write('Error: ' + str(e))
    print('Saved raw to $RAW_FILE; parse error:', e, file=sys.stderr)
" 2>/dev/null || { echo "$BODY"; echo "Saved raw to $RAW_FILE"; }
  else
    echo "HTTP $HTTP_CODE" > "$TEXT_FILE"
    echo "Gateway returned HTTP $HTTP_CODE. Raw response in $RAW_FILE"
    echo "$BODY" | head -20
  fi
else
  if [ -z "$TOKEN" ]; then
    echo "Set OPENCLAW_AGENT_KEY (or OPENCLAW_GATEWAY_TOKEN) to open app with key." >&2
    echo "Opening app without key (message only)..." >&2
    open "openclaw://agent?message=${ENCODED}"
  else
    open "openclaw://agent?message=${ENCODED}&key=${TOKEN}"
  fi
  echo "Opened OpenClaw app with message."
fi
