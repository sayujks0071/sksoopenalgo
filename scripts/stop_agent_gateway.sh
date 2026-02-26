#!/usr/bin/env bash
set -euo pipefail
PID_FILE="/Users/mac/openalgo/log/agent_gateway.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "not running"
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID" || true
  sleep 1
  kill -9 "$PID" 2>/dev/null || true
fi
rm -f "$PID_FILE"
echo "stopped"
