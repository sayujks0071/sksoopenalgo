#!/bin/bash
# Enable the OpenClaw gateway Chat Completions HTTP endpoint so that
# OPENCLAW_USE_GATEWAY=1 ./scripts/openclaw_send_message.sh "..." saves the response.
# Run once; restart the gateway if it does not hot-reload config.

if command -v openclaw &>/dev/null; then
  openclaw config set gateway.http.endpoints.chatCompletions.enabled true
  echo "Done. Restart the OpenClaw gateway if responses still return 405."
else
  echo "openclaw CLI not found. Enable the endpoint manually:"
  echo "  openclaw config set gateway.http.endpoints.chatCompletions.enabled true"
  echo "Or edit ~/.openclaw/openclaw.json and add under gateway:"
  echo '  "http": { "endpoints": { "chatCompletions": { "enabled": true } } }'
  exit 1
fi
