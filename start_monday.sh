#!/usr/bin/env bash
# ============================================================
#  Monday March 2 2026 — Full Deploy Script
#  Equity (₹5L: SBIN/RELIANCE/HDFCBANK) + IC Monitor
#  Run from: /Users/mac/sksoopenalgo/openalgo/
#
#  USAGE:
#    Step 1 (9:10 AM — pre-entry check):   bash start_monday.sh check
#    Step 2 (9:14 AM — start equity):      bash start_monday.sh equity
#    Step 3 (9:15 AM — Wave 1 IC entry):   /ic-wave1 (Claude skill)
#    Step 4 (post Wave 1 — start monitor): bash start_monday.sh ic_monitor
#
#  REQUIREMENTS:
#    - API key updated in ic_config.py _FALLBACK_KEY and .env OPENALGO_APIKEY
#    - Dhan auth active (verified via funds endpoint)
#    - OpenAlgo server running on port 5002
# ============================================================

BASE_DIR="/Users/mac/sksoopenalgo/openalgo"
STRAT_DIR="$BASE_DIR/openalgo"
PYTHON="$STRAT_DIR/.venv/bin/python3"
HOST="http://127.0.0.1:5002"

# ── Load API key from ic_config ───────────────────────────────────────────────
API_KEY=$(cd "$BASE_DIR" && "$PYTHON" -c "import sys; sys.path.insert(0,'$BASE_DIR'); from ic_config import OPENALGO_KEY; print(OPENALGO_KEY)" 2>/dev/null)
if [ -z "$API_KEY" ]; then
    echo "❌ Cannot load API key from ic_config.py — update _FALLBACK_KEY first!"
    exit 1
fi
echo "✅ API key loaded: ${API_KEY:0:12}...${API_KEY: -4}"

# ── Verify server + auth ─────────────────────────────────────────────────────
verify_auth() {
    RESP=$(curl -s -X POST "$HOST/api/v1/funds" \
        -H "Content-Type: application/json" \
        -d "{\"apikey\":\"$API_KEY\"}" 2>/dev/null)
    if echo "$RESP" | grep -q '"status":"success"'; then
        CASH=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('availablecash','?'))" 2>/dev/null)
        echo "✅ Auth OK | Available cash: ₹$CASH"
        return 0
    else
        echo "❌ Auth FAILED: $RESP"
        return 1
    fi
}

# ════════════════════════════════════════════════════════════════════════════
case "$1" in

