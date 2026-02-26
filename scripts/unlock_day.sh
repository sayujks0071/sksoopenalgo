#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${OA_RISK_LOCK_FILE:-$ROOT_DIR/openalgo/logs/runner_risk_lock_state.json}"
GUI_UID="$(id -u)"

SEGMENT="ALL"
FOR_DATE="$(TZ=Asia/Kolkata date +%F)"
ALL_DATES=0

DO_SHOW=0
DO_UNLOCK=0
DO_DISABLE=0
DO_ENABLE=0
DO_START=0
YES=0

usage() {
  cat <<'USAGE'
Usage:
  scripts/unlock_day.sh [--show] [--unlock] [--segment SEGMENT] [--for-date YYYY-MM-DD] [--all-dates] [--yes]
  scripts/unlock_day.sh [--enable-runners|--disable-runners|--start-runners] [--segment SEGMENT] [--yes]

Segments:
  EQUITY | FNO_OPTIONS | MCX | ALL

Examples:
  scripts/unlock_day.sh --show
  scripts/unlock_day.sh --unlock --segment MCX --yes
  scripts/unlock_day.sh --unlock --segment ALL --all-dates --yes
  scripts/unlock_day.sh --enable-runners --segment FNO_OPTIONS --yes
  scripts/unlock_day.sh --start-runners --segment MCX --yes
USAGE
}

normalize_segment() {
  local raw
  raw="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  case "$raw" in
    EQUITY|FNO_OPTIONS|MCX|ALL) echo "$raw" ;;
    *) echo "Invalid segment: $1" >&2; exit 2 ;;
  esac
}

segment_list() {
  if [[ "$SEGMENT" == "ALL" ]]; then
    echo "EQUITY FNO_OPTIONS MCX"
  else
    echo "$SEGMENT"
  fi
}

label_for_segment() {
  case "$1" in
    EQUITY) echo "com.openalgo.runner.equity" ;;
    FNO_OPTIONS) echo "com.openalgo.runner.fno" ;;
    MCX) echo "com.openalgo.runner.mcx" ;;
    *) echo "Unknown segment: $1" >&2; exit 2 ;;
  esac
}

market_open_for_segment() {
  local seg="$1"
  local exch="NSE"
  [[ "$seg" == "MCX" ]] && exch="MCX"

  python3 - <<PY
import sys
from pathlib import Path
root = Path("$ROOT_DIR")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "openalgo"))
try:
    from openalgo.strategies.utils.trading_utils import is_market_open
except Exception:
    from strategies.utils.trading_utils import is_market_open
print("1" if is_market_open("$exch") else "0")
PY
}

show_lock_state() {
  python3 - <<PY
import json
from pathlib import Path

path = Path("$LOCK_FILE")
if not path.exists():
    print(f"Lock file not found: {path}")
    raise SystemExit(0)

try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Failed to read lock file: {exc}")
    raise SystemExit(1)

if not isinstance(data, dict) or not data:
    print(f"Lock file is empty: {path}")
    raise SystemExit(0)

print(f"Lock file: {path}")
for seg, rec in data.items():
    if not isinstance(rec, dict):
        print(f"- {seg}: <invalid>")
        continue
    print(
        f"- {seg}: locked={rec.get('locked')} date={rec.get('date')} "
        f"pnl={rec.get('pnl')} reason={rec.get('reason')}"
    )
PY
}

unlock_state() {
  local segments_csv
  segments_csv="$(segment_list | tr ' ' ',')"
  python3 - <<PY
import json
from pathlib import Path

path = Path("$LOCK_FILE")
target = set("$segments_csv".split(",")) if "$segments_csv" else set()
for_date = "$FOR_DATE"
all_dates = bool(int("$ALL_DATES"))

if not path.exists():
    print(f"Lock file not found: {path}")
    raise SystemExit(0)

data = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    print("Lock file content is invalid; resetting to empty dict")
    data = {}

removed = []
for seg in list(data.keys()):
    if target and seg not in target:
        continue
    rec = data.get(seg)
    if not isinstance(rec, dict):
        removed.append((seg, "<invalid>"))
        data.pop(seg, None)
        continue
    rec_date = str(rec.get("date", ""))
    if all_dates or rec_date == for_date:
        removed.append((seg, rec_date))
        data.pop(seg, None)

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2), encoding="utf-8")

if removed:
    print("Removed locks:")
    for seg, d in removed:
        print(f"- {seg} (date={d})")
else:
    print("No matching lock entries removed.")
PY
}

disable_runners() {
  for seg in $(segment_list); do
    local label plist
    label="$(label_for_segment "$seg")"
    plist="$HOME/Library/LaunchAgents/${label}.plist"
    launchctl unload -w "$plist" 2>/dev/null || true
    launchctl disable "gui/$GUI_UID/$label" 2>/dev/null || true
    pkill -f "strategy_runner.py --segment=${seg} --action=start" 2>/dev/null || true
    echo "Disabled ${label}"
  done
}

enable_runners() {
  for seg in $(segment_list); do
    local label plist
    label="$(label_for_segment "$seg")"
    plist="$HOME/Library/LaunchAgents/${label}.plist"
    launchctl enable "gui/$GUI_UID/$label" 2>/dev/null || true
    launchctl load -w "$plist" 2>/dev/null || true
    echo "Enabled ${label}"
  done
}

start_runners() {
  for seg in $(segment_list); do
    local label open
    label="$(label_for_segment "$seg")"
    if launchctl print-disabled "gui/$GUI_UID" 2>/dev/null | rg -q "\"${label}\" => disabled"; then
      echo "Skip ${label}: service is disabled (run --enable-runners first)"
      continue
    fi
    open="$(market_open_for_segment "$seg")"
    if [[ "$open" != "1" ]]; then
      echo "Skip ${label}: market closed for ${seg}"
      continue
    fi
    if launchctl kickstart -k "gui/$GUI_UID/$label" >/dev/null 2>&1; then
      echo "Started ${label}"
    else
      echo "Failed to start ${label}"
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --show) DO_SHOW=1 ;;
    --unlock) DO_UNLOCK=1 ;;
    --disable-runners) DO_DISABLE=1 ;;
    --enable-runners) DO_ENABLE=1 ;;
    --start-runners) DO_START=1 ;;
    --segment)
      [[ $# -ge 2 ]] || { echo "--segment requires value" >&2; exit 2; }
      SEGMENT="$(normalize_segment "$2")"
      shift
      ;;
    --for-date)
      [[ $# -ge 2 ]] || { echo "--for-date requires value" >&2; exit 2; }
      FOR_DATE="$2"
      shift
      ;;
    --all-dates) ALL_DATES=1 ;;
    --yes) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
  shift
done

if (( DO_SHOW == 0 && DO_UNLOCK == 0 && DO_DISABLE == 0 && DO_ENABLE == 0 && DO_START == 0 )); then
  DO_SHOW=1
fi

if (( DO_UNLOCK || DO_DISABLE || DO_ENABLE || DO_START )); then
  if (( YES == 0 )); then
    echo "Refusing mutating action without --yes" >&2
    exit 2
  fi
fi

if (( DO_SHOW )); then
  show_lock_state
fi
if (( DO_UNLOCK )); then
  unlock_state
fi
if (( DO_DISABLE )); then
  disable_runners
fi
if (( DO_ENABLE )); then
  enable_runners
fi
if (( DO_START )); then
  start_runners
fi
