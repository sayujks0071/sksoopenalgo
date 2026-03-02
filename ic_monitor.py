#!/usr/bin/env python3
"""
NIFTY Iron Condor Live Monitor v3 — Dynamic Session + Rolling + Metrics
Overhaul after 24-FEB-2026: fully adaptive IC detection, sizing, exits, and rolls.

Key improvements (v2):
  - Dynamic IC structure detection from positionbook (no hardcoded strikes)
  - compute_wave_lots(): margin + VIX + gap-based sizing
  - check_dynamic_exit(): 5 exit conditions (premium%, proximity, trailing, VIX, SL tighten)
  - close_all_ic(): uses actual position symbols — no leg_map, no hardcoded strikes
  - OpenAlgo only for positions (no direct Dhan calls) — DNS failures do not affect monitor
  - PID file guard against duplicate monitor processes
  - 60s intervals day / 30s intervals gamma hour (2-3:10 PM)
  - SELL legs placed first in wave entries — prevents RMS rejection

New in v3:
  - roll_side(): NIFTY in 80–60pt zone + <40% captured → roll to ATM±150 instead of closing
  - compute_session_metrics(): auto-logs pnl, pct_captured, MAE, rolls to trade_history.jsonl
  - MAE tracking: state["mae"] = lowest MTM seen (most adverse excursion)
  - ROLL_ZONE = 80: new exit condition (wider than GAMMA_ZONE_PARTIAL=60)
  - 5 new state keys: ce_rolled, pe_rolled, mae, adjustments, regime_at_entry
"""
import time, json, requests, sys, os, signal, re, socket, atexit, glob
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

# ─── PERSISTENT HTTP SESSION (connection reuse to localhost:5002) ─────────────
_http = requests.Session()
_http.headers.update({"Content-Type": "application/json"})
atexit.register(lambda: _http.close())  # 2.2: ensure cleanup on exit

# ─── IC CONFIG (single source of truth) ──────────────────────────────────────
sys.path.insert(0, "/Users/mac/openalgo")
from ic_config import (OPENALGO_KEY as _IC_KEY, OPENALGO_URL as _IC_URL,
                       LOT_SIZE as _IC_LOT, SPAN_PER_LOT as _IC_SPAN,
                       get_next_expiry as _get_expiry,
                       LOG_FILE as _CFG_LOG_FILE, STATE_FILE as _CFG_STATE_FILE,
                       PID_FILE as _CFG_PID_FILE, HEARTBEAT_FILE as _CFG_HEARTBEAT_FILE,
                       N8N_WEBHOOK as _CFG_N8N_WEBHOOK, TRADE_HISTORY as _CFG_TRADE_HISTORY,
                       EVENTS_LOG as _CFG_EVENTS_LOG,
                       HARD_CLOSE_TIME, PRE_CLOSE_TIME, AFTERNOON_CE_CLOSE,
                       WAVE2_TIME, WAVE3_TIME, WAVE2_MIN_MTM, WAVE3_MIN_MTM,
                       MAX_DAILY_LOSS, MAX_LOTS_HARD_CAP, MIN_LOTS,
                       PREMIUM_CLOSE_PCT, PREMIUM_CLOSE_AFTER, PREMIUM_CLOSE_PROX,
                       ROLL_ZONE, GAMMA_ZONE_PARTIAL, GAMMA_ZONE_FULL,
                       TRAIL_LOCK_THRESHOLD, TRAIL_LOCK_PCT, VIX_SPIKE_TRIGGER,
                       PREMIUM_STOP_MULTIPLE,
                       PER_LEG_SL_INITIAL, PER_LEG_SL_AFTER_60, PER_LEG_SL_AFTER_2PM,
                       PER_LEG_SL_PORTFOLIO_GUARD,
                       MIN_ENTRY_DISTANCE, WIDEN_SHORT_OFFSET,
                       build_option_symbol)

# ─── CORE CONFIG (all imported from ic_config — single source of truth) ──────
IST            = pytz.timezone("Asia/Kolkata")
OPENALGO_URL   = _IC_URL
OPENALGO_KEY   = _IC_KEY
# All broker interaction uses OpenAlgo (localhost:5002) exclusively.
# Direct Dhan API calls are prohibited — see MEMORY.md F1-F7.
LOG_FILE         = _CFG_LOG_FILE
PID_FILE         = _CFG_PID_FILE
N8N_WEBHOOK_URL  = _CFG_N8N_WEBHOOK
HEARTBEAT_FILE   = _CFG_HEARTBEAT_FILE
EVENTS_LOG       = _CFG_EVENTS_LOG

# Sizing aliases
SPAN_PER_SPREAD_LOT = _IC_SPAN
LOT_SIZE            = _IC_LOT

# ─── STATE MACHINE ───────────────────────────────────────────────────────────
state = {
    "ic": {},               # populated by detect_ic_from_positions() at startup
    "peak_mtm": 0.0,        # highest MTM seen this session
    "entry_premium": 0.0,   # net credit received (updates after each wave)
    "pct_captured": 0.0,    # mtm / entry_premium
    "wave2_done": False,
    "wave3_done": False,
    "ce_closed": False,
    "pe_closed": False,
    "closed": False,
    "vix_entry": 0.0,       # India VIX at session start
    "current_vix": 0.0,     # latest VIX reading
    "nifty_entry": 0.0,     # NIFTY at Wave 1 entry
    "entry_time": None,
    "alerts_sent": set(),   # dedup: log each alert key only once
    "expiry": _get_expiry(),   # auto-computed from ic_config — no manual weekly update needed
    # ── v3 additions ─────────────────────────────────────────────────────────
    "ce_rolled": False,     # True after CE side has been rolled once this session
    "pe_rolled": False,     # True after PE side has been rolled once this session
    "mae": 0.0,             # Most Adverse Excursion: lowest MTM seen (≤0)
    "adjustments": 0,       # Count of rolls executed this session
    "regime_at_entry": "",  # Market regime at IC entry (set by ic_pre_entry.py or auto)
    "start_ts": None,       # time.time() at session start (for duration calc)
    "last_exit_reason": "", # reason stored before every break (for metrics log)
    "cumulative_entry_premium": 0.0,  # 1.8: sum of all wave/roll premiums (never replaced, only added)
    "premium_unreliable_until": 0.0,  # epoch: block premium-capture exits until this time (when entry_premium was estimated)
    # ── n8n notification cache (updated each monitor loop iteration) ──────────
    "last_nifty": 0.0,
    "last_mtm":   0.0,
    "last_dce":   0,
    # ── infrastructure health tracking ────────────────────────────────────────
    "consec_failures": 0,   # consecutive iterations where get_positions() returned {}
    "infra_retry_count": 0, # times consec_failures has reset (Fix A — retry instead of abort)
}


# ─── LOGGING (with auto-rotation) ────────────────────────────────────────────
_LOG_MAX_LINES = 5000   # rotate when log exceeds this
_log_counter   = 0      # lines written this session

def log(msg, level="INFO"):
    global _log_counter
    now  = datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{now}] {level:8s} | {msg}"
    print(line, flush=True)
    # 1.1: Only write to file explicitly when stdout is a TTY (interactive mode).
    # When launched via nohup/launchd, stdout is already redirected to LOG_FILE.
    if os.isatty(1):
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    _log_counter += 1
    # Auto-rotate every 500 lines written (check file size periodically)
    if _log_counter % 500 == 0:
        try:
            sz = os.path.getsize(LOG_FILE)
            if sz > 500_000:  # >500KB → trim to last 2000 lines
                with open(LOG_FILE, "r") as f:
                    lines = f.readlines()
                if len(lines) > _LOG_MAX_LINES:
                    with open(LOG_FILE, "w") as f:
                        f.writelines(lines[-2000:])
        except Exception:
            pass


def alert_once(key, msg, level="WARN"):
    """Log a message only once per session (dedup by key)."""
    if key not in state["alerts_sent"]:
        log(msg, level)
        state["alerts_sent"].add(key)


# ─── STATE PERSISTENCE (G7 — survive monitor restarts) ───────────────────────
_STATE_FILE = _CFG_STATE_FILE


def save_wave_state():
    """Persist wave entry flags so a monitor restart doesn't duplicate or skip waves."""
    import json as _j
    try:
        rec = {
            "date":        datetime.now(IST).strftime("%Y-%m-%d"),
            "wave2_done":  state.get("wave2_done", False),
            "wave3_done":  state.get("wave3_done", False),
            "ce_closed":   state.get("ce_closed", False),
            "pe_closed":   state.get("pe_closed", False),
            "ce_rolled":   state.get("ce_rolled", False),
            "pe_rolled":   state.get("pe_rolled", False),
            "closed":      state.get("closed", False),
            "adjustments": state.get("adjustments", 0),
        }
        with open(_STATE_FILE, "w") as f:
            _j.dump(rec, f)
    except Exception as e:
        log(f"save_wave_state error: {e}", "WARN")


def load_wave_state():
    """On restart, reload today's wave flags to prevent duplicate or skipped wave entries."""
    import json as _j
    today = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with open(_STATE_FILE) as f:
            rec = _j.load(f)
        if rec.get("date") == today:
            for k in ("wave2_done", "wave3_done", "ce_closed", "pe_closed",
                      "ce_rolled", "pe_rolled", "closed", "adjustments"):
                if k in rec:
                    state[k] = rec[k]
            log(f"State restored from disk: wave2={state['wave2_done']} "
                f"wave3={state['wave3_done']} closed={state['closed']}", "INIT")
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"load_wave_state error: {e}", "WARN")
    return False