# ── PRE-ENTRY CHECK (9:10 AM) ─────────────────────────────────────────────
check)
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  IC Pre-Entry Check — $(date '+%H:%M:%S')"
    echo "═══════════════════════════════════════════════════════"
    verify_auth || exit 1
    echo ""
    cd "$BASE_DIR" && "$PYTHON" ic_pre_entry.py
    EXIT_CODE=$?
    echo ""
    case $EXIT_CODE in
      0) echo "🟢 GO — All conditions met. Proceed with Wave 1 at 9:15 AM" ;;
      1) echo "🟡 CAUTION — Reduce lots or wait. Check VIX/gap." ;;
      2) echo "🔴 SKIP — Do NOT trade today (VIX too low / trending / thin premium)" ;;
    esac

    # 🧠 Seed ruflo memory with today's session state (non-critical — trading continues if unavailable)
    echo ""
    echo "  🧠 Seeding ruflo memory..."
    SEED_OUT=$(cd "$BASE_DIR" && "$PYTHON" ruflo_bridge.py seed 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$SEED_OUT" ]; then
        EXPIRY_TAG=$(echo "$SEED_OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'expiry={d[\"expiry\"]} session={d[\"session_date\"]}')" 2>/dev/null)
        echo "  ✅ ruflo seeded: $EXPIRY_TAG"
    else
        echo "  ⚠️  ruflo unavailable (non-critical — trading proceeds normally)"
    fi

    exit $EXIT_CODE
    ;;

# ── START EQUITY STRATEGIES (9:14 AM) ─────────────────────────────────────
equity)
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Starting Equity Strategies — $(date '+%H:%M:%S')"
    echo "  Capital: ₹5L (ORB₹2L + VWAP₹1.5L + EMA₹1.5L)"
    echo "═══════════════════════════════════════════════════════"

    verify_auth || exit 1

    # Kill any running instances
    pkill -f "orb_equity_volume.py" 2>/dev/null && echo "  Stopped old ORB instance"
    pkill -f "vwap_rsi_equity.py"   2>/dev/null && echo "  Stopped old VWAP instance"
    pkill -f "ema_supertrend_equity.py" 2>/dev/null && echo "  Stopped old EMA instance"
    sleep 1

    # ── 1. ORB Volume — SBIN (₹2L, qty=333) ──────────────────────────────
    echo ""
    echo "  Starting ORB_SBIN (qty=333, SL=0.5%, TP=1.5%, gap_filter=on)..."
    OPENALGO_HOST="$HOST" \
    OPENALGO_APIKEY="$API_KEY" \
    SYMBOL="SBIN" EXCHANGE="NSE" PRODUCT="MIS" \
    QUANTITY="333" RISK_PER_TRADE="2000" \
    ORB_MINUTES="30" SL_PCT="0.5" TP_PCT="1.5" \
    VOLUME_MULTIPLIER="1.7" MAX_HOLD_MIN="90" \
    GAP_FILTER="true" GAP_THRESHOLD_PCT="0.15" \
    MAX_ORDERS_PER_DAY="2" STRATEGY_NAME="ORB_SBIN" \
    nohup "$PYTHON" "$STRAT_DIR/strategies/scripts/orb_equity_volume.py" \
        > /tmp/orb_sbin.log 2>&1 &
    echo "  ORB_SBIN PID=$! → tail -f /tmp/orb_sbin.log"

    # ── 2. VWAP RSI — RELIANCE (₹1.5L, qty=268) ──────────────────────────
    echo ""
    echo "  Starting VWAP_RELIANCE (qty=268, SL=0.4%, RSI 30/70)..."
    OPENALGO_HOST="$HOST" \
    OPENALGO_APIKEY="$API_KEY" \
    SYMBOL="RELIANCE" EXCHANGE="NSE" PRODUCT="MIS" \
    QUANTITY="268" RISK_PER_TRADE="1500" \
    SL_PCT="0.4" VWAP_STD_MULT="1.5" \
    RSI_OVERSOLD="30" RSI_OVERBOUGHT="70" \
    MAX_ORDERS_PER_DAY="4" STRATEGY_NAME="VWAP_RELIANCE" \
    nohup "$PYTHON" "$STRAT_DIR/strategies/scripts/vwap_rsi_equity.py" \
        > /tmp/vwap_reliance.log 2>&1 &
    echo "  VWAP_RELIANCE PID=$! → tail -f /tmp/vwap_reliance.log"

    # ── 3. EMA SuperTrend — HDFCBANK (₹1.5L, qty=696) ────────────────────
    echo ""
    echo "  Starting EMA_HDFCBANK (qty=696, ATR SL×1.5 TP×3.0)..."
    OPENALGO_HOST="$HOST" \
    OPENALGO_APIKEY="$API_KEY" \
    SYMBOL="HDFCBANK" EXCHANGE="NSE" PRODUCT="MIS" \
    QUANTITY="696" RISK_PER_TRADE="1500" \
    FAST_EMA="5" SLOW_EMA="13" \
    SUPERTREND_MULT="2.5" ADX_MIN="0" \
    ATR_SL_MULT="1.5" ATR_TP_MULT="3.0" \
    MAX_ORDERS_PER_DAY="4" STRATEGY_NAME="EMA_HDFCBANK" \
    nohup "$PYTHON" "$STRAT_DIR/strategies/scripts/ema_supertrend_equity.py" \
        > /tmp/ema_hdfcbank.log 2>&1 &
    echo "  EMA_HDFCBANK PID=$! → tail -f /tmp/ema_hdfcbank.log"

    echo ""
    echo "✅ All 3 equity strategies started."
    echo "   Monitor with: bash start_monday.sh status"
    ;;

