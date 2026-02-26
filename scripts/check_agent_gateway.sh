#!/usr/bin/env bash
set -euo pipefail
for i in {1..15}; do
  if curl -fsS http://127.0.0.1:9101/v1/health | sed -n '1,3p'; then
    exit 0
  fi
  sleep 0.3
done
echo "agent gateway health check failed"
exit 1
