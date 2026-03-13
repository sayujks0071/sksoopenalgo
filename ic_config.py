#!/usr/bin/env python3
"""IC Trading Config — single source of truth. Import, don't copy."""
import os, sys
from datetime import date, timedelta

# Auto-load .env from the project directory so scripts run without manual export
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
_load_dotenv()

# ─── API & BROKER ────────────────────────────────────────────────────────────
_FALLBACK_KEY = "09854f66270c372a56b5560970270d00e375d2e63131a3f5d9dd0f7d2505aae7"
OPENALGO_KEY  = os.environ.get("OPENALGO_API_KEY", _FALLBACK_KEY)
OPENALGO_URL  = "http://127.0.0.1:5002/api/v1"
LOT_SIZE      = 65
SPAN_PER_LOT  = 32_000   # MIS margin per IC spread lot

if OPENALGO_KEY == _FALLBACK_KEY and not os.environ.get("OPENALGO_API_KEY"):
    print("[ic_config] WARNING: using hardcoded key — set OPENALGO_API_KEY env var",
          file=sys.stderr, flush=True)

# ─── PATHS (2.1: centralized — previously scattered across files) ────────────
_BASE_DIR      = "/Users/mac/sksoopenalgo/openalgo"
LOG_FILE       = os.path.join(_BASE_DIR, "ic_monitor.log")
STATE_FILE     = os.path.join(_BASE_DIR, "ic_state.json")
HEARTBEAT_FILE = os.path.join(_BASE_DIR, "ic_heartbeat.json")
EVENTS_LOG     = os.path.join(_BASE_DIR, "ic_monitor_events.jsonl")
PID_FILE       = "/tmp/ic_monitor.pid"
TRADE_HISTORY  = os.path.expanduser(
    "~/.openclaw/workspace/memory/trading/trade_history.jsonl")

# ─── WEBHOOKS ────────────────────────────────────────────────────────────────
N8N_WEBHOOK = "https://sayujks20417.app.n8n.cloud/webhook/ic-trading-alert"

# ─── SCHEDULE (hour, minute) tuples ──────────────────────────────────────────
HARD_CLOSE_TIME    = (15, 10)   # 3:10 PM — non-negotiable
PRE_CLOSE_TIME     = (15,  0)   # 3:00 PM — close if MTM > 0
AFTERNOON_CE_CLOSE = (14, 30)   # 2:30 PM — close CE if MTM > ₹10K
WAVE2_TIME         = (11, 30)
WAVE3_TIME         = (14,  0)
WAVE2_MIN_MTM      = 0          # skip Wave 2 if session MTM < 0
WAVE3_MIN_MTM      = 35_000     # skip Wave 3 if session MTM < ₹35K

# ─── RISK LIMITS ─────────────────────────────────────────────────────────────
MAX_DAILY_LOSS       = -101_000  # 6% of ₹16.88L capital
MAX_CONSECUTIVE_LOSSES = 2      # 3.2: circuit breaker
WEEKLY_LOSS_LIMIT    = -50_000   # 3.2: weekly floor

# ─── SIZING ──────────────────────────────────────────────────────────────────
MAX_LOTS_HARD_CAP    = 40
MIN_LOTS             = 6

# ─── DYNAMIC EXIT THRESHOLDS ────────────────────────────────────────────────
# tastytrade research: closing at 75% beats 80% on risk-adjusted returns
# — last 20% of premium captures the most gamma risk for the least reward
PREMIUM_CLOSE_PCT    = 0.75     # ≥75% captured → close all
PREMIUM_CLOSE_AFTER  = 0.60     # ≥60% AND time ≥ 2:00 PM → close all
PREMIUM_CLOSE_PROX   = 0.50     # ≥50% AND within 50pt → close all
# tastytrade / Karen Supertrader: never lose more than 2× the credit received
# proportional stop > capital % stop (scales with actual position risk)
PREMIUM_STOP_MULTIPLE = 2.0     # close if MTM loss > PREMIUM_STOP_MULTIPLE × entry_premium
# VIX floor: world's best premium sellers don't sell cheap premium
# Below VIX_MIN_ENTRY the edge disappears → SKIP
VIX_MIN_ENTRY        = 13.0     # India VIX < this → premium too thin → SKIP
ROLL_ZONE            = 80       # 80pt from short + <40% → roll
GAMMA_ZONE_PARTIAL   = 60       # 60pt → close that side
GAMMA_ZONE_FULL      = 30       # 30pt → emergency close all
TRAIL_LOCK_THRESHOLD = 40_000   # trailing lock activates when peak > ₹40K (scaled for 33-lot)
TRAIL_LOCK_PCT       = 0.70     # protect 70% of peak MTM
VIX_SPIKE_TRIGGER    = 0.15     # VIX rises 15%+ → close all

