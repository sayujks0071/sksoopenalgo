#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# acp_backtest_lab.sh
# Launch an OpenClaw ACP design session for strategy improvement and backtesting.
#
# What the agent does in this session:
#   - Analyse current strategy portfolio (PF, DD, WR stats)
#   - Identify underperformers and suggest filter improvements
#   - Design parameter sweep ranges for SuperTrend_NIFTY (PF=1.37, target >1.5)
#   - Suggest new strategy candidates for the portfolio
#   - Generate Python code modifications for run_extended_backtests.py
#
# Key strategies to focus on:
#   - SuperTrend_NIFTY (PF=1.37 REVIEW → target DEPLOY with PF>1.5)
#   - New strategy candidates (BankNIFTY, Midcap, etc.)
#
# Usage:
#   ./scripts/acp_backtest_lab.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

STRATEGIES_JSON="/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/active_strategies.json"
BACKTEST_RUNNER="/Users/mac/sksoopenalgo/openalgo/run_extended_backtests.py"

PROMPT="Backtest improvement lab session.

Context (from active_strategies.json):
$(cat "$STRATEGIES_JSON" 2>/dev/null || echo '[file not readable]')

Key improvement goals:
1. SuperTrend_NIFTY: currently PF=1.37 (REVIEW). Need PF > 1.5 to DEPLOY.
   - Script: supertrend_vwap_strategy.py
   - Current params: adx_threshold=25, adx_period=14, stop_pct=1.8
   - Backtest window: 58d 5m on NIFTYBEES.NS (multiply PnL by 80x for NIFTY futures)
   - What additional filters or param changes could push PF above 1.5?

2. Portfolio gaps:
   - No BankNIFTY strategy in DEPLOY list
   - No midcap/smallcap strategy
   - Suggest 1-2 new strategy candidates with expected PF based on similar strategies

3. MCX improvements:
   - MCX_SILVER (PF=2.98) — can we improve WR% from 60.9% further?
   - MCX_GOLD (PF=2.08) — new, just added. Params: EMA9/21 + RSI + ADX>20

Please:
1. Review the portfolio and flag the weakest strategies
2. Propose 3 specific parameter changes for SuperTrend_NIFTY with reasoning
3. Suggest one new strategy candidate with a concrete backtesting approach
4. Output any Python code changes for run_extended_backtests.py

Files to edit if needed:
- run_extended_backtests.py: $BACKTEST_RUNNER
- active_strategies.json: $STRATEGIES_JSON"

echo "🔬 Starting backtest lab ACP session..."
echo "   Session: agent:design:backtest"
echo "   Focus: SuperTrend_NIFTY improvement + new strategy candidates"
echo ""
echo "💡 Tip: Attach relevant backtest result files to the session if needed."
echo "─────────────────────────────────────────────────────────"

openclaw acp --session "agent:design:backtest" --message "$PROMPT"
