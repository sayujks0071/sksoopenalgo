#!/bin/bash
# One-time: add OpenClaw cron job to run OpenAlgo Dhan login at 8 AM IST on trading days.
# Run from a terminal where `openclaw` CLI is configured (gateway URL + auth).
#
# Usage: ./scripts/openclaw_cron_add_dhan_login.sh
# Optional: OPENALGO_PROJECT_DIR=/path/to/openalgo ./scripts/openclaw_cron_add_dhan_login.sh

set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR="${OPENALGO_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if ! command -v openclaw &>/dev/null; then
  echo "openclaw CLI not found. Install and configure OpenClaw first." >&2
  exit 1
fi

echo "Adding OpenClaw cron job: OpenAlgo Dhan login at 8 AM IST (Mon–Fri)"
echo "Project dir: $PROJECT_DIR"
openclaw cron add \
  --name "OpenAlgo Dhan login" \
  --cron "0 8 * * 1-5" \
  --tz "Asia/Kolkata" \
  --session isolated \
  --message "Run the OpenAlgo Dhan trading login script. Execute this command: cd $PROJECT_DIR && ./scripts/cron_dhan_trading_login.sh" \
  --no-deliver

echo "Done. List jobs: openclaw cron list"