# ─── PER-LEG SL MULTIPLIERS ─────────────────────────────────────────────────
# CRITICAL FIX (2026-03-02): The per-leg 2x SL fired prematurely on 2026-03-02,
# triggering at MTM=-5,784 when portfolio SL (2x entry premium ≈ -25,872) was not hit.
# Root cause: individual option prices can easily double mid-session, even when the
# overall IC is still safe. Per-leg SL must be LOOSER than the portfolio-level stop.
# Strategy: per-leg SL is a LAST RESORT for extreme leg moves; portfolio stop is primary.
# Per-leg SL fires only if an individual leg has moved MORE than the premium stop would
# ever catch — i.e., truly runaway scenario.
# Research (CMT/CBOE): per-leg 3x allows mean-reversion; 2x creates whipsaws.
PER_LEG_SL_INITIAL   = 3.0     # first 60% of session: SL at 3× avg (was 2.0x → premature)
PER_LEG_SL_AFTER_60  = 2.5     # after capturing 60% premium: tighten to 2.5×
PER_LEG_SL_AFTER_2PM = 2.0     # after 2 PM: tighten to 2.0× (end-of-day protection)
# Guard: per-leg SL only fires if portfolio MTM is also negative (avoids firing
# on a recovering spread where one leg moved but overall IC is still OK)
PER_LEG_SL_PORTFOLIO_GUARD = True   # True = skip per-leg SL if portfolio MTM > -30% of entry_premium

# ─── ENTRY SAFETY ────────────────────────────────────────────────────────────
# CRITICAL FIX (2026-03-02): Short PE was entered at 24750 with NIFTY at 24826 → only 76pt
# gap. A single bearish candle breached the short strike. Minimum safe distance = 100pt.
MIN_ENTRY_DISTANCE   = 100     # NIFTY must be > 100pt from both short strikes at entry
# If ATM rounding puts NIFTY closer than this, widen shorts to ATM±150 automatically
WIDEN_SHORT_OFFSET   = 150     # fallback short offset when MIN_ENTRY_DISTANCE is breached

# ─── SYMBOL BUILDER ──────────────────────────────────────────────────────────
def build_option_symbol(underlying: str, expiry_ddmmmyy: str,
                        strike: float, opt_type: str) -> str:
    """Build NSE canonical option symbol.

    Format: {UNDERLYING}{DDMMMYY}{strike}{CE|PE}
    Examples: NIFTY02MAR2625400CE, BANKNIFTY03MAR2653000PE

    Args:
        underlying:    'NIFTY', 'BANKNIFTY', or 'SENSEX'
        expiry_ddmmmyy: expiry in DDMMMYY format, e.g. '03MAR26'
        strike:        numeric strike (will be int-converted)
        opt_type:      'CE' or 'PE'
    """
    return f"{underlying.upper()}{expiry_ddmmmyy}{int(strike)}{opt_type.upper()}"


# ─── EXPIRY ──────────────────────────────────────────────────────────────────
def get_next_expiry() -> str:
    """Return next NIFTY 50 weekly expiry (Thursday) as DDMMMYY, e.g. '05MAR26'.
    NIFTY 50 weekly options expire on Thursday (confirmed from live session data).
    """
    import pytz
    from datetime import datetime
    IST  = pytz.timezone("Asia/Kolkata")
    now  = datetime.now(IST)
    d    = now.date()
    days = (3 - d.weekday()) % 7           # days to next Thursday (weekday 3)
    if days == 0 and (now.hour, now.minute) >= (15, 30):
        days = 7                            # past market close → next week
    return (d + timedelta(days=days)).strftime("%d%b%y").upper()

if __name__ == "__main__":
    print(f"Key: {OPENALGO_KEY[:8]}... | Expiry: {get_next_expiry()}")
    print(f"Log: {LOG_FILE} | State: {STATE_FILE} | History: {TRADE_HISTORY}")
