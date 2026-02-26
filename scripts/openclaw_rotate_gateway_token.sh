#!/bin/bash
# Rotate/reissue the OpenClaw gateway token and keep config, plist, and .env.openclaw in sync.
# Run from repo root. Requires: openclaw CLI, Python 3, launchd (macOS).
# After running: set the printed token in the OpenClaw app (Settings → Agent key / Gateway token).

set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
JSON="$HOME/.openclaw/openclaw.json"
PLIST_NAMES="ai.openclaw.gateway.plist com.openclaw.gateway.plist"

if [ ! -f "$JSON" ]; then
  echo "Config not found: $JSON. Run openclaw configure first."
  exit 1
fi

PLIST=""
for name in $PLIST_NAMES; do
  if [ -f "$HOME/Library/LaunchAgents/$name" ]; then
    PLIST="$HOME/Library/LaunchAgents/$name"
    break
  fi
done
if [ -z "$PLIST" ]; then
  echo "No OpenClaw gateway plist found in ~/Library/LaunchAgents/"
  exit 1
fi

NEW_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
echo "New gateway token (set this in the OpenClaw app if needed): $NEW_TOKEN"

openclaw config set gateway.auth.token "$NEW_TOKEN"
openclaw config set gateway.auth.password "$NEW_TOKEN"

python3 -c "
import plistlib
path = \"$PLIST\"
with open(path, 'rb') as f:
    p = plistlib.load(f)
env = p.get('EnvironmentVariables') or {}
env['OPENCLAW_GATEWAY_TOKEN'] = '''$NEW_TOKEN'''
p['EnvironmentVariables'] = env
with open(path, 'wb') as f:
    plistlib.dump(p, f)
print('Plist updated')
"

ENV_FILE="$PROJECT_ROOT/.env.openclaw"
if [ -f "$ENV_FILE" ]; then
  if grep -q '^OPENCLAW_GATEWAY_TOKEN=' "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^OPENCLAW_GATEWAY_TOKEN=.*|OPENCLAW_GATEWAY_TOKEN=$NEW_TOKEN|" "$ENV_FILE"
  else
    echo "OPENCLAW_GATEWAY_TOKEN=$NEW_TOKEN" >> "$ENV_FILE"
  fi
  echo "Updated $ENV_FILE"
else
  echo "OPENCLAW_GATEWAY_TOKEN=$NEW_TOKEN" > "$ENV_FILE"
  echo "Created $ENV_FILE"
fi

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Gateway restarted."

"$SCRIPT_DIR/openclaw_check_gateway_token_sync.sh" && echo "Sync OK. Use OPENCLAW_USE_GATEWAY=1 ./scripts/openclaw_send_message.sh to test."
