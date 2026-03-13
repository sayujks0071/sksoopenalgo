#!/bin/bash
set -euo pipefail

REVIEWED="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/start_canary_5002_reviewed.sh"

if [[ ! -x "${REVIEWED}" ]]; then
  chmod +x "${REVIEWED}"
fi

echo "Routing to reviewed canary launcher for equity profile."
echo "Default is preview only. Pass --execute to actually start the reviewed canary set."

exec "${REVIEWED}" --profile equity "$@"