def log_event(event: str, data: dict = None) -> None:
    """3.5: Append structured event to JSONL log for automated analysis."""
    try:
        rec = {
            "ts": datetime.now(IST).isoformat(),
            "event": event,
            "nifty": round(state.get("last_nifty", 0), 1),
            "mtm": round(state.get("last_mtm", 0), 0),
        }
        if data:
            rec.update(data)
        with open(EVENTS_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def approx_net_delta(ic: dict, nifty: float, lots: int) -> float:
    """3.6: Quick delta approximation per leg. No scipy needed — linear proxy.
    Returns net delta per lot. Alert if |net_delta| > 0.3.
    """
    if not ic or nifty <= 0 or lots <= 0:
        return 0.0
    net = 0.0
    for leg in ic.get("shorts", []):
        strike = leg.get("strike", 0)
        if strike <= 0:
            continue
        moneyness = (nifty - strike) / nifty  # +ve = ITM for CE
        if "CE" in leg.get("sym", ""):
            d = max(0.0, min(1.0, 0.5 + moneyness * 5))  # rough CE delta
            net -= d  # short CE → negative delta
        else:
            d = max(-1.0, min(0.0, -0.5 + moneyness * 5))  # rough PE delta
            net -= d  # short PE → positive delta
    for leg in ic.get("longs", []):
        strike = leg.get("strike", 0)
        if strike <= 0:
            continue
        moneyness = (nifty - strike) / nifty
        if "CE" in leg.get("sym", ""):
            d = max(0.0, min(1.0, 0.5 + moneyness * 5))
            net += d
        else:
            d = max(-1.0, min(0.0, -0.5 + moneyness * 5))
            net += d
    return round(net / lots if lots > 0 else net, 3)


def write_heartbeat(nifty: float = 0.0, mtm: float = 0.0, extra: dict = None):
    """2.3: Write heartbeat JSON each loop iteration. External health checks read this."""
    try:
        hb = {
            "pid":       os.getpid(),
            "timestamp": datetime.now(IST).isoformat(),
            "epoch":     time.time(),
            "nifty":     round(nifty, 1),
            "mtm":       round(mtm, 0),
            "closed":    state.get("closed", False),
            "iteration": 0,
        }
        if extra:
            hb.update(extra)
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump(hb, f)
    except Exception:
        pass  # never crash the monitor for heartbeat writes


# 3.7: Alert escalation — severity mapping
_ALERT_SEVERITY = {
    "SESSION_START": "INFO", "MONITOR": "INFO", "SESSION_END": "INFO",
    "WAVE_FAIL": "WARNING", "ROLL_CE": "WARNING", "ROLL_PE": "WARNING",
    "EXIT_ALL": "WARNING", "EXIT_CE": "WARNING", "EXIT_PE": "WARNING",
    "INFRA_DOWN": "CRITICAL", "COMP_FAIL": "CRITICAL", "ROLL_SELL_FAIL": "CRITICAL",
    "HEDGE_CRITICAL": "EMERGENCY", "EMERGENCY_CLOSE_FAIL": "EMERGENCY",
    "MONITOR_SHUTDOWN": "CRITICAL",
}


def notify_n8n(event: str, extra: dict = None):
    """
    Fire-and-forget webhook to n8n for real-time trading alerts.
    Called on key events: EXIT, ROLL_CE, ROLL_PE, PROFIT_TARGET, HARD_STOP, SESSION_START, MONITOR.
    Non-blocking (timeout=4s); failure is logged but NEVER crashes the monitor.
    3.7: Includes severity level for alert escalation on n8n side.
    """
    try:
        payload = {
            "event":        event,
            "severity":     _ALERT_SEVERITY.get(event, "INFO"),
            "nifty":        round(state.get("last_nifty", 0), 1),
            "mtm":          f"{state.get('last_mtm', 0):+.0f}",
            "pct_captured": f"{state.get('pct_captured', 0)*100:.1f}",
            "reason":       state.get("last_exit_reason", ""),
            "time":         datetime.now(IST).strftime("%H:%M IST"),
            "dce":          state.get("last_dce", 0),
            "peak_mtm":     f"{state.get('peak_mtm', 0):+.0f}",
            "ce_rolled":    state.get("ce_rolled", False),
            "pe_rolled":    state.get("pe_rolled", False),
        }
        if extra:
            payload.update(extra)
        _http.post(N8N_WEBHOOK_URL, json=payload, timeout=4)
    except Exception:
        pass   # never crash the monitor for notification failures


# ─── TIME HELPERS ─────────────────────────────────────────────────────────────
def ist_now():
    return datetime.now(IST)


def ist_hm():
    n = ist_now()
    return (n.hour, n.minute)


# ─── SYMBOL HELPERS ──────────────────────────────────────────────────────────
def normalize_sym(sym):
    """Uppercase + strip hyphens/spaces — handles both OA and Dhan formats."""
    return sym.upper().replace("-", "").replace(" ", "")


def extract_strike(sym):
    """Extract numeric strike price from option symbol.

    OpenAlgo format:  NIFTY05MAR2625500CE → strips NIFTY + month + CE/PE → '052625500' → last 5 = 25500
    Dhan format:      NIFTY-Mar2026-25500-CE → after normalize same path → 25500

    The year digits (e.g. '26') immediately precede the strike, so we strip prefix/suffix
    and take the last 4 or 5 digits which represent the strike price.
    """
    s = normalize_sym(sym)
    # Remove NIFTY prefix
    s = s.replace("NIFTY", "")
    # Remove month abbreviations (leaves day + year + strike digits)
    for mo in ("JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"):
        s = s.replace(mo, "")
    # Remove CE/PE suffix
    if s.endswith("CE"):
        s = s[:-2]
    elif s.endswith("PE"):
        s = s[:-2]
    # Remaining string is pure digits: DDYY + STRIKE, e.g. "052625500"
    # Strike is last 5 digits (NIFTY 20K–30K range), fallback last 4
    for n in (5, 4):
        if len(s) >= n:
            candidate = s[-n:]
            if candidate.isdigit():
                v = int(candidate)
                if 15000 <= v <= 35000:
                    return v
    return 0


def extract_expiry_from_sym(sym):
    """Extract DDMMMYY expiry string from OpenAlgo symbol.
    NIFTY05MAR2625500CE → 05MAR26
    Returns None if not detected (e.g. Dhan format).
    """
    s = normalize_sym(sym).replace("NIFTY", "")
    m = re.match(r'^(\d{2}[A-Z]{3}\d{2})', s)
    return m.group(1) if m else None


def get_opt_type(sym):
    """Return 'CE', 'PE', or '' from symbol."""
    s = normalize_sym(sym)
    if s.endswith("CE"):
        return "CE"
    if s.endswith("PE"):
        return "PE"
    return ""


def is_option_sym(sym):
    t = get_opt_type(sym)
    return t in ("CE", "PE")


# ─── INFRASTRUCTURE HEALTH CHECK ─────────────────────────────────────────────
INFRA_FAIL_LIMIT = 5   # consecutive OpenAlgo failures before monitor exits


def check_infrastructure():
    """Fail-fast check before monitor loop starts.
    Tests OpenAlgo on 127.0.0.1:5002 — exits immediately if down.
    Does NOT call api.dhan.co (DNS failures are not our problem to retry).
    """
    log("Pre-flight: checking OpenAlgo health at 127.0.0.1:5002 ...", "INIT")
    try:
        r = _http.post(
            f"{OPENALGO_URL}/funds",
            json={"apikey": OPENALGO_KEY},
            timeout=5
        )
        if r.status_code == 200:
            log("Pre-flight: OpenAlgo OK", "INIT")
            return True
        else:
            log(f"Pre-flight: OpenAlgo returned HTTP {r.status_code}", "ERROR")
    except requests.exceptions.ConnectionError:
        log("Pre-flight: OpenAlgo is DOWN — port 5002 not reachable", "ERROR")
    except requests.exceptions.Timeout:
        log("Pre-flight: OpenAlgo timed out (>5s) — server overloaded or frozen", "ERROR")
    except Exception as e:
        log(f"Pre-flight: OpenAlgo check failed: {e}", "ERROR")

    notify_n8n("INFRA_DOWN", {"detail": "OpenAlgo 5002 unreachable at monitor startup"})
    log("ABORTING: Fix OpenAlgo first, then restart ic_monitor.py", "ERROR")
    return False


# ─── API HELPERS ─────────────────────────────────────────────────────────────
def api_post(endpoint, data, timeout=8):
    try:
        r = _http.post(
            f"{OPENALGO_URL}/{endpoint}",
            json={**data, "apikey": OPENALGO_KEY},
            timeout=timeout
        )
        return r.json()
    except Exception as e:
        log(f"API error [{endpoint}]: {e}", "ERROR")
        return {}


def api_post_retry(endpoint, data, n=3, backoff=1.5, timeout=8):
    """api_post with up to n retries on timeout/connection error. BUG4 fix."""
    for attempt in range(n):
        try:
            r = _http.post(
                f"{OPENALGO_URL}/{endpoint}",
                json={**data, "apikey": OPENALGO_KEY},
                timeout=timeout
            )
            return r.json()
        except requests.exceptions.Timeout:
            if attempt < n - 1:
                log(f"API timeout [{endpoint}] attempt {attempt+1}/{n} — retry in {backoff}s", "WARN")
                time.sleep(backoff)
            else:
                log(f"API error [{endpoint}]: Timeout after {n} attempts", "ERROR")
        except Exception as e:
            log(f"API error [{endpoint}]: {e}", "ERROR")
            return {}
    return {}


def get_positions():
    """Fetch live positions via OpenAlgo positionbook (localhost only — no direct Dhan calls).
    Returns dict: {symbol: {qty, avg, ltp, mtm, sym}}
    Returns {} on failure — caller handles empty dict gracefully.
    BUG4 fix: retries 2× on timeout before giving up.
    """
    try:
        resp = api_post_retry("positionbook", {}, n=2, backoff=1.0, timeout=8)
        data = resp.get("data", [])
        if data is not None:
            pos = {}
            for p in data:
                sym = p.get("symbol", "")
                qty = int(p.get("quantity", 0))
                avg = float(p.get("average_price", 0) or 0)
                ltp = float(p.get("ltp", 0) or 0)
                mtm = (ltp - avg) * qty if ltp > 0 else float(p.get("pnl", 0) or 0)
                pos[sym] = {"qty": qty, "avg": avg, "ltp": ltp, "mtm": mtm, "sym": sym}
            return pos
    except Exception as e:
        log(f"OpenAlgo positionbook error: {e}", "ERROR")
    return {}


def enrich_ltps_from_quotes(positions):
    """Fetch live LTP via quotes API for any option position where ltp==0.

    Root cause fix (25-FEB-2026): OpenAlgo positionbook and Dhan positions API
    both return lastTradedPrice=0 for option positions. Without real LTPs,
    MTM=0 always → pct_captured=0 → ROLL_ZONE fires perpetually.

    2.7: Parallel fetches with ThreadPoolExecutor (4 legs in ~1s vs 4s sequential).
    """
    need_ltp = [(sym, p) for sym, p in positions.items()
                if p["qty"] != 0 and is_option_sym(sym) and p.get("ltp", 0) <= 0]
    if not need_ltp:
        return 0

    def _fetch_ltp(sym):
        try:
            # BUG4 fix: retry once on timeout
            r   = api_post_retry("quotes", {"symbol": sym, "exchange": "NFO"},
                                 n=2, backoff=1.0, timeout=4)
            ltp = float(r.get("data", {}).get("ltp", 0) or 0)
            return sym, ltp
        except Exception as e:
            log(f"LTP enrich error [{sym}]: {e}", "WARN")
            return sym, 0.0

    updated = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_ltp, sym): (sym, p) for sym, p in need_ltp}
        try:
            for fut in as_completed(futures, timeout=8):
                try:
                    sym, ltp = fut.result(timeout=2)
                    if ltp > 0:
                        p = positions[sym]
                        p["ltp"] = ltp
                        p["mtm"] = (ltp - p["avg"]) * p["qty"]
                        updated += 1
                except Exception:
                    pass
        except TimeoutError:
            # Some futures didn't complete in time — collect what we have
            for fut, (sym, p_) in futures.items():
                if fut.done():
                    try:
                        sym, ltp = fut.result()
                        if ltp > 0:
                            p = positions[sym]
                            p["ltp"] = ltp
                            p["mtm"] = (ltp - p["avg"]) * p["qty"]
                            updated += 1
                    except Exception:
                        pass
    return updated


