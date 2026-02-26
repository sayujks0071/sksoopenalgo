#!/usr/bin/env bash
set -euo pipefail
ROOT="/Users/mac/openalgo"
APP="$ROOT/openalgo"
VENV="$ROOT/agentlightning/.venv"
PY="$VENV/bin/python"
PID_FILE="$ROOT/log/agent_gateway.pid"
LOG_FILE="$ROOT/log/agent_gateway.log"

mkdir -p "$ROOT/log"

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$VENV"
  "$PY" -m pip install --upgrade pip >/dev/null
fi

# Keep gateway deps isolated from OpenAlgo runtime pins.
if ! "$PY" -c "import flask,httpx" >/dev/null 2>&1; then
  "$PY" -m pip install flask httpx >/dev/null
fi
if ! "$PY" -c "import pandas,numpy" >/dev/null 2>&1; then
  "$PY" -m pip install pandas numpy >/dev/null
fi
if ! "$PY" -c "import pandas_ta" >/dev/null 2>&1; then
  PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$PYVER" == "3.14" ]]; then
    echo "skip pandas-ta install on Python ${PYVER} (optional dependency)"
  else
    "$PY" -m pip install pandas-ta >/dev/null || true
  fi
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "agent gateway already running pid=$(cat "$PID_FILE")"
  exit 0
fi

export OA_AGENT_BIND="127.0.0.1"
export OA_AGENT_PORT="9101"
export PYTHONPATH="$APP:${PYTHONPATH:-}"
cd "$APP"

# Fully detach to survive parent shell lifecycle.
if command -v setsid >/dev/null 2>&1; then
  setsid "$PY" "$APP/scripts/agent_gateway.py" >> "$LOG_FILE" 2>&1 < /dev/null &
else
  nohup "$PY" "$APP/scripts/agent_gateway.py" >> "$LOG_FILE" 2>&1 < /dev/null &
fi
PID=$!
echo "$PID" > "$PID_FILE"
sleep 0.5
if kill -0 "$PID" 2>/dev/null; then
  echo "started pid=$PID"
else
  echo "failed_to_start"
  exit 1
fi
