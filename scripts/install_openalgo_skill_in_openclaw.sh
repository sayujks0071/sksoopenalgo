#!/bin/bash
# Install the OpenAlgo OpenClaw skill into OpenClaw's workspace skills folder.
# Run from repo root: ./scripts/install_openalgo_skill_in_openclaw.sh

set -e
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
SKILL_SRC="$PROJECT_ROOT/openalgo-openclaw-skill"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
OPENCLAW_SKILLS="$OPENCLAW_WORKSPACE/skills"
TARGET="$OPENCLAW_SKILLS/openalgo"

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
  echo "Error: $SKILL_SRC/SKILL.md not found. Run from repo root." >&2
  exit 1
fi

mkdir -p "$OPENCLAW_SKILLS"
if [ -L "$TARGET" ] || [ -d "$TARGET" ]; then
  rm -rf "$TARGET"
fi
cp -R "$SKILL_SRC" "$TARGET"
echo "Installed OpenAlgo skill to $TARGET"
echo "Set OPENALGO_API_KEY (and optionally OPENALGO_BASE_URL) for the OpenClaw gateway, then refresh skills or restart the gateway."