def _seed_entry_premium_from_chain(ic: dict, expiry: str) -> float:
    """Fallback: if positionbook avg prices are all 0 (Dhan intraday lag),
    reconstruct entry_premium from current option chain LTPs.

    Called at monitor startup when ic['entry_premium'] <= 1.0.
    Uses live LTPs as a conservative proxy for entry prices (they're close
    to fill prices for freshly opened positions).

    BUG4 fix: uses api_post_retry (3 attempts) instead of single api_post.
    Returns the seeded entry_premium (float > 0), or 1.0 on failure.
    """
    try:
        r = api_post_retry("optionchain", {
            "underlying": "NIFTY", "exchange": "NFO",
            "expiry_date": expiry
        }, n=3, backoff=3.0, timeout=8)
        chain = r.get("chain", [])
        if not chain:
            return 1.0

        # Build strike → {ce_ltp, pe_ltp} lookup
        ltp_map: dict = {}
        for item in chain:
            try:
                strike = int(item.get("strike", 0))
                ce_ltp = float(item.get("ce", {}).get("ltp", 0) or 0)
                pe_ltp = float(item.get("pe", {}).get("ltp", 0) or 0)
                ltp_map[strike] = {"CE": ce_ltp, "PE": pe_ltp}
            except Exception:
                continue

        short_credit = 0.0
        long_debit   = 0.0

        for s in ic.get("shorts", []):
            strike   = s["strike"]
            opt_type = s["type"]  # "CE" or "PE"
            qty      = abs(s["qty"])
            ltp      = ltp_map.get(strike, {}).get(opt_type, 0.0)
            short_credit += qty * ltp

        for l in ic.get("longs", []):
            strike   = l["strike"]
            opt_type = l["type"]
            qty      = abs(l["qty"])
            ltp      = ltp_map.get(strike, {}).get(opt_type, 0.0)
            long_debit += qty * ltp

        seeded = short_credit - long_debit
        if seeded > 0:
            log(f"Entry premium seeded from chain LTPs: "
                f"credit=₹{short_credit:,.0f}  debit=₹{long_debit:,.0f}  "
                f"net=₹{seeded:,.0f} (positionbook avg was 0)", "INIT")
            return seeded

        # Net debit spread (e.g. bear put spread) — use absolute premium received
        # Fall back to short-leg credit only so pct_captured is meaningful
        fallback = max(short_credit, 1.0)
        log(f"Entry premium seeded from short LTPs only (net debit): ₹{fallback:,.0f}", "INIT")
        return fallback

    except Exception as e:
        log(f"_seed_entry_premium_from_chain failed: {e}", "WARN")
        return 1.0


def _ensure_entry_premium(ic: dict, label: str = "") -> float:
    """BUG1+BUG2 fix: guarantee ic['entry_premium'] is meaningful (> 1.0).

    Strategy:
      1. Already valid (> 1.0) → return immediately.
      2. Try seeding from live option chain LTPs (3 retries inside _seed_entry_premium_from_chain).
      3. Last resort: estimate from total short qty × ₹50/contract.
         Sets state['premium_unreliable_until'] = now+5min to block
         premium-capture exits while the estimate is in use.

    Called at startup AND after every IC refresh (post-roll, post-wave).
    """
    if ic["entry_premium"] > 1.0:
        return ic["entry_premium"]

    expiry = state.get("expiry", "")
    seeded = _seed_entry_premium_from_chain(ic, expiry)
    if seeded > 1.0:
        ic["entry_premium"] = seeded
        log(f"Entry premium verified from chain: ₹{seeded:,.0f} {label}", "INIT")
        return seeded

    # All chain attempts failed — use conservative floor and block premium exits
    total_short_qty = sum(abs(s["qty"]) for s in ic.get("shorts", []))
    fallback = max(total_short_qty * 50, 1_000)   # ₹50/contract floor
    ic["entry_premium"] = fallback
    block_until = time.time() + 300   # 5 minutes
    state["premium_unreliable_until"] = block_until
    log(
        f"⚠️  Entry premium ESTIMATED at ₹{fallback:,.0f} "
        f"({total_short_qty} contracts × ₹50) — chain unavailable {label}. "
        f"Premium exits blocked for 5 min.",
        "WARN"
    )
    return fallback


_nifty_cache    = 0.0   # last-known NIFTY — returned when optionchain times out
_nifty_cache_ts = 0.0   # epoch of last successful NIFTY fetch
_vix_cache      = 0.0   # last-known VIX
_vix_cache_ts   = 0.0   # epoch of last successful VIX fetch
_CACHE_TTL      = 300   # 5 minutes — stale after this


def get_nifty_and_vix():
    """Fetch NIFTY LTP and India VIX.
    NIFTY: via OpenAlgo option chain (underlying_ltp).
    VIX:   via OpenAlgo /quotes endpoint with symbol=INDIAVIX, exchange=NSE_INDEX.
           The previous approach (optionchain for INDIAVIX) always returned 0 because
           INDIAVIX has no option chain — this was the root cause of VIX=0 in all sessions.
    Returns (nifty_ltp: float, vix: float).
    On timeout/failure, returns cached values if < 5 min old, else 0.0.
    """
    global _nifty_cache, _nifty_cache_ts, _vix_cache, _vix_cache_ts
    expiry = state["expiry"]

    # ── NIFTY LTP via option chain ───────────────────────────────────────────
    try:
        r = api_post_retry("optionchain", {
            "underlying": "NIFTY", "exchange": "NSE_INDEX",
            "expiry_date": expiry, "strike_count": 4
        }, n=2, backoff=1.0, timeout=5)
        v = float(r.get("underlying_ltp", 0) or 0)
        if v > 0:
            _nifty_cache    = v
            _nifty_cache_ts = time.time()
    except Exception as e:
        log(f"NIFTY LTP error (using cached {_nifty_cache:.0f}): {e}", "WARN")

    # ── India VIX via /quotes (FIX: optionchain never worked for INDIAVIX) ───
    # INDIAVIX is an index — it has no option chain. The quotes endpoint returns
    # the live LTP of the index itself.
    try:
        rv = api_post_retry("quotes", {
            "symbol": "INDIAVIX", "exchange": "NSE_INDEX"
        }, n=2, backoff=1.0, timeout=5)
        # Try both response shapes: {data: {ltp: ...}} and {ltp: ...}
        vix_raw = (rv.get("data") or rv) if isinstance(rv, dict) else {}
        v = float(vix_raw.get("ltp", 0) or vix_raw.get("last_price", 0) or 0)
        if v > 0:
            _vix_cache    = v
            _vix_cache_ts = time.time()
    except Exception as e:
        log(f"VIX quote error (cached={_vix_cache:.2f}): {e}", "WARN")

    # 1.9: Return 0.0 if cache is stale (> 5 min)
    now_ts = time.time()
    nifty  = _nifty_cache if (now_ts - _nifty_cache_ts < _CACHE_TTL) else 0.0
    vix    = _vix_cache   if (now_ts - _vix_cache_ts   < _CACHE_TTL) else 0.0
    return nifty, vix


def get_available_margin():
    """Fetch available cash from OpenAlgo funds endpoint."""
    try:
        r = api_post("funds", {})
        return float(r.get("data", {}).get("availablecash", 0) or 0)
    except Exception as e:
        log(f"Funds error: {e}", "WARN")
        return 0.0


def place_order(symbol, action, qty, strategy="IC_MONITOR"):
    """Place a market order via OpenAlgo."""
    resp = api_post("placeorder", {
        "strategy": strategy, "symbol": symbol, "action": action,
        "exchange": "NFO", "pricetype": "MARKET",
        "product": "MIS", "quantity": str(qty)
    })
    ok  = resp.get("status") == "success"
    oid = resp.get("orderid", "?")
    log(
        f"ORDER: {action} {symbol} {qty} → {'✅ ' + oid if ok else '❌ ' + str(resp)}",
        "TRADE" if ok else "ERROR"
    )
    return ok


def verify_fill_in_tradebook(symbol: str, action: str, qty: int,
                             timeout: int = 30, placed_after: float = None) -> bool:
    """
    Poll OpenAlgo tradebook every 5s to confirm a fill.
    1.5: If placed_after (epoch) is set, skip trades with older timestamps.
    Returns True if a trade for symbol+action with qty >= qty is found within timeout.
    Uses 127.0.0.1:5002 only — no direct Dhan calls.
    """
    sym_n    = symbol.upper().replace(" ", "").replace("-", "")
    action_u = action.upper()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            trades = api_post("tradebook", {}).get("data", []) or []
            for t in trades:
                if (str(t.get("symbol","")).upper().replace(" ","").replace("-","") == sym_n
                        and str(t.get("action","")).upper() == action_u
                        and int(t.get("quantity", 0)) >= qty):
                    # 1.5: Timestamp filter
                    if placed_after and t.get("updatetime"):
                        try:
                            ts_str = str(t["updatetime"]).strip()
                            if len(ts_str) <= 8:  # "HH:MM:SS"
                                from datetime import date as _date
                                parts = ts_str.split(":")
                                td = datetime(_date.today().year, _date.today().month,
                                              _date.today().day,
                                              int(parts[0]), int(parts[1]), int(parts[2]))
                                trade_epoch = td.timestamp()
                            else:
                                trade_epoch = datetime.strptime(
                                    ts_str[:19], "%Y-%m-%d %H:%M:%S").timestamp()
                            if trade_epoch < placed_after - 10:
                                continue  # stale fill
                        except Exception:
                            pass  # accept match if parsing fails
                    return True
        except Exception as e:
            log(f"verify_fill [{symbol} {action}]: {e}", "WARN")
        time.sleep(5)
    return False


def verify_sell_fill(symbol: str, qty: int, timeout: int = 30,
                     placed_after: float = None) -> bool:
    """Convenience wrapper for SELL fill verification."""
    return verify_fill_in_tradebook(symbol, "SELL", qty, timeout, placed_after)


