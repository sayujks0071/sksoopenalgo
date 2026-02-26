#!/usr/bin/env bash
#
# Index OpenClaw's markdown memory with memsearch for semantic search.
#
# Prerequisites:
#   - pip install memsearch   (and optionally "memsearch[local]" for no API key)
#   - memsearch config init   (run once to create ~/.memsearch/config.toml)
#
# Usage:
#   ./scripts/openclaw-memsearch-index.sh           # index once
#   ./scripts/openclaw-memsearch-index.sh --watch   # index then run watcher in background
#
# Override workspace path (default: ~/.openclaw/workspace):
#   OPENCLAW_WORKSPACE=/path/to/workspace ./scripts/openclaw-memsearch-index.sh
#

set -e

WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
WATCH=false

for arg in "$@"; do
  case "$arg" in
    --watch) WATCH=true ;;
    -h|--help)
      echo "Usage: $0 [--watch]"
      echo "  Index OpenClaw memory at OPENCLAW_WORKSPACE (default: ~/.openclaw/workspace)"
      echo "  --watch  After indexing, run memsearch watch in the background"
      echo ""
      echo "Prerequisites: pip install memsearch && memsearch config init"
      exit 0
      ;;
  esac
done

if ! command -v memsearch &>/dev/null; then
  echo "memsearch not found. Install with: pip install memsearch"
  echo "Then run: memsearch config init"
  exit 1
fi

if [[ ! -d "$WORKSPACE" ]]; then
  echo "OpenClaw workspace not found: $WORKSPACE"
  echo "Set OPENCLAW_WORKSPACE if your workspace is elsewhere."
  exit 1
fi

# Ensure we're not indexing an empty or wrong path: expect MEMORY.md or memory/ subdir
if [[ ! -f "$WORKSPACE/MEMORY.md" ]] && [[ ! -d "$WORKSPACE/memory" ]]; then
  echo "Workspace does not look like OpenClaw memory (no MEMORY.md or memory/): $WORKSPACE"
  exit 1
fi

echo "Indexing OpenClaw memory at: $WORKSPACE"
memsearch index "$WORKSPACE"

if [[ "$WATCH" == true ]]; then
  echo "Starting memsearch watch in background (Ctrl+C or kill to stop)."
  memsearch watch "$WORKSPACE" &
  echo "Watcher PID: $!"
fi
