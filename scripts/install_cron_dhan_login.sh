#!/bin/bash
# Install cron job for Dhan trading login (OpenAlgo).
# Run once from repo root: ./scripts/install_cron_dhan_login.sh

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
CRON_SCRIPT="$SCRIPT_DIR/cron_dhan_trading_login.sh"

# Schedule: 8:45 AM IST weekdays (adjust for your TZ; 03:15 UTC = 08:45 IST)
# For macOS/Linux with system TZ = Asia/Kolkata use:
# 45 8 * * 1-5
CRON_SCHEDULE="${DHAN_LOGIN_CRON_SCHEDULE:-45 8 * * 1-5}"
CRON_LINE="$CRON_SCHEDULE OPENALGO_PROJECT_DIR=$PROJECT_DIR $CRON_SCRIPT"

if [ ! -x "$CRON_SCRIPT" ]; then
  chmod +x "$CRON_SCRIPT"
fi

echo "Installing cron: Dhan trading login (OpenAlgo)"
echo "  Schedule: $CRON_SCHEDULE (default 8:45 AM Mon–Fri)"
echo "  Script:   $CRON_SCRIPT"
echo ""

# Avoid duplicate entries
crontab -l 2>/dev/null | grep -v "cron_dhan_trading_login.sh" | grep -v "dhan_trading_login.py" > /tmp/cron_dhan_backup
echo "$CRON_LINE" >> /tmp/cron_dhan_backup
crontab /tmp/cron_dhan_backup
rm -f /tmp/cron_dhan_backup

echo "Cron installed. Current crontab:"
crontab -l | grep -E "dhan_trading_login|cron_dhan"
echo ""
echo "Logs: \$OPENALGO_CRON_LOG or $PROJECT_DIR/log/cron_dhan_login.log"
echo "To change schedule: DHAN_LOGIN_CRON_SCHEDULE='45 8 * * 1-5' ./scripts/install_cron_dhan_login.sh"
