#!/usr/bin/env bash
set -euo pipefail

HOME_DIR="${HOME:-/Users/mac}"
LAUNCH_AGENTS_DIR="$HOME_DIR/Library/LaunchAgents"
OPENALGO_ROOT="/Users/mac/openalgo"
OPENALGO_APP_DIR="$OPENALGO_ROOT/openalgo"
STRATEGY_DIR="$OPENALGO_ROOT/strategies"
PYTHON_BIN="$OPENALGO_APP_DIR/.venv/bin/python"
UID_NUM="$(id -u)"
ACTIVE_DOMAIN=""

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$OPENALGO_APP_DIR/logs"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python binary not found: $PYTHON_BIN"
  exit 1
fi

write_plist() {
  local label="$1"
  local plist_path="$2"
  local cwd="$3"
  local stdout_log="$4"
  local stderr_log="$5"
  shift 5
  local args=("$@")

  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0">'
    echo '<dict>'
    echo '  <key>Label</key>'
    echo "  <string>$label</string>"
    echo '  <key>ProgramArguments</key>'
    echo '  <array>'
    for a in "${args[@]}"; do
      echo "    <string>$a</string>"
    done
    echo '  </array>'
    echo '  <key>WorkingDirectory</key>'
    echo "  <string>$cwd</string>"
    echo '  <key>RunAtLoad</key>'
    echo '  <true/>'
    echo '  <key>KeepAlive</key>'
    echo '  <true/>'
    echo '  <key>ThrottleInterval</key>'
    echo '  <integer>10</integer>'
    echo '  <key>EnvironmentVariables</key>'
    echo '  <dict>'
    echo '    <key>PYTHONUNBUFFERED</key>'
    echo '    <string>1</string>'
    echo '    <key>PATH</key>'
    echo '    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>'
    echo '  </dict>'
    echo '  <key>StandardOutPath</key>'
    echo "  <string>$stdout_log</string>"
    echo '  <key>StandardErrorPath</key>'
    echo "  <string>$stderr_log</string>"
    echo '</dict>'
    echo '</plist>'
  } > "$plist_path"
}

WATCHDOG_LABEL="com.openalgo.watchdog"
EQUITY_LABEL="com.openalgo.runner.equity"
FNO_LABEL="com.openalgo.runner.fno"
MCX_LABEL="com.openalgo.runner.mcx"

WATCHDOG_PLIST="$LAUNCH_AGENTS_DIR/$WATCHDOG_LABEL.plist"
EQUITY_PLIST="$LAUNCH_AGENTS_DIR/$EQUITY_LABEL.plist"
FNO_PLIST="$LAUNCH_AGENTS_DIR/$FNO_LABEL.plist"
MCX_PLIST="$LAUNCH_AGENTS_DIR/$MCX_LABEL.plist"

write_plist \
  "$WATCHDOG_LABEL" \
  "$WATCHDOG_PLIST" \
  "$OPENALGO_APP_DIR" \
  "$OPENALGO_APP_DIR/logs/launchd_watchdog.out.log" \
  "$OPENALGO_APP_DIR/logs/launchd_watchdog.err.log" \
  "$PYTHON_BIN" "$OPENALGO_APP_DIR/scripts/strategy_watchdog.py" "--interval" "60"

write_plist \
  "$EQUITY_LABEL" \
  "$EQUITY_PLIST" \
  "$STRATEGY_DIR" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_equity.out.log" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_equity.err.log" \
  "$PYTHON_BIN" "$STRATEGY_DIR/strategy_runner.py" "--segment=EQUITY" "--action=start"

write_plist \
  "$FNO_LABEL" \
  "$FNO_PLIST" \
  "$STRATEGY_DIR" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_fno.out.log" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_fno.err.log" \
  "$PYTHON_BIN" "$STRATEGY_DIR/strategy_runner.py" "--segment=FNO_OPTIONS" "--action=start"

write_plist \
  "$MCX_LABEL" \
  "$MCX_PLIST" \
  "$STRATEGY_DIR" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_mcx.out.log" \
  "$OPENALGO_APP_DIR/logs/launchd_runner_mcx.err.log" \
  "$PYTHON_BIN" "$STRATEGY_DIR/strategy_runner.py" "--segment=MCX" "--action=start"

kill_matching() {
  local pattern="$1"
  # Avoid killing this setup shell by filtering command path to Python runners only.
  pgrep -fl "$pattern" | awk '/Python/ {print $1}' | while read -r pid; do
    kill -TERM "$pid" 2>/dev/null || true
  done
}

# Stop ad-hoc runner processes so launchd owns lifecycle.
kill_matching "strategy_runner.py --segment=EQUITY --action=start"
kill_matching "strategy_runner.py --segment=FNO_OPTIONS --action=start"
kill_matching "strategy_runner.py --segment=MCX --action=start"

start_in_domain() {
  local domain="$1"
  local target="$domain/$UID_NUM"

  for label in "$WATCHDOG_LABEL" "$EQUITY_LABEL" "$FNO_LABEL" "$MCX_LABEL"; do
    launchctl bootout "$target/$label" 2>/dev/null || true
  done

  launchctl bootstrap "$target" "$WATCHDOG_PLIST" || return 1
  launchctl bootstrap "$target" "$EQUITY_PLIST" || return 1
  launchctl bootstrap "$target" "$FNO_PLIST" || return 1
  launchctl bootstrap "$target" "$MCX_PLIST" || return 1

  launchctl kickstart -k "$target/$WATCHDOG_LABEL"
  launchctl kickstart -k "$target/$EQUITY_LABEL"
  launchctl kickstart -k "$target/$FNO_LABEL"
  launchctl kickstart -k "$target/$MCX_LABEL"

  ACTIVE_DOMAIN="$target"
  return 0
}

if ! start_in_domain "gui"; then
  start_in_domain "user"
fi

echo "Installed and started:"
echo "  $WATCHDOG_LABEL"
echo "  $EQUITY_LABEL"
echo "  $FNO_LABEL"
echo "  $MCX_LABEL"
echo "Domain: $ACTIVE_DOMAIN"