# ─── DYNAMIC IC DETECTION ─────────────────────────────────────────────────────
def detect_ic_from_positions(positions: dict) -> dict | None:
    """Scan positionbook and auto-build IC structure dict from actual fills.
    Works for any IC — no hardcoded strikes or lot sizes.
    Returns IC dict, or None if no open IC detected.
    """
    shorts = []
    longs  = []

    for sym, p in positions.items():
        if p["qty"] == 0:
            continue
        if not is_option_sym(sym):
            continue
        strike   = extract_strike(sym)
        opt_type = get_opt_type(sym)
        if strike == 0:
            continue

        rec = {
            "sym":    sym,
            "qty":    p["qty"],
            "avg":    p["avg"],
            "ltp":    p["ltp"],
            "strike": strike,
            "type":   opt_type,
        }
        if p["qty"] < 0:
            rec["sl_price"] = p["avg"] * 2.0   # initial 2x SL
            shorts.append(rec)
        else:
            longs.append(rec)

    if not shorts:
        return None   # no shorts = no IC (also catches longs-only residual after close)

    # ── Longs-only guard: if there are shorts but they're heavily dominated by longs,
    # this is likely residual wing positions from a just-closed IC. Refuse to create IC.
    total_short_qty = sum(abs(s["qty"]) for s in shorts)
    total_long_qty  = sum(abs(l["qty"]) for l in longs)
    if total_long_qty > total_short_qty * 2.5:
        log(f"detect_ic: longs ({total_long_qty}) >> shorts ({total_short_qty}) — "
            f"residual wings from closed IC? Refusing IC detection.", "WARN")
        return None

    # Net credit received: sum(short_premium) - sum(long_premium)
    entry_premium = (
        sum(abs(s["qty"]) * s["avg"] for s in shorts) -
        sum(l["qty"] * l["avg"] for l in longs)
    )

    # Identify key strikes and barriers
    pe_shorts = [s for s in shorts if s["type"] == "PE"]
    ce_shorts = [s for s in shorts if s["type"] == "CE"]
    pe_longs  = [l for l in longs  if l["type"] == "PE"]
    ce_longs  = [l for l in longs  if l["type"] == "CE"]

    short_pe = min((s["strike"] for s in pe_shorts), default=0)
    short_ce = max((s["strike"] for s in ce_shorts), default=0)
    long_pe  = min((l["strike"] for l in pe_longs),  default=0)
    long_ce  = max((l["strike"] for l in ce_longs),  default=0)

    # ── Imbalance detection: alert if CE/PE short qty differs by > 1.5× ─────
    ce_short_qty = sum(abs(s["qty"]) for s in ce_shorts)
    pe_short_qty = sum(abs(s["qty"]) for s in pe_shorts)
    _imbalance_ratio = max(ce_short_qty, pe_short_qty) / max(min(ce_short_qty, pe_short_qty), 1)
    if _imbalance_ratio > 1.5:
        log(
            f"⚠️  IC IMBALANCE: CE_short_qty={ce_short_qty} vs PE_short_qty={pe_short_qty} "
            f"(ratio={_imbalance_ratio:.1f}x) — directional delta exposure! "
            f"This often happens when residual positions from a prior session mix with new entries.",
            "WARN"
        )

    # Auto-detect expiry from first short's symbol (OpenAlgo format)
    for s in shorts:
        exp = extract_expiry_from_sym(s["sym"])
        if exp:
            state["expiry"] = exp
            break

    ic = {
        "shorts":              shorts,
        "longs":               longs,
        "pe_shorts":           pe_shorts,
        "ce_shorts":           ce_shorts,
        "pe_longs":            pe_longs,
        "ce_longs":            ce_longs,
        "entry_premium":       max(entry_premium, 1.0),  # avoid zero-division
        "short_pe_strike":     short_pe,
        "short_ce_strike":     short_ce,
        "nifty_lower_barrier": (long_pe - 50) if long_pe > 0 else 0,
        "nifty_upper_barrier": (long_ce + 50) if long_ce > 0 else 0,
    }

    # Fix A: Positions are truth — override stale state flags.
    # If we can physically see live shorts in positionbook, the side is NOT closed
    # regardless of what state (loaded from previous session) claims.
    if ce_shorts and state.get("ce_closed"):
        log("State reconcile: ce_closed=True but CE shorts live in positionbook → resetting to False", "WARN")
        state["ce_closed"] = False
    if pe_shorts and state.get("pe_closed"):
        log("State reconcile: pe_closed=True but PE shorts live in positionbook → resetting to False", "WARN")
        state["pe_closed"] = False

    return ic


# ─── DYNAMIC POSITION SIZING ─────────────────────────────────────────────────
def compute_wave_lots(wave_num, avail_margin, vix=14.0, gap_pct=0.0, session_mtm=0):
    """Compute recommended lot count for a given wave.

    Factors:
      - Available margin (78% utilisation rule)
      - VIX: ×0.5 if >20 (dangerous), ×0.75 if 16-20, ×1.0 if ≤16
      - Gap at open: ×0.70 if >1.5%, ×0.85 if 0.75-1.5%, ×1.0
      - Wave factor: W1=100%, W2=65%, W3=40% (successive waves smaller)

    Returns clamped int in [MIN_LOTS, MAX_LOTS_HARD_CAP].
    """
    if avail_margin <= 0:
        return MIN_LOTS

    base = int(avail_margin * 0.78 / SPAN_PER_SPREAD_LOT)

    vix_f  = 0.5  if vix       > 20   else (0.75 if vix       > 16   else 1.0)
    gap_f  = 0.70 if abs(gap_pct) > 1.5 else (0.85 if abs(gap_pct) > 0.75 else 1.0)
    wave_f = {1: 1.0, 2: 0.65, 3: 0.40}.get(wave_num, 0.40)

    lots = int(base * vix_f * gap_f * wave_f)
    return max(MIN_LOTS, min(MAX_LOTS_HARD_CAP, lots))


# ─── DYNAMIC EXIT CONDITIONS ─────────────────────────────────────────────────
def check_dynamic_exit(ic: dict, positions: dict, nifty: float, mtm: float, now: datetime) -> tuple[bool, str, str]:
    """Evaluate all 5 dynamic exit conditions.

    Returns (should_exit: bool, side: 'ALL'|'CE'|'PE', reason: str)
    side='ALL' → close full IC; side='CE'/'PE' → close that side only.
    """
    if not ic or state["closed"]:
        return False, "", ""

    hm           = (now.hour, now.minute)
    # 1.8: Use cumulative premium to survive rolls/waves
    entry_prem   = state.get("cumulative_entry_premium", 0.0)
    if entry_prem <= 0:
        entry_prem = ic.get("entry_premium", 1.0)
    pct_captured = min(5.0, max(-5.0, mtm / entry_prem if entry_prem > 0 else 0.0))
    short_pe     = ic.get("short_pe_strike", 0)
    short_ce     = ic.get("short_ce_strike", 0)
    peak         = state["peak_mtm"]

    state["pct_captured"] = pct_captured   # expose to status log

    # ── Condition 1: Premium capture milestones ──────────────────────────────
    # BUG3 fix: suppress premium exits when entry_premium was estimated (chain unavailable).
    # Gamma zone / SL / max-loss exits are NOT suppressed — safety always fires.
    _prem_blocked = time.time() < state.get("premium_unreliable_until", 0.0)
    if _prem_blocked:
        _rem_s = max(0, int(state["premium_unreliable_until"] - time.time()))
        alert_once(
            "prem_blocked",
            f"⚠️  Premium exits suppressed ({_rem_s}s remaining) — entry_premium was estimated, not chain-verified",
            "WARN"
        )
    else:
        if pct_captured >= PREMIUM_CLOSE_PCT:
            return True, "ALL", f"Premium captured {pct_captured:.1%} ≥ {PREMIUM_CLOSE_PCT:.0%}"

        if pct_captured >= PREMIUM_CLOSE_AFTER and hm >= (14, 0):
            return True, "ALL", f"Premium {pct_captured:.1%} ≥ {PREMIUM_CLOSE_AFTER:.0%} after 2PM"

        if pct_captured >= PREMIUM_CLOSE_PROX and nifty > 0:
            if short_pe and abs(nifty - short_pe) < 50:
                return True, "ALL", (
                    f"Premium {pct_captured:.1%} + NIFTY {nifty:.0f} near short PE {short_pe}")
            if short_ce and abs(nifty - short_ce) < 50:
                return True, "ALL", (
                    f"Premium {pct_captured:.1%} + NIFTY {nifty:.0f} near short CE {short_ce}")

    # ── Condition 1.5: Roll zone — side threatened but not yet at gamma ─────
    # Only roll if pct_captured < 40% (still early enough to benefit from roll)
    # and the side has NOT been rolled already this session (roll once per side)
    # Grace period: skip roll check for first 15 min (avoids false trigger at session open
    # when MTM=0 because LTPs haven't settled and NIFTY may be naturally close to short)
    _session_age_min = (time.time() - state["start_ts"]) / 60 if state.get("start_ts") else 999
    # 3.4: Check time to expiry — close instead of roll if < 4 hours remain
    _hours_to_close = ((15 * 60 + 30) - (now.hour * 60 + now.minute)) / 60.0
    _allow_roll = _hours_to_close >= 4.0  # don't roll if <4h to expiry — theta too fast

    if nifty > 0 and _session_age_min >= 15:
        if short_ce > 0 and not state["ce_closed"] and not state["ce_rolled"]:
            dist_ce = short_ce - nifty
            if ROLL_ZONE >= dist_ce > GAMMA_ZONE_PARTIAL and pct_captured < 0.40:
                if _allow_roll:
                    return True, "ROLL_CE", (
                        f"Roll CE: dist={dist_ce:.0f}pt capt={pct_captured:.1%} "
                        f"NIFTY={nifty:.0f} shortCE={short_ce}")
                else:
                    return True, "CE", (
                        f"Close CE (no roll — {_hours_to_close:.1f}h to close): "
                        f"dist={dist_ce:.0f}pt NIFTY={nifty:.0f}")
        if short_pe > 0 and not state["pe_closed"] and not state["pe_rolled"]:
            dist_pe = nifty - short_pe
            if ROLL_ZONE >= dist_pe > GAMMA_ZONE_PARTIAL and pct_captured < 0.40:
                if _allow_roll:
                    return True, "ROLL_PE", (
                        f"Roll PE: dist={dist_pe:.0f}pt capt={pct_captured:.1%} "
                        f"NIFTY={nifty:.0f} shortPE={short_pe}")
                else:
                    return True, "PE", (
                        f"Close PE (no roll — {_hours_to_close:.1f}h to close): "
                        f"dist={dist_pe:.0f}pt NIFTY={nifty:.0f}")

    # ── Condition 2: Gamma danger zone ───────────────────────────────────────
    if nifty > 0:
        if short_ce > 0 and not state["ce_closed"]:
            dist_ce = short_ce - nifty
            if dist_ce <= GAMMA_ZONE_FULL:
                return True, "ALL", (
                    f"NIFTY {nifty:.0f} within {dist_ce:.0f}pt of short CE {short_ce} — EMERGENCY")
            if dist_ce <= GAMMA_ZONE_PARTIAL:
                return True, "CE", (
                    f"NIFTY {nifty:.0f} within {dist_ce:.0f}pt of short CE {short_ce} — close CE")

        if short_pe > 0 and not state["pe_closed"]:
            dist_pe = nifty - short_pe
            if dist_pe <= GAMMA_ZONE_FULL:
                return True, "ALL", (
                    f"NIFTY {nifty:.0f} within {dist_pe:.0f}pt of short PE {short_pe} — EMERGENCY")
            if dist_pe <= GAMMA_ZONE_PARTIAL:
                return True, "PE", (
                    f"NIFTY {nifty:.0f} within {dist_pe:.0f}pt of short PE {short_pe} — close PE")

    # ── Condition 3: Trailing profit lock ────────────────────────────────────
    if peak >= TRAIL_LOCK_THRESHOLD:
        floor = peak * TRAIL_LOCK_PCT
        if mtm < floor:
            return True, "ALL", (
                f"Trail lock: MTM {mtm:+,.0f} < floor {floor:,.0f} (peak={peak:,.0f})")

    # ── Condition 4: Per-leg SL with adaptive tightening ────────────────────
    # CRITICAL FIX (2026-03-02): The old 2.0x multiplier fired at MTM=-₹5,784 when
    # the portfolio SL (-₹25,872) was never hit. Per-leg SL must NOT fire before the
    # portfolio-level premium_stop_multiple. Use 3.0x initial (only extreme moves).
    # Portfolio guard: skip per-leg SL if overall MTM > -30% of entry credit.
    for s in ic.get("shorts", []):
        ltp = s.get("ltp", 0)
        # Fresh LTP from current positions if stale
        if ltp <= 0:
            for sym, p in positions.items():
                if normalize_sym(sym) == normalize_sym(s["sym"]):
                    ltp = p["ltp"]
                    s["ltp"] = ltp
                    break
        if ltp <= 0:
            continue

        if s.get("avg", 0) <= 0:
            continue   # skip legs with no avg price (shouldn't happen but guard anyway)

        # Portfolio guard: if overall MTM is still within acceptable range, don't fire per-leg SL.
        # This prevents per-leg SL from triggering when the IC is recovering or when
        # one leg moved but the spread is still healthy as a portfolio.
        if PER_LEG_SL_PORTFOLIO_GUARD and entry_prem > 0:
            portfolio_loss_pct = mtm / entry_prem  # negative when losing
            if portfolio_loss_pct > -0.30:          # less than 30% portfolio loss → skip per-leg SL
                continue

        # Adaptive SL multiplier (loosened vs prior 2.0x — per-leg is LAST RESORT)
        # pct_captured and hm already computed above
        sl_mult = PER_LEG_SL_INITIAL        # 3.0x by default
        if pct_captured >= 0.60:
            sl_mult = PER_LEG_SL_AFTER_60   # 2.5x after 60% captured
        if hm >= (14, 0):
            sl_mult = PER_LEG_SL_AFTER_2PM  # 2.0x after 2 PM

        sl_price = s["avg"] * sl_mult
        if ltp >= sl_price:
            return True, "ALL", (
                f"Short {s['sym'][-12:]} LTP {ltp:.2f} ≥ SL {sl_price:.2f} "
                f"({sl_mult}x avg {s['avg']:.2f}) [port_loss={portfolio_loss_pct:.1%}]")

    # ── Condition 5: India VIX spike (IV explosion = IC killer) ─────────────
    vix_e = state.get("vix_entry", 0)
    vix_c = state.get("current_vix", 0)
    if vix_e > 0 and vix_c > 0:
        vix_rise = (vix_c - vix_e) / vix_e
        if vix_rise >= VIX_SPIKE_TRIGGER:
            return True, "ALL", (
                f"VIX spike: {vix_c:.2f} vs entry {vix_e:.2f} (+{vix_rise:.1%})")

    # ── Condition 6: Absolute premium stop (tastytrade / Karen Supertrader) ──
    # Never lose more than PREMIUM_STOP_MULTIPLE × the credit collected.
    # Fires before capital-based stop — proportional to actual position risk.
    # Suppressed if premium_unreliable (chain unavailable) — avoids false fire.
    if not _prem_blocked and entry_prem > 0:
        prem_stop = -(entry_prem * PREMIUM_STOP_MULTIPLE)
        if mtm < prem_stop:
            return True, "ALL", (
                f"Premium stop: MTM {mtm:+,.0f} < -{PREMIUM_STOP_MULTIPLE:.0f}× "
                f"entry_premium {entry_prem:,.0f} = {prem_stop:,.0f}")

    # ── Max daily loss ────────────────────────────────────────────────────────
    if mtm < MAX_DAILY_LOSS:
        return True, "ALL", f"Max daily loss {mtm:+,.0f} < limit {MAX_DAILY_LOSS:,}"

    return False, "", ""


