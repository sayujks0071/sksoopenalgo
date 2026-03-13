#!/bin/bash
set -euo pipefail

REVIEWED="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/start_canary_5002_reviewed.sh"
MANIFEST="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/deployment_manifest_5002.md"

if [[ ! -x "${REVIEWED}" ]]; then
  chmod +x "${REVIEWED}"
fi

echo "Direct options launcher disabled in favor of reviewed flow."
echo "Options strategies without dry-run support remain review-only."
echo "See manifest: ${MANIFEST}"
echo
echo "Launching reviewed dry-run profile preview. Pass --execute to start only the reviewed dry-run subset."

exec "${REVIEWED}" --profile dryrun "$@"
