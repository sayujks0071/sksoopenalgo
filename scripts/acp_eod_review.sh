#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# acp_eod_review.sh
# Launch an OpenClaw ACP session for end-of-day (EOD) trading review.
# Run manually at 15:35 IST or triggered by cron after square-off.
#
# What the agent does in this session:
#   1. get_daily_pnl             — today's realised P&L per strategy
#   2. get_live_positions        — any remaining open positions (should be 0)
#   3. check_strategy_processes  — confirm all strategies are stopped post-15:10
#   4. tail_strategy_log         — check each strategy's last 30 lines for errors
#   5. Produce a P&L summary table (per strategy + total)
#   6. Flag anomalies: excessive losses, strategies not stopped, missed signals
#   7. send_whatsapp_alert       — EOD summary to WhatsApp
#   8. Recommendations for tomorrow
#
# Usage:
#   ./scripts/acp_eod_review.sh            # interactive ACP session
#   GATEWAY_ONLY=1 ./scripts/acp_eod_review.sh  # gateway one-shot (for cron)
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TODAY=$(date +"%Y-%m-%d")
NOW=$(date +"%H:%M IST")

PROMPT="End-of-day review for $TODAY ($NOW).

Active strategies today (DEPLOY):
- ORB_SBIN (NSE, Qty 333, MIS)
- VWAP_RELIANCE (NSE, Qty 268, MIS)
- EMA_HDFCBANK (NSE, Qty 696, MIS)
- MCX_SILVER (SILVERM30APR26FUT, Qty 1, NRML)
- MCX_GOLD (GOLDM02APR26FUT, Qty 1, NRML)

Please do the following:
1. Call get_daily_pnl — show P&L per trade, group by strategy symbol
2. Call get_live_positions — flag any positions that are still open (should be 0 post 15:10)
3. Call check_strategy_processes — confirm all Python strategy processes have stopped
4. Call tail_strategy_log for each active strategy (orb_sbin, vwap_reliance, ema_hdfcbank, mcx_silver, mcx_gold) with lines=30
5. Produce a clean P&L summary table: | Strategy | Trades | P&L | Status |
6. Flag any anomalies (open positions, excessive losses, process still running, errors in logs)
7. Call send_whatsapp_alert with: date, net P&L, top performer, any anomalies (3-4 lines max)
8. Give 3 recommendations for tomorrow

Risk limits to check:
- Daily loss limit: ₹29,000 (flag if exceeded)
- Profit target: ₹1,00,000 (flag if hit)
- Any strategy with DD > 1.5% of its allocated capital → flag for review"

if [ -n "$GATEWAY_ONLY" ] && [ "$GATEWAY_ONLY" = "1" ]; then
  echo "🌆 Running EOD review via gateway (non-interactive)..."
  if [ -f "$PROJECT_ROOT/.env.openclaw" ]; then
    set -a; . "$PROJECT_ROOT/.env.openclaw"; set +a
  fi
  OPENCLAW_USE_GATEWAY=1 OPENCLAW_RESPONSE_DIR="$PROJECT_ROOT/log" \
    "$SCRIPT_DIR/openclaw_send_message.sh" "$PROMPT"
else
  echo "🌆 Starting EOD review ACP session..."
  echo "   Session: agent:main:eod"
  echo "   Date: $TODAY | Time: $NOW"
  echo ""
  echo "💡 Tip: Agent will tail all 5 strategy logs and send WhatsApp summary."
  echo "─────────────────────────────────────────────────────────"

  openclaw acp --session "agent:main:eod" --message "$PROMPT"
fi