# ─── CLOSE FUNCTIONS ─────────────────────────────────────────────────────────
def close_all_ic(positions, reason="MANUAL"):
    """Close all open IC option positions using actual symbols from positionbook.
    No hardcoded strikes — reverses every non-zero CE/PE position.
    BUG6 fix: retries each failed order 2× with 1.5s backoff.
    """
    log(f"🔴 CLOSING ALL IC POSITIONS — {reason}", "TRADE")
    closed = 0
    tag = f"IC_CLOSE_{reason[:20].replace(' ', '_')}"

    for sym, p in positions.items():
        if p["qty"] == 0:
            continue
        if not is_option_sym(sym):
            continue   # skip equity/futures
        action = "BUY" if p["qty"] < 0 else "SELL"
        ok = place_order(sym, action, abs(p["qty"]), tag)
        if not ok:
            for _retry in range(2):  # retry up to 2× more (3 total)
                log(f"ORDER retry {_retry+1}/2: {action} {sym}", "WARN")
                time.sleep(1.5)
                ok = place_order(sym, action, abs(p["qty"]), tag)
                if ok:
                    break
        if ok:
            closed += 1
        time.sleep(0.5)

    state["closed"] = True
    log(f"Close complete: {closed} legs exited", "TRADE")
    save_wave_state()   # persist — G7
    return closed


def safe_close_all(positions, reason, allow_continue_until=None):
    """
    Close all IC positions, then verify positionbook is flat. (Fix B — F4)
    If residual positions remain AND we are before allow_continue_until:
      → reset state["closed"]=False, update state["ic"], return False (don't break)
    Otherwise → compute_session_metrics + return True (break)
    """
    close_all_ic(positions, reason)
    time.sleep(3)

    fresh    = get_positions()
    residual = {s: p for s, p in fresh.items()
                if p["qty"] != 0 and is_option_sym(s)}

    if not residual:
        log("Post-close verify: positionbook flat. ✅", "TRADE")
        return True   # all clear — caller should break

    hm = ist_hm()
    if allow_continue_until and hm >= allow_continue_until:
        log(f"Post-close verify: {len(residual)} residual legs but past "
            f"{allow_continue_until[0]}:{allow_continue_until[1]:02d} — accepting.", "WARN")
        return True

    # ── FIX (2026-03-02): Detect wings-only residual ─────────────────────────
    # After close_all_ic, Dhan positionbook sometimes lags by a few seconds, leaving
    # the LONG (wing) positions still showing. These are NOT a new IC — they're the
    # protection legs from the just-closed position. Previously the monitor would
    # continue tracking them, treating them as a new IC, causing phantom exits.
    # Fix: if residuals are ALL long positions (qty > 0), force-close them immediately.
    residual_shorts = {s: p for s, p in residual.items() if p["qty"] < 0}
    residual_longs  = {s: p for s, p in residual.items() if p["qty"] > 0}

    if not residual_shorts and residual_longs:
        log(
            f"Post-close: {len(residual_longs)} residual LONG (wing) positions — "
            f"likely Dhan positionbook lag. Force-closing wings now.", "WARN"
        )
        for sym, p in residual_longs.items():
            log(f"   Force-close: SELL {sym} qty={p['qty']}", "WARN")
            place_order(sym, "SELL", p["qty"], "IC_WING_CLEANUP")
            time.sleep(0.4)
        # Final verify after wing cleanup
        time.sleep(3)
        final = {s: p for s, p in get_positions().items()
                 if p["qty"] != 0 and is_option_sym(s)}
        if not final:
            log("Post-close wing cleanup: positionbook flat. ✅", "TRADE")
            return True
        log(f"Post-close wing cleanup: {len(final)} positions still remain — monitor will exit.", "WARN")
        return True   # exit monitor — manual verification required

    # Residual positions include shorts → legitimate IC remnant, continue monitoring
    log(f"⚠️ Post-close: {len(residual)} positions remain ({len(residual_shorts)} short, "
        f"{len(residual_longs)} long) — continuing monitor.", "WARN")
    for sym, p in residual.items():
        log(f"   Residual: {sym} qty={p['qty']}", "WARN")
    state["closed"] = False
    new_ic = detect_ic_from_positions(fresh)
    if new_ic:
        state["ic"] = new_ic
    notify_n8n("RESIDUAL_POSITIONS", {"count": len(residual), "reason": reason})
    return False   # caller must NOT break


def close_side(positions, side, reason="GAMMA_MGMT"):
    """Close only CE or PE side of the IC (partial close).
    BUG6 fix: retries each failed order 2× with 1.5s backoff.
    """
    log(f"🟡 CLOSING {side} SIDE — {reason}", "TRADE")
    closed = 0
    tag = f"IC_{side}_CLOSE"

    for sym, p in positions.items():
        if p["qty"] == 0:
            continue
        if not normalize_sym(sym).endswith(side):
            continue
        action = "BUY" if p["qty"] < 0 else "SELL"
        ok = place_order(sym, action, abs(p["qty"]), tag)
        if not ok:
            for _retry in range(2):
                log(f"ORDER retry {_retry+1}/2: {action} {sym}", "WARN")
                time.sleep(1.5)
                ok = place_order(sym, action, abs(p["qty"]), tag)
                if ok:
                    break
        if ok:
            closed += 1
        time.sleep(0.4)

    if side == "CE":
        state["ce_closed"] = True
    elif side == "PE":
        state["pe_closed"] = True

    log(f"{side} close complete: {closed} legs exited", "TRADE")
    return closed


