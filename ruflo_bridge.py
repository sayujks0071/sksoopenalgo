#!/usr/bin/env python3
"""
ruflo_bridge.py — Claude Flow integration sidecar for IC trading.

Modes:
  seed          8:00 AM — dump IC config + session init as JSON for ruflo memory seeding
  calibrate     9:09 AM — pre-entry check snapshot (VIX, regime, credit gate)
  monitor       9:20 AM — emit live state every 60s for SONA trajectory step recording
  wave_vote 2|3 11:28/1:58 PM — fast rule-based vote for hive-mind consensus
  post_session  3:30 PM — aggregate session data for pattern storage + RL trajectory end

Usage:
  python3 ruflo_bridge.py seed
  python3 ruflo_bridge.py calibrate
  python3 ruflo_bridge.py monitor
  python3 ruflo_bridge.py wave_vote 2
  python3 ruflo_bridge.py wave_vote 3
  python3 ruflo_bridge.py post_session

Output: JSON to stdout. Non-zero exit = operation failed.
The Claude Code session reads this output and calls ruflo MCP tools accordingly.
"""
import sys, os, json, time, argparse
from datetime import datetime, date
from typing import Any

# ─── Paths ────────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

try:
    from ic_config import (
        OPENALGO_KEY, OPENALGO_URL, LOT_SIZE, SPAN_PER_LOT,
        MAX_DAILY_LOSS, MAX_CONSECUTIVE_LOSSES, WEEKLY_LOSS_LIMIT,
        MAX_LOTS_HARD_CAP, MIN_LOTS, PREMIUM_CLOSE_PCT, PREMIUM_CLOSE_AFTER,
        PREMIUM_STOP_MULTIPLE, VIX_MIN_ENTRY, ROLL_ZONE, GAMMA_ZONE_PARTIAL,
        GAMMA_ZONE_FULL, TRAIL_LOCK_THRESHOLD, TRAIL_LOCK_PCT, VIX_SPIKE_TRIGGER,
        WAVE2_MIN_MTM, WAVE3_MIN_MTM, HARD_CLOSE_TIME, WAVE2_TIME, WAVE3_TIME,
        STATE_FILE, HEARTBEAT_FILE, EVENTS_LOG, get_next_expiry,
    )
except ImportError as e:
    print(json.dumps({"error": f"ic_config import failed: {e}"}))
    sys.exit(1)

import urllib.request
import urllib.error

RUFLO_STATE_FILE = os.path.join(_BASE, "ruflo_session_state.json")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_ist():
    try:
        import pytz
        return datetime.now(pytz.timezone("Asia/Kolkata"))
    except ImportError:
        return datetime.utcnow()


def _now_str():
    return _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")


def _api_post(endpoint: str, payload: dict, timeout: int = 5) -> dict:
    """POST to OpenAlgo API. Returns parsed JSON or {"error": ...}."""
    url = f"{OPENALGO_URL}/{endpoint}"
    data = json.dumps({**payload, "apikey": OPENALGO_KEY}).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as ex:
        return {"error": str(ex)}


