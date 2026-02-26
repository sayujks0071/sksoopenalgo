#!/bin/bash
# Check if OpenClaw gateway auth token in openclaw.json matches the token
# in the launchd plist (macOS). Mismatch causes "device token mismatch" / 401.
# Does not print the actual tokens.

set -e
JSON="$HOME/.openclaw/openclaw.json"
PLIST_NAMES="ai.openclaw.gateway.plist com.openclaw.gateway.plist"

if [ ! -f "$JSON" ]; then
  echo "Config not found: $JSON"
  exit 1
fi

# gateway.auth.token from JSON (safe: no token printed)
JSON_TOKEN=$(python3 -c "
import json
try:
    with open('$JSON') as f:
        c = json.load(f)
    t = c.get('gateway', {}).get('auth', {}).get('token') or ''
    print(t)
except Exception as e:
    print('')
" 2>/dev/null)

PLIST=""
for name in $PLIST_NAMES; do
  if [ -f "$HOME/Library/LaunchAgents/$name" ]; then
    PLIST="$HOME/Library/LaunchAgents/$name"
    break
  fi
done

if [ -z "$PLIST" ]; then
  echo "No OpenClaw gateway plist found in ~/Library/LaunchAgents/"
  echo "Token in config: ${JSON_TOKEN:+set (length ${#JSON_TOKEN})}"
  exit 1
fi

# Plist: EnvironmentVariables -> OPENCLAW_GATEWAY_TOKEN (XML or plist)
PLIST_TOKEN=$(python3 -c "
import plistlib, sys
try:
    with open('$PLIST', 'rb') as f:
        p = plistlib.load(f)
    env = p.get('EnvironmentVariables') or {}
    print((env.get('OPENCLAW_GATEWAY_TOKEN') or '').strip())
except Exception:
    print('')
" 2>/dev/null)

if [ "$JSON_TOKEN" = "$PLIST_TOKEN" ]; then
  echo "Tokens match (config and launchd plist)."
else
  echo "Tokens DON'T match — device token mismatch."
  echo "Update OPENCLAW_GATEWAY_TOKEN in: $PLIST"
  echo "to the value of gateway.auth.token in: $JSON"
  echo "Then: launchctl unload $PLIST && launchctl load $PLIST"
  exit 1
fi