# ─── ROLL ADJUSTMENT ─────────────────────────────────────────────────────────
def roll_side(positions: dict, side: str, nifty: float, reason: str = "ROLL") -> bool:
    """Roll a threatened IC side to wider strikes (ATM±150/±250).

    Called when NIFTY enters 60–80pt zone AND pct_captured < 40%.
    Steps:
      1. Close current CE/PE side (buy back short, sell back long) via close_side()
      2. Re-enter at ATM±150 short / ATM±250 long at 75% of original qty
      3. Mark state ce_rolled / pe_rolled (only 1 roll per side per session)
    """
    log(f"🔄 ROLLING {side} SIDE — {reason}", "ROLL")

    # Step 1: Close existing side
    close_side(positions, side, f"ROLL_CLOSE_{side}")

    time.sleep(1.5)   # let fills settle

    # Step 2: Compute new strikes from current NIFTY ATM
    atm_now      = round(nifty / 50) * 50
    expiry       = state["expiry"]
    suffix       = side   # "CE" or "PE"
    sign         = 1 if side == "CE" else -1
    short_offset = 150 * sign
    long_offset  = 250 * sign
    new_short    = atm_now + short_offset
    new_long     = atm_now + long_offset

    # 75% of original qty (round to lot boundary)
    orig_qty = 0
    for sym, p in positions.items():
        if p["qty"] < 0 and normalize_sym(sym).endswith(side):
            orig_qty = abs(p["qty"])
            break
    if orig_qty == 0:
        orig_qty = 780   # safe fallback

    raw_roll_qty = int(orig_qty * 0.75 / LOT_SIZE) * LOT_SIZE
    qty_roll = max(LOT_SIZE, raw_roll_qty)
    if raw_roll_qty == 0:
        log(f"   Roll qty rounded to 0 from {orig_qty} — using minimum {LOT_SIZE}", "ROLL")  # 2.6

    short_sym = f"NIFTY{expiry}{new_short}{suffix}"
    long_sym  = f"NIFTY{expiry}{new_long}{suffix}"

    log(f"   Re-entering: SELL {short_sym} + BUY {long_sym} | qty={qty_roll}", "ROLL")

    # 1.6: Atomic roll — SELL short first, VERIFY fill, then BUY long
    sell_placed_at = time.time()
    ok_short = place_order(short_sym, "SELL", qty_roll, "IC_ROLL")
    if ok_short:
        sell_confirmed = verify_sell_fill(short_sym, qty_roll, timeout=30,
                                          placed_after=sell_placed_at)
    else:
        sell_confirmed = False

    if not sell_confirmed:
        log(f"Roll {side} SELL NOT CONFIRMED — aborting roll (no BUY hedge placed)", "ERROR")
        notify_n8n("ROLL_SELL_FAIL", {
            "side": side, "symbol": short_sym,
            "reason": "SELL fill not confirmed in tradebook — roll aborted"
        })
        return False

    time.sleep(0.8)
    buy_placed_at = time.time()
    ok_long = place_order(long_sym, "BUY", qty_roll, "IC_ROLL")

    # Verify BUY hedge fill (non-fatal but alert)
    if ok_long:
        buy_confirmed = verify_fill_in_tradebook(long_sym, "BUY", qty_roll,
                                                  timeout=20, placed_after=buy_placed_at)
        if not buy_confirmed:
            log(f"Roll {side} BUY hedge unconfirmed — check positions", "WARN")
            notify_n8n("ROLL_HEDGE_WARN", {
                "side": side, "symbol": long_sym,
                "reason": "BUY hedge not confirmed after roll"
            })

    log(f"Roll {side} complete: short={new_short} long={new_long} qty={qty_roll}", "ROLL")
    return True


def compute_session_metrics(final_mtm: float) -> None:
    """Compute and append session summary to trade_history.jsonl.

    Called automatically before every clean session exit (break).
    Records: pnl, pct_captured, MAE, duration_min, regime, rolls, exit_reason.
    """
    import json as _json

    # 1.8: Use cumulative premium (survives rolls/waves), capped to avoid absurd values
    ep  = state.get("cumulative_entry_premium", 0.0)
    if ep <= 0:
        ep = state["ic"].get("entry_premium", 1.0) if state.get("ic") else 1.0
    pct = min(5.0, max(-5.0, state.get("pct_captured", 0.0)))

    start_ts = state.get("start_ts")
    duration = round((time.time() - start_ts) / 60, 1) if start_ts else 0.0

    record = {
        "date":             datetime.now(IST).strftime("%Y-%m-%d"),
        "strategy":         "NIFTY_IC_v3",
        "expiry":           state.get("expiry", ""),
        "pnl":              round(final_mtm, 2),
        "entry_premium":    round(ep, 2),
        "pct_captured":     round(pct, 4),
        "mae":              round(state.get("mae", 0.0), 2),
        "peak_mtm":         round(state.get("peak_mtm", 0.0), 2),
        "duration_min":     duration,
        "vix_entry":        state.get("vix_entry", 0.0),
        "regime_at_entry":  state.get("regime_at_entry", ""),
        "ce_rolled":        state.get("ce_rolled", False),
        "pe_rolled":        state.get("pe_rolled", False),
        "adjustments":      state.get("adjustments", 0),
        "exit_reason":      state.get("last_exit_reason", ""),
    }

    path = _CFG_TRADE_HISTORY
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(_json.dumps(record) + "\n")
        log(
            f"METRICS: pnl={final_mtm:+.0f} capt={pct:.1%} "
            f"mae={record['mae']:+.0f} rolls={record['adjustments']} "
            f"dur={duration}min",
            "METRICS"
        )
        # 3.3: Per-expiry-cycle summary
        _expiry = state.get("expiry", "")
        if _expiry and os.path.exists(path):
            try:
                with open(path) as f:
                    _all = [_json.loads(l) for l in f if l.strip()]
                _cycle = [t for t in _all if t.get("expiry") == _expiry]
                if _cycle:
                    _total_pnl = sum(t.get("pnl", 0) for t in _cycle)
                    _wins = sum(1 for t in _cycle if t.get("pnl", 0) > 0)
                    log(f"EXPIRY SUMMARY ({_expiry}): {len(_cycle)} trades, "
                        f"P&L=₹{_total_pnl:+,.0f}, wins={_wins}/{len(_cycle)} "
                        f"({_wins/len(_cycle):.0%})", "METRICS")
            except Exception:
                pass
        # 3.5: log event
        log_event("SESSION_END", record)
    except Exception as e:
        log(f"Metrics write error: {e}", "WARN")


# ─── DYNAMIC WAVE ENTRY ───────────────────────────────────────────────────────
def enter_wave(wave_num: int, nifty: float, avail_margin: float, vix: float = 14.0, session_mtm: float = 0) -> bool:
    """Place a new IC wave with dynamically sized lots.

    Strike structure: ATM±100 shorts, ATM±200 longs (consistent across waves).
    Order sequence: SELL CE → SELL PE → BUY CE → BUY PE (RMS fix: shorts first).
    Returns True if short legs filled successfully.
    """
    # Gate checks
    if wave_num == 2 and session_mtm < WAVE2_MIN_MTM:
        log(f"Wave {wave_num} gate failed: MTM {session_mtm:+,.0f} < {WAVE2_MIN_MTM}", "WAVE")
        return False
    if wave_num == 3 and session_mtm < WAVE3_MIN_MTM:
        log(f"Wave {wave_num} gate failed: MTM {session_mtm:+,.0f} < {WAVE3_MIN_MTM:,}", "WAVE")
        return False

    lots   = compute_wave_lots(wave_num, avail_margin, vix, 0.0, session_mtm)
    qty    = lots * LOT_SIZE
    atm    = round(nifty / 50) * 50
    expiry = state["expiry"]

    # ── ENTRY DISTANCE CHECK (FIX 2026-03-02) ────────────────────────────────
    # NIFTY was only 76pt from short PE on 2026-03-02. MIN_ENTRY_DISTANCE = 100.
    # If NIFTY falls within MIN_ENTRY_DISTANCE of the standard ATM±100 shorts,
    # automatically widen to ATM±WIDEN_SHORT_OFFSET (150pt) for safer entry.
    std_short_ce    = atm + 100
    std_short_pe    = atm - 100
    dist_ce         = std_short_ce - nifty   # positive when NIFTY is below short CE
    dist_pe         = nifty - std_short_pe   # positive when NIFTY is above short PE

    if dist_ce < MIN_ENTRY_DISTANCE or dist_pe < MIN_ENTRY_DISTANCE:
        log(
            f"⚠️  Entry distance check: NIFTY={nifty:.0f} → dist_CE={dist_ce:.0f}pt dist_PE={dist_pe:.0f}pt "
            f"— below MIN_ENTRY_DISTANCE={MIN_ENTRY_DISTANCE}pt. "
            f"Widening shorts to ATM±{WIDEN_SHORT_OFFSET} (was ±100).", "WAVE"
        )
        short_offset = WIDEN_SHORT_OFFSET     # 150pt
        long_offset  = WIDEN_SHORT_OFFSET + 100  # 250pt
    else:
        short_offset = 100
        long_offset  = 200

    short_ce = build_option_symbol("NIFTY", expiry, atm + short_offset, "CE")
    long_ce  = build_option_symbol("NIFTY", expiry, atm + long_offset,  "CE")
    short_pe = build_option_symbol("NIFTY", expiry, atm - short_offset, "PE")
    long_pe  = build_option_symbol("NIFTY", expiry, atm - long_offset,  "PE")

    log(f"🟢 WAVE {wave_num}: NIFTY={nifty:.0f} ATM={atm} shorts=±{short_offset} lots={lots} qty={qty}", "WAVE")
    log(f"   SELL {short_ce} + SELL {short_pe} | BUY {long_ce} + BUY {long_pe}", "WAVE")
    log(f"   Margin estimate: ₹{lots * SPAN_PER_SPREAD_LOT:,.0f}", "WAVE")

    # LEG 1: SELL CE short — verify fill before placing anything else (Fix C — F2/F3)
    ok1 = place_order(short_ce, "SELL", qty, f"IC_WAVE{wave_num}")
    if not ok1 or not verify_sell_fill(short_ce, qty, timeout=30):
        log(f"Wave {wave_num} ABORTED: CE SELL not confirmed in tradebook", "ERROR")
        notify_n8n("WAVE_FAIL", {"wave": wave_num, "reason": "CE SELL unconfirmed (Dhan RMS reject)"})
        return False

    # LEG 2: SELL PE short — verify; compensate CE if failed
    time.sleep(0.5)
    ok2 = place_order(short_pe, "SELL", qty, f"IC_WAVE{wave_num}")
    if not ok2 or not verify_sell_fill(short_pe, qty, timeout=30):
        log(f"Wave {wave_num} ABORTED: PE SELL unconfirmed — buying back CE short", "ERROR")
        place_order(short_ce, "BUY", qty, f"IC_WAVE{wave_num}_COMP")
        notify_n8n("WAVE_FAIL", {"wave": wave_num, "reason": "PE SELL unconfirmed — CE compensated"})
        return False

    # LEGS 3+4: BUY hedges — only placed after both SELLs confirmed in tradebook
    time.sleep(0.5)
    ok3 = place_order(long_ce, "BUY", qty, f"IC_WAVE{wave_num}")
    time.sleep(0.5)
    ok4 = place_order(long_pe, "BUY", qty, f"IC_WAVE{wave_num}")

    log(f"Wave {wave_num} fills: CE_short=✅ PE_short=✅ CE_long={ok3} PE_long={ok4}", "WAVE")
    return True


# ─── TOTAL MTM ────────────────────────────────────────────────────────────────
def total_mtm_all(positions):
    """Sum MTM across all open CE/PE positions."""
    return sum(
        p["mtm"] for p in positions.values()
        if p["qty"] != 0 and is_option_sym(p["sym"])
    )


# ─── GRACEFUL SHUTDOWN ────────────────────────────────────────────────────────
_shutdown_requested = False

def _handle_signal(signum, frame):
    global _shutdown_requested
    log(f"Signal {signum} received — requesting graceful shutdown", "WARN")
    _shutdown_requested = True

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ─── MONITOR LOOP ─────────────────────────────────────────────────────────────
def _rotate_old_logs():
    """2.5: If log file is from a previous day, archive it. Clean up logs > 7 days old."""
    try:
        if not os.path.exists(LOG_FILE):
            return
        mtime = os.path.getmtime(LOG_FILE)
        log_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        today    = datetime.now(IST).strftime("%Y-%m-%d")
        if log_date < today:
            archive = LOG_FILE.replace(".log", f".{log_date}.log")
            os.rename(LOG_FILE, archive)
        # Clean up archives older than 7 days
        base = os.path.dirname(LOG_FILE)
        for old in glob.glob(os.path.join(base, "ic_monitor.*.log")):
            try:
                age_days = (time.time() - os.path.getmtime(old)) / 86400
                if age_days > 7:
                    os.remove(old)
            except Exception:
                pass
    except Exception:
        pass  # never fail startup over log rotation