# ── START IC MONITOR (after Wave 1 fills) ────────────────────────────────
ic_monitor)
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Starting IC Monitor v3 — $(date '+%H:%M:%S')"
    echo "  Expiry: 05MAR26 | Max Loss: ₹1,01,000"
    echo "═══════════════════════════════════════════════════════"

    # 🧠 ruflo calibration snapshot (non-critical)
    echo "  🧠 ruflo calibration..."
    CAL_OUT=$(cd "$BASE_DIR" && "$PYTHON" ruflo_bridge.py calibrate 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$CAL_OUT" ]; then
        CAL_SUMMARY=$(echo "$CAL_OUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
status = d.get('status', '?')
vix = d.get('vix', 0)
credit = d.get('credit', 0)
regime = d.get('regime', '?')
print(f'{status} | VIX={vix:.1f} | credit={credit:.1f}/unit | regime={regime}')
" 2>/dev/null)
        echo "  ✅ ruflo calibrate: $CAL_SUMMARY"
    else
        echo "  ⚠️  ruflo calibration unavailable (non-critical)"
    fi
    echo ""

    # Kill any stale instance
    pkill -f "ic_monitor.py" 2>/dev/null && echo "  Stopped old IC Monitor" && sleep 2

    cd "$BASE_DIR" && \
    nohup "$PYTHON" ic_monitor.py \
        > /tmp/ic_monitor.log 2>&1 &
    echo "  IC Monitor PID=$! → tail -f /tmp/ic_monitor.log"
    echo "  Or use ic-status Claude skill to check"
    ;;

# ── STATUS CHECK ─────────────────────────────────────────────────────────
status)
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Running Strategy Processes — $(date '+%H:%M:%S')"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    for name in orb_equity_volume vwap_rsi_equity ema_supertrend_equity ic_monitor; do
        PID=$(pgrep -f "${name}.py" 2>/dev/null)
        if [ -n "$PID" ]; then
            echo "  ✅ $name  PID=$PID"
        else
            echo "  ❌ $name  NOT running"
        fi
    done

    echo ""
    echo "  Recent ORB log:"
    tail -5 /tmp/orb_sbin.log 2>/dev/null | sed 's/^/    /'
    echo "  Recent VWAP log:"
    tail -5 /tmp/vwap_reliance.log 2>/dev/null | sed 's/^/    /'
    echo "  Recent EMA log:"
    tail -5 /tmp/ema_hdfcbank.log 2>/dev/null | sed 's/^/    /'

    echo ""
    echo "  IC Heartbeat:"
    cat "$BASE_DIR/ic_heartbeat.json" 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(f'    NIFTY={d[\"nifty\"]} MTM=+{d[\"mtm\"]:,.0f} iter={d[\"iteration\"]} ts={d[\"timestamp\"][-8:]}')" 2>/dev/null || echo "    (no heartbeat yet)"
    ;;

# ── POST-SESSION ruflo LEARNING (3:30 PM or after /ic-close) ─────────────
post_session)
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  IC Post-Session — $(date '+%H:%M:%S')"
    echo "  Sending session data to ruflo for RL learning..."
    echo "═══════════════════════════════════════════════════════"
    POST_OUT=$(cd "$BASE_DIR" && "$PYTHON" ruflo_bridge.py post_session 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$POST_OUT" ]; then
        echo "$POST_OUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pnl = d.get('final_pnl', 0)
quality = d.get('quality', 0)
waves = d.get('waves_executed', 0)
pattern = d.get('new_pattern', '-')[:80]
sign = '+' if pnl >= 0 else ''
print(f'  Final P&L:     {sign}{pnl:,.0f}')
print(f'  RL quality:    {quality:.2f}  (0.5=breakeven, 1.0=max profit)')
print(f'  Waves done:    {waves}')
print(f'  New pattern:   {pattern}')
print('  ✅ ruflo SONA trajectory updated — learning complete')
" 2>/dev/null || echo "  ⚠️  Could not parse ruflo output"
    else
        echo "  ⚠️  ruflo unavailable — session data not persisted (non-critical)"
    fi
    ;;

# ── STOP ALL ─────────────────────────────────────────────────────────────
stop)
    echo "⚠️  Stopping all strategies..."
    for name in orb_equity_volume vwap_rsi_equity ema_supertrend_equity ic_monitor; do
        pkill -f "${name}.py" 2>/dev/null && echo "  Stopped $name" || echo "  $name not running"
    done
    echo "Done."
    ;;

*)
    echo "Usage: $0 {check|equity|ic_monitor|status|post_session|stop}"
    echo ""
    echo "  check        — Run IC pre-entry check + seed ruflo memory (9:10 AM)"
    echo "  equity       — Start all 3 equity strategies (9:14 AM)"
    echo "  ic_monitor   — Ruflo calibrate + start IC monitor after Wave 1 fills"
    echo "  status       — Show running processes + recent logs"
    echo "  post_session — Send EOD session data to ruflo for RL learning (3:30 PM)"
    echo "  stop         — Kill all strategies"
    ;;
esac
