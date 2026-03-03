#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# acp_morning_brief.sh
# Launch an OpenClaw ACP session for pre-market analysis.
# Run manually at ~08:55 AM IST or triggered by cron.
#
# What the agent does in this session:
#   1. list_active_strategies    — show portfolio status + PF/DD stats
#   2. get_funds                 — confirm available capital
#   3. check_strategy_processes  — see if any strategies survived from yesterday
#   4. Recommend which strategies to deploy today
#   5. Generate deployment commands ready to paste
#   6. send_whatsapp_alert       — summary sent to WhatsApp
#
# Usage:
#   ./scripts/acp_morning_brief.sh            # interactive ACP session
#   GATEWAY_ONLY=1 ./scripts/acp_morning_brief.sh  # gateway one-shot (non-interactive)
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TODAY=$(date +"%Y-%m-%d")
NOW=$(date +"%H:%M IST")

# Pre-market prompt sent to the agent
PROMPT="Good morning! Pre-market briefing for $TODAY ($NOW).

Please do the following:
1. Call list_active_strategies — show a table of all strategies with status (DEPLOY/REVIEW/PAUSE), PF, DD%, WR%
2. Call get_funds — confirm available capital and margin
3. Call check_strategy_processes — check if any strategies are already running (they shouldn't be pre-market)
4. Based on PF and DD, recommend today's deployment priority (highest PF first)
5. Output exact copy-paste deployment bash commands for all DEPLOY strategies
6. Call send_whatsapp_alert with a 3-line summary: strategies to deploy, capital available, any risks

Keep the output structured with clear sections."

if [ -n "$GATEWAY_ONLY" ] && [ "$GATEWAY_ONLY" = "1" ]; then
  # Non-interactive gateway call (for cron use)
  echo "🌅 Running pre-market brief via gateway (non-interactive)..."

  if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
    set -a; . "$PROJECT_ROOT/.env.openclaw"; set +a
  fi
  OPENCLAW_USE_GATEWAY=1 OPENCLAW_RESPONSE_DIR="$PROJECT_ROOT/log" \
    "$SCRIPT_DIR/openclaw_send_message.sh" "$PROMPT"
else
  # Interactive ACP session
  echo "🌅 Starting pre-market ACP session..."
  echo "   Session: agent:main:premarket"
  echo "   Date: $TODAY | Time: $NOW"
  echo ""
  echo "💡 Tip: The agent has access to these tools:"
  echo "   list_active_strategies | get_funds | check_strategy_processes"
  echo "   tail_strategy_log | send_whatsapp_alert"
  echo ""
  echo "Starting ACP bridge. Type your questions or press Ctrl+C to exit."
  echo "─────────────────────────────────────────────────────────"

  # Launch ACP session — agent starts with the morning brief prompt
  openclaw acp --session "agent:main:premarket" --message "$PROMPT"
fi