def monitor_loop():
    # ── 2.5: Rotate previous day's log before anything else ──────────────
    _rotate_old_logs()

    # ── Infrastructure pre-flight check ──────────────────────────────────────
    if not check_infrastructure():
        sys.exit(1)

    # ── PID guard: exit if another instance is running ──────────────────────
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read().strip())
            if old_pid != os.getpid():
                try:
                    os.kill(old_pid, 0)   # check if process is alive
                    log(f"⚠️  Another monitor already running (PID {old_pid}). "
                        f"Kill it first: kill {old_pid}", "WARN")
                    sys.exit(1)
                except OSError:
                    pass  # old process is dead — OK to proceed
        except (ValueError, FileNotFoundError):
            pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log("=" * 70, "START")
    log("🚀 IC MONITOR v3 STARTED — Dynamic IC Session + Rolling + Metrics", "START")
    log(f"   Hard Close: {HARD_CLOSE_TIME[0]}:{HARD_CLOSE_TIME[1]:02d} IST | "
        f"Max Loss: ₹{abs(MAX_DAILY_LOSS):,}", "START")
    log(f"   Trail Lock: {TRAIL_LOCK_PCT:.0%} of peak (activates at ₹{TRAIL_LOCK_THRESHOLD:,})", "START")
    log(f"   Premium exits: {PREMIUM_CLOSE_PCT:.0%} full | "
        f"{PREMIUM_CLOSE_AFTER:.0%}+2PM | {PREMIUM_CLOSE_PROX:.0%}+proximity", "START")
    log(f"   Gamma zone: partial={GAMMA_ZONE_PARTIAL}pt / emergency={GAMMA_ZONE_FULL}pt", "START")
    log(f"   Roll zone: {ROLL_ZONE}pt (triggers roll if pct_captured<40%)", "START")
    log("=" * 70, "START")

    # ── Scan open positions for IC structure ─────────────────────────────────
    log("Scanning positionbook for IC structure...", "INIT")
    positions  = get_positions()
    open_count = sum(1 for p in positions.values() if p["qty"] != 0 and is_option_sym(p["sym"]))

    if open_count == 0:
        log("⚠️  No open option positions found. Start monitor AFTER Wave 1 fills.", "WARN")
        log("   Exiting cleanly.", "WARN")
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass
        return

    ic = detect_ic_from_positions(positions)
    if ic is None:
        log("⚠️  Could not detect IC structure from positions. Check positionbook.", "WARN")
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass
        return

    # ── Seed entry_premium if positionbook avg prices are 0 (Dhan intraday lag) ──
    # detect_ic_from_positions() clamps entry_premium to 1.0 when all avg=0.
    # Without a valid entry_premium, pct_captured = MTM/1 = thousands% → instant EXIT.
    # BUG1 fix: _ensure_entry_premium() retries chain 3×; falls back to qty×₹50 estimate
    # and blocks premium exits for 5 min if chain is unavailable.
    _ensure_entry_premium(ic, "(startup)")

    state["ic"]            = ic
    state["entry_premium"] = ic["entry_premium"]
    state["cumulative_entry_premium"] = ic["entry_premium"]  # 1.8: init cumulative
    state["entry_time"]    = ist_now()
    state["start_ts"]      = time.time()   # for duration calculation in metrics
    load_wave_state()   # restore today's wave flags if monitor was restarted — G7

    log(f"IC DETECTED: {len(ic['shorts'])} shorts + {len(ic['longs'])} longs", "INIT")
    log(f"  Short PE: {ic['short_pe_strike']} | Short CE: {ic['short_ce_strike']}", "INIT")
    log(f"  Entry premium: ₹{ic['entry_premium']:,.0f}", "INIT")
    log(f"  NIFTY barriers: {ic['nifty_lower_barrier']}–{ic['nifty_upper_barrier']}", "INIT")
    log(f"  Expiry: {state['expiry']}", "INIT")

    # ── Fetch initial NIFTY + VIX ────────────────────────────────────────────
    nifty, vix = get_nifty_and_vix()
    if vix > 0:
        state["vix_entry"]   = vix
        state["current_vix"] = vix
    if nifty > 0:
        state["nifty_entry"] = nifty

    log(f"Session start: NIFTY={nifty:.1f} | VIX={vix:.2f}", "INIT")
    log(f"Wave schedule: W2@{WAVE2_TIME[0]}:{WAVE2_TIME[1]:02d} | "
        f"W3@{WAVE3_TIME[0]}:{WAVE3_TIME[1]:02d} | "
        f"Hard close@{HARD_CLOSE_TIME[0]}:{HARD_CLOSE_TIME[1]:02d}", "INIT")

    # ── Auto-initialize state flags based on current time + IC structure ─────
    hm_init = ist_hm()
    if hm_init >= WAVE2_TIME:
        state["wave2_done"] = True
        log("Wave 2 window already passed — marking done (skip)", "INIT")
    if hm_init >= WAVE3_TIME:
        state["wave3_done"] = True
        log("Wave 3 window already passed — marking done (skip)", "INIT")

    # If no PE side detected → mark PE as closed/rolled (pure CE spread)
    if ic.get("short_pe_strike", 0) == 0:
        state["pe_closed"] = True
        state["pe_rolled"] = True
        log("No PE shorts detected → marking PE side as closed/rolled", "INIT")

    # If CE short strike > ATM+150 → assume CE was already rolled this session
    if nifty > 0:
        atm_init = round(nifty / 50) * 50
        if ic.get("short_ce_strike", 0) > atm_init + 150:
            state["ce_rolled"] = True
            log(f"CE short at {ic.get('short_ce_strike',0)} > ATM+150 → "
                f"marking ce_rolled=True (already rolled once)", "INIT")

    interval  = 60   # default monitoring interval (seconds)
    iteration = 0
    mtm       = 0.0  # 1.2: initialize before loop — safe fallback for exception handlers

    # ── Notify n8n that monitor is live ───────────────────────────────────────
    notify_n8n("SESSION_START", {
        "expiry": state.get("expiry", ""),
        "nifty_entry": state.get("nifty_entry", 0),
        "vix_entry": state.get("vix_entry", 0),
    })
    log_event("SESSION_START", {
        "expiry": state.get("expiry", ""),
        "nifty_entry": state.get("nifty_entry", 0),
        "vix_entry": state.get("vix_entry", 0),
        "ic": {"short_ce": ic.get("short_ce_strike", 0),
               "short_pe": ic.get("short_pe_strike", 0)},
    })

    while not _shutdown_requested:
        try:
            hm        = ist_hm()
            now       = ist_now()
            iteration += 1

            # ── 3.1: Adaptive interval based on proximity to short strikes ──
            _ic_t = state.get("ic")
            _min_dist = 999
            if _ic_t and nifty > 0:
                for _sk in (_ic_t.get("short_ce_strike", 0), _ic_t.get("short_pe_strike", 0)):
                    if _sk > 0:
                        _min_dist = min(_min_dist, abs(nifty - _sk))
            if _min_dist <= 30:
                interval = 15
            elif _min_dist <= 60:
                interval = 20
            elif _min_dist <= 100 or hm >= (14, 0):
                interval = 30
            else:
                interval = 60

            # ── Stop after market close ───────────────────────────────────
            if hm >= (15, 35):
                log("Market closed (15:35). Monitor exiting.", "DONE")
                state["last_exit_reason"] = "MARKET_CLOSED_15:35"
                compute_session_metrics(mtm)   # v3
                break

            # ── HARD CLOSE at 3:10 PM ─────────────────────────────────────
            if hm >= HARD_CLOSE_TIME and not state["closed"]:
                positions = get_positions()
                enrich_ltps_from_quotes(positions)
                mtm_final = total_mtm_all(positions)
                state["last_exit_reason"] = "HARD_CLOSE_3:10PM"
                if safe_close_all(positions, "HARD_CLOSE_3:10PM", allow_continue_until=(15, 35)):
                    compute_session_metrics(mtm_final)
                    break

            # ── PRE-CLOSE at 3:00 PM if MTM positive ─────────────────────
            if hm >= PRE_CLOSE_TIME and not state["closed"]:
                positions = get_positions()
                enrich_ltps_from_quotes(positions)
                nifty, vix = get_nifty_and_vix()
                mtm = total_mtm_all(positions)
                if mtm > 0:
                    log(f"3:00 PM pre-close: MTM={mtm:+,.0f} > 0 — closing all", "TRADE")
                    state["last_exit_reason"] = "PRE_CLOSE_3PM"
                    if safe_close_all(positions, "PRE_CLOSE_3PM", allow_continue_until=(15, 10)):
                        compute_session_metrics(mtm)
                        break
                else:
                    alert_once("preclose_wait",
                               f"3:00 PM: MTM={mtm:+,.0f}, holding until 3:10 hard close")

            # ── Fetch live data ───────────────────────────────────────────
            positions  = get_positions()

            # ── Consecutive failure guard ─────────────────────────────
            if not positions:
                state["consec_failures"] += 1
                log(f"OpenAlgo returned no positions "
                    f"(consecutive failures: {state['consec_failures']}/{INFRA_FAIL_LIMIT})",
                    "WARN")
                if state["consec_failures"] >= INFRA_FAIL_LIMIT:
                    state["infra_retry_count"] += 1
                    # Fix B: never abort while positions may be open.
                    # Escalate sleep (120s → 240s → 300s cap) but keep retrying.
                    _sleep_s = min(300, 120 * state["infra_retry_count"])
                    notify_n8n("INFRA_DOWN", {
                        "detail": f"OpenAlgo failed {INFRA_FAIL_LIMIT}× — "
                                  f"sleeping {_sleep_s}s (retry {state['infra_retry_count']}, no abort)"
                    })
                    log(f"INFRA PAUSE: retry {state['infra_retry_count']} (no abort). Sleeping {_sleep_s}s.", "ERROR")
                    # G6: Time-aware — don't sleep past hard close; attempt emergency close instead
                    _hm_now = ist_hm()
                    if _hm_now >= HARD_CLOSE_TIME:
                        log("INFRA OUTAGE at hard close time — attempting emergency close.", "ERROR")
                        try:
                            _raw = api_post("positionbook", {})
                            _pos = {p["symbol"]: {"qty": int(p.get("quantity", 0)),
                                                  "sym": p["symbol"], "mtm": 0.0, "ltp": 0.0}
                                    for p in (_raw.get("data") or []) if p.get("symbol")}
                            if any(v["qty"] != 0 for v in _pos.values()):
                                close_all_ic(_pos, "INFRA_HARD_CLOSE")
                        except Exception as _ex:
                            log(f"Emergency close attempt failed: {_ex}", "ERROR")
                            notify_n8n("EMERGENCY_CLOSE_FAIL", {"reason": str(_ex)})
                        break
                    time.sleep(_sleep_s)
                    state["consec_failures"] = 0
                    # 3.8: Re-validate infrastructure and refresh IC state after recovery
                    if check_infrastructure():
                        _rec_pos = get_positions()
                        if _rec_pos:
                            _rec_ic = detect_ic_from_positions(_rec_pos)
                            if _rec_ic:
                                state["ic"] = _rec_ic
                                ic = _rec_ic
                                log("IC state refreshed after infra recovery", "INIT")
                time.sleep(interval)
                continue
            else:
                state["consec_failures"] = 0   # reset on success

            enrich_ltps_from_quotes(positions)   # fix: positionbook LTP always 0
            nifty, vix = get_nifty_and_vix()
            mtm        = total_mtm_all(positions)

            if vix > 0:
                state["current_vix"] = vix
            if mtm > state["peak_mtm"]:
                state["peak_mtm"] = mtm
            if mtm < state["mae"]:              # v3: track most adverse excursion
                state["mae"] = mtm

            # Update LTPs in IC structure for SL checks
            ic = state["ic"]
            if ic:
                for leg_list in (ic.get("shorts", []), ic.get("longs", [])):
                    for leg in leg_list:
                        for sym, p in positions.items():
                            if normalize_sym(sym) == normalize_sym(leg["sym"]):
                                leg["ltp"] = p["ltp"]
                                break

            # ── Compute pct captured for status log (1.8: use cumulative) ───
            ep = state.get("cumulative_entry_premium", 0.0)
            if ep <= 0:
                ep = ic.get("entry_premium", 1.0) if ic else 1.0
            state["pct_captured"] = min(5.0, max(-5.0, mtm / ep if ep > 0 else 0.0))

            # ── Status log ────────────────────────────────────────────────
            short_pe = ic.get("short_pe_strike", 0) if ic else 0
            short_ce = ic.get("short_ce_strike", 0) if ic else 0
            d_pe = f" dPE={nifty - short_pe:.0f}" if short_pe and nifty else ""
            d_ce = f" dCE={short_ce - nifty:.0f}" if short_ce and nifty else ""
            vix_str = f"VIX={vix:.2f}" if vix > 0 else "VIX=?"
            log(
                f"NIFTY={nifty:.1f} {vix_str} | MTM={mtm:+,.0f} | "
                f"Peak={state['peak_mtm']:+,.0f} | Capt={state['pct_captured']:.1%} |"
                f"{d_pe}{d_ce}",
                "MONITOR"
            )
            # ── 3.6: Delta exposure check ─────────────────────────────────
            _n_lots = max(1, sum(abs(p["qty"]) for p in positions.values()
                                if p["qty"] != 0 and is_option_sym(p["sym"])) // (LOT_SIZE * 4))
            _net_d = approx_net_delta(ic, nifty, _n_lots)
            if abs(_net_d) > 0.3:
                alert_once("delta_skew",
                           f"Delta skew: net_delta={_net_d:.2f}/lot (threshold ±0.3) — IC becoming directional",
                           "WARN")

            # ── Update n8n notification cache ─────────────────────────────
            state["last_nifty"] = nifty
            state["last_mtm"]   = mtm
            state["last_dce"]   = int(short_ce - nifty) if short_ce and nifty else 0

            # ── 2.3: Heartbeat file (read by /health endpoint) ────────────
            write_heartbeat(nifty, mtm, {"iteration": iteration, "net_delta": _net_d})

            # ── Heartbeat to n8n every 10 iterations (≈10 min) ───────────
            if iteration % 10 == 0:
                notify_n8n("MONITOR")

            # ── DYNAMIC EXIT CHECK ────────────────────────────────────────
            if not state["closed"] and ic:
                do_exit, side, reason = check_dynamic_exit(ic, positions, nifty, mtm, now)
                if do_exit:
                    if side == "ALL":
                        log(f"🔴 EXIT ALL: {reason}", "EXIT")
                        state["last_exit_reason"] = reason
                        notify_n8n("EXIT_ALL", {"reason": reason})
                        log_event("EXIT", {"side": "ALL", "reason": reason, "mtm": mtm})
                        if safe_close_all(positions, reason, allow_continue_until=(15, 10)):
                            compute_session_metrics(mtm)
                            break
                    elif side in ("ROLL_CE", "ROLL_PE"):
                        # v3: Roll instead of close — keep IC alive at wider strikes
                        actual = side.replace("ROLL_", "")
                        log(f"🔄 ROLL {actual}: {reason}", "EXIT")
                        notify_n8n(f"ROLL_{actual}", {"reason": reason})
                        log_event("ROLL", {"side": actual, "reason": reason, "mtm": mtm})
                        roll_side(positions, actual, nifty, reason)
                        state[f"{actual.lower()}_rolled"] = True
                        state["adjustments"] += 1
                        save_wave_state()   # persist — G7
                        # Re-detect IC with new rolled positions
                        time.sleep(2)
                        positions = get_positions()
                        new_ic = detect_ic_from_positions(positions)
                        if new_ic:
                            _ensure_entry_premium(new_ic, "(post-roll)")   # BUG2 fix
                            state["ic"]            = new_ic
                            state["entry_premium"] = new_ic["entry_premium"]
                            state["cumulative_entry_premium"] += new_ic["entry_premium"]  # 1.8
                            ic                     = new_ic
                            log(f"IC refreshed after roll: premium=₹{new_ic['entry_premium']:,.0f} "
                                f"(cumulative=₹{state['cumulative_entry_premium']:,.0f})", "ROLL")
                        # Do NOT break — continue monitoring with new IC structure
                    elif side == "CE" and not state["ce_closed"]:
                        log(f"🟡 EXIT CE: {reason}", "EXIT")
                        notify_n8n("EXIT_CE", {"reason": reason})
                        close_side(positions, "CE", reason)
                    elif side == "PE" and not state["pe_closed"]:
                        log(f"🟡 EXIT PE: {reason}", "EXIT")
                        notify_n8n("EXIT_PE", {"reason": reason})
                        close_side(positions, "PE", reason)

            # ── AFTERNOON CE CLOSE at 2:30 PM (gamma risk) ───────────────
            if (hm >= AFTERNOON_CE_CLOSE and not state["ce_closed"]
                    and not state["closed"] and mtm > 10_000):
                alert_once("aft_ce_close",
                           f"2:30 PM CE gamma close: MTM={mtm:+,.0f} > ₹10K")
                close_side(positions, "CE", "THETA_DECAY_2:30PM")

            # ── WAVE 2 at 11:30 AM ────────────────────────────────────────
            # Skip if CE side already force-closed (gamma zone hit) — adding lots
            # after a forced CE exit would create a naked CE short (bug: 27-FEB-2026)
            if hm >= WAVE2_TIME and not state["wave2_done"] and not state["closed"] \
                    and not state["ce_closed"]:
                atm_now  = round(nifty / 50) * 50 if nifty > 0 else 0
                in_range = (nifty > 0 and abs(nifty - atm_now) < 150)
                log(f"Wave2 check: MTM={mtm:+,.0f} | "
                    f"NIFTY={nifty:.0f} in_range={in_range}", "WAVE2")
                if mtm >= WAVE2_MIN_MTM and in_range:
                    avail = get_available_margin()
                    ok    = enter_wave(2, nifty, avail, vix if vix > 0 else 14.0, mtm)
                    if ok:
                        # Refresh IC to include Wave 2 positions
                        time.sleep(2)
                        positions = get_positions()
                        new_ic = detect_ic_from_positions(positions)
                        if new_ic:
                            _ensure_entry_premium(new_ic, "(post-wave2)")   # BUG2 fix
                            state["ic"]            = new_ic
                            state["entry_premium"] = new_ic["entry_premium"]
                            state["cumulative_entry_premium"] += new_ic["entry_premium"]  # 1.8
                            log(f"IC refreshed after Wave2: premium=₹{new_ic['entry_premium']:,.0f} "
                                f"(cumulative=₹{state['cumulative_entry_premium']:,.0f})", "WAVE2")
                else:
                    log("Wave2 skipped: conditions not met", "WAVE2")
                state["wave2_done"] = True   # don't retry regardless
                save_wave_state()   # persist — G7

            # ── WAVE 3 at 2:00 PM ────────────────────────────────────────
            # Same guard: skip if CE already force-closed (naked short risk)
            if hm >= WAVE3_TIME and not state["wave3_done"] and not state["closed"] \
                    and not state["ce_closed"]:
                atm_now  = round(nifty / 50) * 50 if nifty > 0 else 0
                in_range = (nifty > 0 and abs(nifty - atm_now) < 150)
                log(f"Wave3 check: MTM={mtm:+,.0f} | "
                    f"NIFTY={nifty:.0f} in_range={in_range}", "WAVE3")
                if mtm >= WAVE3_MIN_MTM and in_range:
                    avail = get_available_margin()
                    ok    = enter_wave(3, nifty, avail, vix if vix > 0 else 14.0, mtm)
                    if ok:
                        time.sleep(2)
                        positions = get_positions()
                        new_ic = detect_ic_from_positions(positions)
                        if new_ic:
                            _ensure_entry_premium(new_ic, "(post-wave3)")   # BUG2 fix
                            state["ic"]            = new_ic
                            state["entry_premium"] = new_ic["entry_premium"]
                            state["cumulative_entry_premium"] += new_ic["entry_premium"]  # 1.8
                            log(f"IC refreshed after Wave3: premium=₹{new_ic['entry_premium']:,.0f} "
                                f"(cumulative=₹{state['cumulative_entry_premium']:,.0f})", "WAVE3")
                else:
                    log("Wave3 skipped: conditions not met", "WAVE3")
                state["wave3_done"] = True
                save_wave_state()   # persist — G7

        except KeyboardInterrupt:
            log("Monitor stopped by user (Ctrl+C)", "STOP")
            state["last_exit_reason"] = "USER_INTERRUPT"
            compute_session_metrics(mtm)   # 1.2: mtm always in scope (initialized before loop)
            break
        except Exception as e:
            log(f"Monitor iteration error: {e}", "ERROR")
            import traceback
            log(traceback.format_exc()[:500], "ERROR")

        time.sleep(interval)

    # ── Graceful shutdown: save state, notify, cleanup (2.4) ──────────────────
    if _shutdown_requested and not state["closed"]:
        log("Shutdown with open positions — saving state for recovery", "WARN")
        notify_n8n("MONITOR_SHUTDOWN", {
            "reason": "Signal received",
            "positions_open": True,
            "mtm": mtm,
        })

    save_wave_state()

    # ── Cleanup PID file ─────────────────────────────────────────────────────
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass
    log("IC Monitor v3 exiting.", "DONE")


if __name__ == "__main__":
    # 1.3: Removed signal.signal(SIGTERM, sys.exit(0)) — it overrode the
    # graceful handler at line 968, bypassing PID cleanup and metrics save.
    # The handler registered at module level (_handle_signal) handles SIGTERM.
    monitor_loop()
