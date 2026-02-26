#!/bin/bash
# Cron wrapper: ensure Dhan trading login for OpenAlgo (validate + optional sync from .env).
# Run this before market open (e.g. 8:45 AM IST weekdays).

PROJECT_DIR="${OPENALGO_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR" || exit 1

LOG_FILE="${OPENALGO_CRON_LOG:-$PROJECT_DIR/log/cron_dhan_login.log}"
mkdir -p "$(dirname "$LOG_FILE")"
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Load .env so Python script sees OPENALGO_USER, DHAN_ACCESS_TOKEN, etc.
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$PROJECT_DIR/.env"
  set +a
fi

echo "==================================================" >> "$LOG_FILE"
echo "Dhan login check at $(date)" >> "$LOG_FILE"
python3 "$PROJECT_DIR/scripts/dhan_trading_login.py" >> "$LOG_FILE" 2>&1
echo "Exit $? at $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