def _read_state() -> dict:
    """Read ic_state.json (written by ic_monitor.py)."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _read_heartbeat() -> dict:
    """Read ic_heartbeat.json (written every 60s by ic_monitor.py)."""
    try:
        with open(HEARTBEAT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_ruflo_state(update: dict):
    """Merge update into ruflo_session_state.json."""
    existing = {}
    try:
        with open(RUFLO_STATE_FILE) as f:
            existing = json.load(f)
    except Exception:
        pass
    existing.update(update)
    existing["last_updated"] = _now_str()
    with open(RUFLO_STATE_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def _emit(obj: Any):
    """Print JSON to stdout (main output channel to Claude Code)."""
    print(json.dumps(obj, indent=2, default=str))


# ─── Mode: seed ───────────────────────────────────────────────────────────────

def mode_seed():
    """Dump all IC config + session init state for ruflo memory seeding."""
    today      = date.today().isoformat()
    expiry     = get_next_expiry()
    now_str    = _now_str()

    out = {
        "mode":     "seed",
        "timestamp": now_str,
        "session_date": today,
        "expiry":    expiry,

        # ic_config namespace — permanent constants
        "ic_config": {
            "ic_lot_size":         LOT_SIZE,
            "ic_span_per_lot":     SPAN_PER_LOT,
            "ic_max_daily_loss":   MAX_DAILY_LOSS,
            "ic_weekly_loss_limit": WEEKLY_LOSS_LIMIT,
            "ic_max_consec_losses": MAX_CONSECUTIVE_LOSSES,
            "ic_vix_min_entry":    VIX_MIN_ENTRY,
            "ic_premium_close_pct": PREMIUM_CLOSE_PCT,
            "ic_premium_close_after": PREMIUM_CLOSE_AFTER,
            "ic_premium_stop_mult": PREMIUM_STOP_MULTIPLE,
            "ic_gamma_full_pts":   GAMMA_ZONE_FULL,
            "ic_gamma_partial_pts": GAMMA_ZONE_PARTIAL,
            "ic_roll_zone_pts":    ROLL_ZONE,
            "ic_trail_lock_thresh": TRAIL_LOCK_THRESHOLD,
            "ic_trail_lock_pct":   TRAIL_LOCK_PCT,
            "ic_vix_spike_trigger": VIX_SPIKE_TRIGGER,
            "ic_wave2_min_mtm":    WAVE2_MIN_MTM,
            "ic_wave3_min_mtm":    WAVE3_MIN_MTM,
            "ic_max_lots_hardcap": MAX_LOTS_HARD_CAP,
            "ic_min_lots":         MIN_LOTS,
        },

        # ic_session namespace — daily reset values
        "ic_session": {
            "session_date":  today,
            "expiry":        expiry,
            "wave1_done":    False,
            "wave2_done":    False,
            "wave3_done":    False,
            "current_mtm":   0,
            "peak_mtm":      0,
            "entry_credit":  0,
            "entry_lots":    0,
            "entry_vix":     0.0,
            "entry_regime":  "UNKNOWN",
            "entry_atm":     0,
            "ce_closed":     False,
            "pe_closed":     False,
            "trajectory_id": "",
        },

        # ruflo instructions (for Claude Code to execute)
        "ruflo_instructions": {
            "memory_namespace_config":  "ic_config",
            "memory_namespace_session": "ic_session",
            "memory_upsert":            True,
            "workflow_name":            "monday_morning_ic_session",
            "session_start_context":    f"IC session {today}, expiry {expiry}",
        }
    }

    _write_ruflo_state({"seed": out})
    _emit(out)


# ─── Mode: calibrate ──────────────────────────────────────────────────────────

def mode_calibrate():
    """Pre-entry snapshot: fetch VIX, option chain, check go/caution/skip."""
    expiry  = get_next_expiry()
    now_str = _now_str()

    # Try to get VIX
    vix_resp = _api_post("quote", {"symbol": "INDIA VIX", "exchange": "NSE_INDEX"})
    vix = vix_resp.get("data", {}).get("ltp", 0.0) if "error" not in vix_resp else 0.0

    # Try to get NIFTY ATM
    chain_resp = _api_post("optionchain",
                           {"underlying": "NIFTY", "exchange": "NSE_INDEX",
                            "expiry_date": expiry, "strike_count": 6})
    if "error" not in chain_resp and "atm_strike" in chain_resp:
        atm   = chain_resp.get("atm_strike", 0)
        nifty = chain_resp.get("underlying_ltp", 0)
        # Estimate net credit at ATM±100
        strikes = {s["strike"]: s for s in chain_resp.get("chain", [])}
        ce_short = strikes.get(atm + 100, {})
        pe_short = strikes.get(atm - 100, {})
        ce_long  = strikes.get(atm + 200, {})
        pe_long  = strikes.get(atm - 200, {})
        credit = ((ce_short.get("ce", {}).get("ltp", 0) or 0)
                + (pe_short.get("pe", {}).get("ltp", 0) or 0)
                - (ce_long.get("ce", {}).get("ltp", 0) or 0)
                - (pe_long.get("pe", {}).get("ltp", 0) or 0))
    else:
        atm = nifty = credit = 0

    # Rule-based decision
    if vix > 0 and vix < VIX_MIN_ENTRY:
        decision = "SKIP"
        reason   = f"VIX {vix:.1f} < {VIX_MIN_ENTRY} — premium too thin"
    elif vix > 20:
        decision = "CAUTION"
        reason   = f"VIX {vix:.1f} > 20 — high vol, reduce lots 50%"
    elif credit > 0 and credit < 15:
        decision = "SKIP"
        reason   = f"Net credit ₹{credit:.0f}/unit < ₹15 minimum"
    elif credit > 0 and credit < 25:
        decision = "CAUTION"
        reason   = f"Net credit ₹{credit:.0f}/unit thin — monitor carefully"
    else:
        decision = "GO"
        reason   = f"VIX={vix:.1f}, credit=₹{credit:.0f}/unit, ATM={atm}"

    out = {
        "mode":       "calibrate",
        "timestamp":  now_str,
        "expiry":     expiry,
        "vix":        vix,
        "nifty":      nifty,
        "atm":        atm,
        "credit_est": round(credit, 1),
        "decision":   decision,
        "reason":     reason,
        "ruflo_pattern_query": f"VIX {vix:.0f} regime market conditions IC entry",
    }
    _write_ruflo_state({"calibrate": out})
    _emit(out)


# ─── Mode: monitor ────────────────────────────────────────────────────────────

def mode_monitor():
    """Emit current IC state once (for SONA trajectory step). Not a loop."""
    state   = _read_state()
    hb      = _read_heartbeat()
    now_str = _now_str()

    ic = state.get("ic", {})
    out = {
        "mode":           "monitor",
        "timestamp":      now_str,
        "session_mtm":    hb.get("session_mtm", state.get("session_mtm", 0)),
        "peak_mtm":       state.get("peak_mtm", 0),
        "pct_captured":   round(state.get("pct_captured", 0.0), 3),
        "entry_premium":  state.get("entry_premium", 0),
        "wave2_done":     state.get("wave2_done", False),
        "wave3_done":     state.get("wave3_done", False),
        "ce_closed":      state.get("ce_closed", False),
        "pe_closed":      state.get("pe_closed", False),
        "current_vix":    state.get("current_vix", 0.0),
        "nifty_entry":    state.get("nifty_entry", 0),
        "lots":           ic.get("lots", 0),
        "short_ce":       ic.get("short_ce", ""),
        "short_pe":       ic.get("short_pe", ""),
        "monitor_alive":  bool(hb),
        "health":         hb.get("health", "unknown"),
        "trajectory_step": {
            "action": "live_snapshot",
            "quality": min(1.0, max(0.0,
                          hb.get("session_mtm", 0) / abs(MAX_DAILY_LOSS) + 0.5))
        }
    }
    _write_ruflo_state({"monitor": out})
    _emit(out)


# ─── Mode: wave_vote ──────────────────────────────────────────────────────────

def mode_wave_vote(wave: int):
    """Rule-based 3-agent hive-mind vote for wave 2 or 3 entry."""
    state   = _read_state()
    hb      = _read_heartbeat()
    now_str = _now_str()
    now     = _now_ist()

    session_mtm = hb.get("session_mtm", state.get("session_mtm", 0))
    peak_mtm    = state.get("peak_mtm", 0)
    vix         = state.get("current_vix", 0.0)
    nifty       = hb.get("nifty_ltp", 0)
    atm         = state.get("entry_atm", state.get("ic", {}).get("atm", 0))
    pct_cap     = state.get("pct_captured", 0.0)
    wave2_done  = state.get("wave2_done", False)
    regime      = state.get("regime_at_entry", "UNKNOWN")

    # ── RiskAgent vote ────────────────────────────────────────────────────────
    if wave == 2:
        risk_threshold = WAVE2_MIN_MTM   # 0
        risk_yes       = session_mtm >= risk_threshold
        risk_reason    = f"MTM ₹{session_mtm:,.0f} {'≥' if risk_yes else '<'} threshold ₹{risk_threshold:,.0f}"
    else:  # wave 3
        risk_threshold = WAVE3_MIN_MTM   # 35_000
        risk_yes       = session_mtm >= risk_threshold
        risk_reason    = f"MTM ₹{session_mtm:,.0f} {'≥' if risk_yes else '<'} threshold ₹{risk_threshold:,.0f}"

    # ── RegimeAgent vote ──────────────────────────────────────────────────────
    vix_ok          = VIX_MIN_ENTRY <= vix <= 20
    regime_ok       = regime not in ("TRENDING_BULL", "TRENDING_BEAR", "UNKNOWN")
    nifty_range_ok  = atm == 0 or abs(nifty - atm) <= 200
    regime_yes      = vix_ok and regime_ok and nifty_range_ok
    regime_reason   = (
        f"VIX={vix:.1f}({'OK' if vix_ok else 'BAD'}), "
        f"regime={regime}({'OK' if regime_ok else 'BAD'}), "
        f"NIFTY {'+' if nifty >= atm else ''}{nifty - atm:.0f}pt({'OK' if nifty_range_ok else 'WIDE'})"
    )

    # ── MTMAgent vote — trajectory analysis ──────────────────────────────────
    # Simple: is peak_mtm reasonable and is drawdown from peak acceptable?
    if peak_mtm > 0:
        drawdown_from_peak = (peak_mtm - session_mtm) / peak_mtm
        mtm_yes    = drawdown_from_peak < 0.30 and pct_cap < 0.75
        mtm_reason = (
            f"peak=₹{peak_mtm:,.0f}, cur=₹{session_mtm:,.0f}, "
            f"drawdown={drawdown_from_peak:.0%}, pct_captured={pct_cap:.0%}"
        )
    else:
        mtm_yes    = session_mtm >= 0
        mtm_reason = f"No peak data — MTM ₹{session_mtm:,.0f} ({'≥0' if mtm_yes else '<0'})"

    # ── Consensus ─────────────────────────────────────────────────────────────
    votes     = [risk_yes, regime_yes, mtm_yes]
    yes_count = sum(votes)
    consensus = yes_count >= 2  # 2/3 majority

    out = {
        "mode":       f"wave_vote_{wave}",
        "timestamp":  now_str,
        "wave":       wave,
        "consensus":  consensus,
        "verdict":    "✅ PROCEED" if consensus else "🔴 SKIP",
        "votes": {
            "RiskAgent":   {"vote": risk_yes,   "reason": risk_reason},
            "RegimeAgent": {"vote": regime_yes, "reason": regime_reason},
            "MTMAgent":    {"vote": mtm_yes,    "reason": mtm_reason},
        },
        "yes_count":  yes_count,
        "session_mtm": session_mtm,
        "peak_mtm":   peak_mtm,
        "vix":        vix,
        "regime":     regime,
        "ruflo_hive_proposal": {
            "type":  "wave_execute",
            "value": {"wave": wave, "session_mtm": session_mtm,
                      "yes_count": yes_count, "consensus": consensus}
        }
    }
    _write_ruflo_state({f"wave_vote_{wave}": out})
    _emit(out)


# ─── Mode: post_session ───────────────────────────────────────────────────────

def mode_post_session():
    """Aggregate session data for SONA trajectory end + pattern storage."""
    state   = _read_state()
    hb      = _read_heartbeat()
    now_str = _now_str()
    today   = date.today().isoformat()

    session_mtm  = hb.get("session_mtm", state.get("session_mtm", 0))
    peak_mtm     = state.get("peak_mtm", 0)
    pct_captured = state.get("pct_captured", 0.0)
    entry_vix    = state.get("vix_entry", state.get("current_vix", 0.0))
    regime       = state.get("regime_at_entry", "UNKNOWN")
    wave2_done   = state.get("wave2_done", False)
    wave3_done   = state.get("wave3_done", False)
    entry_credit = state.get("entry_premium", 0)
    lots         = state.get("ic", {}).get("lots", 0)
    adjustments  = state.get("adjustments", 0)

    # Quality score for RL trajectory: 0.5 = breakeven, 1.0 = perfect day, 0.0 = max loss
    quality = min(1.0, max(0.0, session_mtm / abs(MAX_DAILY_LOSS) + 0.5))
    success = session_mtm > 0

    # Build new pattern for today's session (if tradeable data exists)
    patterns = []
    if lots > 0 and entry_credit > 0:
        vix_bucket = (
            "< 13 (too thin)" if entry_vix < 13 else
            "13-16 (ideal)"   if entry_vix < 16 else
            "16-20 (elevated)" if entry_vix < 20 else
            "> 20 (high)"
        )
        outcome_str = (
            f"P&L=₹{session_mtm:,.0f}, pct_cap={pct_captured:.0%}, "
            f"wave2={wave2_done}, wave3={wave3_done}"
        )
        patterns.append({
            "pattern": (
                f"{today} IC session: VIX {entry_vix:.1f} ({vix_bucket}), "
                f"regime={regime}, credit=₹{entry_credit:.0f}/unit, "
                f"lots={lots} → {outcome_str}"
            ),
            "type":       "session_archetype",
            "confidence": min(0.95, 0.6 + abs(session_mtm) / 50000 * 0.35) if success else 0.5,
        })

    out = {
        "mode":           "post_session",
        "timestamp":      now_str,
        "session_date":   today,
        "final_pnl":      session_mtm,
        "peak_mtm":       peak_mtm,
        "pct_captured":   round(pct_captured, 3),
        "quality":        round(quality, 3),
        "success":        success,
        "entry_vix":      entry_vix,
        "entry_credit":   entry_credit,
        "lots":           lots,
        "regime":         regime,
        "wave2_done":     wave2_done,
        "wave3_done":     wave3_done,
        "adjustments":    adjustments,
        "new_patterns":   patterns,
        "ruflo_instructions": {
            "trajectory_end_success": success,
            "trajectory_quality":     quality,
            "session_store_key":      f"ic_session_{today}",
            "session_store_namespace": "ic_historical",
            "run_learn_consolidate":  True,
        }
    }
    _write_ruflo_state({"post_session": out})
    _emit(out)


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="ruflo_bridge — Claude Flow IC sidecar")
    p.add_argument("mode", choices=["seed", "calibrate", "monitor",
                                     "wave_vote", "post_session"],
                   help="Operation mode")
    p.add_argument("wave", nargs="?", type=int, choices=[2, 3],
                   help="Wave number (required for wave_vote mode)")
    args = p.parse_args()

    if args.mode == "seed":
        mode_seed()
    elif args.mode == "calibrate":
        mode_calibrate()
    elif args.mode == "monitor":
        mode_monitor()
    elif args.mode == "wave_vote":
        if args.wave is None:
            p.error("wave_vote requires wave number: 2 or 3")
        mode_wave_vote(args.wave)
    elif args.mode == "post_session":
        mode_post_session()


if __name__ == "__main__":
    main()
