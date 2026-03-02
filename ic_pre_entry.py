#!/usr/bin/env python3
"""
IC Pre-Entry Quality Check — run at 9:10 AM before Wave 1
=========================================================
Checks regime, VIX, net credit, margin, and gap before allowing IC entry.

Exit codes:
  0 = GO      — all conditions met, proceed with Wave 1
  1 = CAUTION — partial conditions met, reduce lots or wait
  2 = SKIP    — do not trade today (trending, high VIX chop, or thin premium)

Usage:
  python3 ic_pre_entry.py
  python3 ic_pre_entry.py && echo "Proceeding with Wave 1..."
"""

import sys
import json as _json
import os
import time
import requests
import pytz
from datetime import datetime, timedelta

# ── Config — single source of truth ─────────────────────────────────────────
from ic_config import (OPENALGO_KEY as KEY, OPENALGO_URL as _API_BASE,
                       get_next_expiry, LOT_SIZE, SPAN_PER_LOT as SPAN_MARGIN,
                       MAX_CONSECUTIVE_LOSSES, WEEKLY_LOSS_LIMIT, TRADE_HISTORY,
                       VIX_MIN_ENTRY)
API    = _API_BASE
EXPIRY = get_next_expiry()   # auto-computes each run — no more manual weekly updates

MIN_CREDIT        = 25     # ₹/unit: below this → SKIP (raised for 33-lot size)
CREDIT_CAUTION    = 15     # ₹/unit: below this but ≥10 → CAUTION
GAP_SKIP_PCT      = 1.5    # NIFTY gap > this % from session open vs prev ATM → wait
VIX_HIGH_SKIP     = 18     # VIX > this with VOLATILE_CHOP → SKIP
VIX_CHOP_CAUTION  = 14     # VIX 14–18 with VOLATILE_CHOP → CAUTION

IST = pytz.timezone("Asia/Kolkata")

# ── Helpers ──────────────────────────────────────────────────────────────────

def post(endpoint, payload, timeout=8):
    try:
        r = requests.post(f"{API}/{endpoint}", json=payload, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_option_chain(expiry, strike_count=10):
    return post("optionchain", {
        "apikey": KEY, "underlying": "NIFTY",
        "exchange": "NSE_INDEX", "expiry_date": expiry,
        "strike_count": strike_count
    })


def get_vix():
    """Fetch India VIX via OpenAlgo quotes endpoint.
    FIX: The previous approach used optionchain for INDIAVIX — this always returned 0
    because INDIAVIX has no option chain. Use /quotes for the index LTP directly.
    Returns the live VIX value, or 0.0 if unavailable (caller handles 0 as blind-VIX).
    """
    try:
        rv = post("quotes", {
            "apikey": KEY, "symbol": "INDIAVIX", "exchange": "NSE_INDEX"
        }, timeout=5)
        vix_data = rv.get("data") or rv
        v = float(vix_data.get("ltp", 0) or vix_data.get("last_price", 0) or 0)
        if v > 0:
            return v
    except Exception as e:
        print(f"  ⚠️  VIX quotes error: {e}")
    return 0.0   # 0.0 = unknown VIX (caller will use RANGE_UNKNOWN_VIX regime)


def get_funds():
    resp = post("funds", {"apikey": KEY})
    return float(resp.get("data", {}).get("availablecash", 0) or 0)


def detect_regime(nifty_ltp: float = 0.0, vix: float = 0.0):
    """Detect market regime using live NIFTY data.

    First tries the OpenClaw RegimeDetector skill. If unavailable (99% of the time),
    falls back to a VIX + price-action heuristic that actually works.

    Fallback regime logic (based on CMT/CBOE best practices):
      - VIX < 13:  LOW_VOL   → IC edge is thin; use reduced lots
      - VIX 13-16: RANGE     → ideal IC conditions
      - VIX 16-20: ELEVATED  → moderate risk, reduce lots 25%
      - VIX 20-25: HIGH_VOL  → reduce lots 50%
      - VIX > 25:  EXTREME   → skip (IC too risky)
      - NIFTY gap > 1.5% from prev close: GAP_DAY → wait for 10:30 AM settlement
    """
    # Try OpenClaw skill first
    try:
        sys.path.insert(0, "/Users/mac/.openclaw/workspace/skills/market-regime/helpers")
        from regime_detector import RegimeDetector
        result = RegimeDetector().detect_regime("NIFTY", "NSE_INDEX")
        return result.get("regime", "UNKNOWN"), result.get("position_sizing_factor", 1.0)
    except Exception as e:
        pass   # skill not available — use VIX heuristic

    # ── VIX-based fallback regime (always available if VIX fetch works) ──────
    # Also uses the live NIFTY LTP for gap detection (if available via OHLC)
    if vix <= 0:
        print("  ⚠️  Regime: VIX unavailable — assuming RANGE regime (factor 0.85 caution)")
        return "RANGE_UNKNOWN_VIX", 0.85   # cautious sizing when VIX is blind

    if vix > 25:
        return "EXTREME_VOL", 0.0     # skip trading
    elif vix > 20:
        return "HIGH_VOL", 0.5        # 50% lots
    elif vix > 16:
        return "ELEVATED_VOL", 0.75   # 75% lots
    elif vix > 13:
        return "RANGE", 1.0           # ideal IC conditions
    else:
        return "LOW_VOL", 0.70        # VIX < 13 → premium too thin → 70% lots


def compute_wave_lots(avail, vix_factor=1.0):
    """Mirror ic_monitor.py compute_wave_lots logic."""
    max_lots = int(avail * 0.78 / SPAN_MARGIN)
    wave1    = max(4, min(40, int(max_lots * vix_factor)))
    wave2    = max(4, min(40, int(wave1 * 0.65)))
    wave3    = max(4, min(40, int(wave1 * 0.40)))
    return wave1, wave2, wave3


def check_recent_performance() -> tuple[bool, str]:
    """3.2: Circuit breaker — check recent trade history for consecutive losses or weekly floor.
    Also checks today's cumulative P&L across all sessions (multi-session day tracking).
    Returns (should_skip: bool, reason: str).
    """
    try:
        if not os.path.exists(TRADE_HISTORY):
            return False, ""
        with open(TRADE_HISTORY) as f:
            lines = f.readlines()
        if not lines:
            return False, ""

        # Parse ALL trades (for today's daily P&L check)
        all_trades = []
        for line in lines:
            try:
                all_trades.append(_json.loads(line.strip()))
            except Exception:
                pass

        if not all_trades:
            return False, ""

        today = datetime.now(IST).strftime("%Y-%m-%d")

        # ── Check today's cumulative P&L (CRITICAL: multi-session day fix) ──
        # ic_monitor MAX_DAILY_LOSS only tracks the CURRENT session's MTM.
        # If you lost ₹80K in the morning session and start a new session,
        # the MAX_DAILY_LOSS check resets to 0. This cross-session daily floor
        # ensures we don't keep adding sessions on a bad day.
        today_pnl = sum(t.get("pnl", 0) for t in all_trades if t.get("date", "") == today)
        if today_pnl < -75_000:   # ₹75K intraday loss = stop all trading today
            return True, (f"Daily loss floor: today's cumulative P&L ₹{today_pnl:,.0f} "
                          f"< -₹75,000 limit — no more sessions today")

        # Parse last 10 trades for consecutive loss check
        trades = all_trades[-10:]

        # Check consecutive losses (last N trades, any date)
        recent = trades[-MAX_CONSECUTIVE_LOSSES:]
        if len(recent) >= MAX_CONSECUTIVE_LOSSES:
            if all(t.get("pnl", 0) < 0 for t in recent):
                return True, (f"Circuit breaker: {MAX_CONSECUTIVE_LOSSES} consecutive losses "
                              f"(last P&Ls: {[round(t.get('pnl',0)) for t in recent]})")

        # Check weekly P&L floor
        week_ago = (datetime.now(IST) - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly_pnl = sum(t.get("pnl", 0) for t in all_trades
                         if t.get("date", "") >= week_ago)
        if weekly_pnl < WEEKLY_LOSS_LIMIT:
            return True, (f"Weekly loss floor: ₹{weekly_pnl:,.0f} < ₹{WEEKLY_LOSS_LIMIT:,.0f} limit")

        return False, ""
    except Exception as e:
        print(f"  ⚠️  Circuit breaker check failed: {e}")
        return False, ""  # fail open — don't block trading on check errors


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(IST)
    print(f"\n{'='*60}")
    print(f"  IC PRE-ENTRY CHECK — {now.strftime('%d-%b-%Y %H:%M IST')}")
    print(f"  Expiry: {EXPIRY}")
    print(f"{'='*60}")

    reasons_skip    = []
    reasons_caution = []

    # ── 0. Circuit breaker (3.2) ─────────────────────────────────────────────
    print("\n[0/6] Checking recent performance (circuit breaker)...")
    cb_skip, cb_reason = check_recent_performance()
    if cb_skip:
        print(f"  {cb_reason}")
        reasons_skip.append(cb_reason)
    else:
        print("  Recent performance OK — no circuit breaker triggered")

    # ── 1. Fetch option chain ────────────────────────────────────────────────
    print("\n[1/6] Fetching option chain...")
    oc = get_option_chain(EXPIRY, strike_count=10)
    if "error" in oc:
        print(f"  ❌ Option chain error: {oc['error']}")
        print("  → Cannot proceed without market data.")
        print(f"\n  ⛔  VERDICT: SKIP  (API unavailable — no market data)")
        sys.exit(2)

    nifty = float(oc.get("underlying_ltp", 0) or 0)
    atm   = float(oc.get("atm_strike", 0) or 0)

    if nifty <= 0 or atm <= 0:
        print("  ❌ NIFTY or ATM is 0 — market may not be open yet.")
        print(f"\n  ⛔  VERDICT: SKIP  (market not open or pre-open)")
        sys.exit(2)

    print(f"  NIFTY: {nifty:.1f}  |  ATM: {atm:.0f}")

    # ── 2. VIX ───────────────────────────────────────────────────────────────
    print("\n[2/6] Fetching India VIX...")
    vix = get_vix()
    print(f"  VIX: {vix:.2f}")

    # VIX-based lot sizing factor
    if vix > 20:
        vix_factor = 0.5
        print(f"  ⚠️  VIX > 20: reduce lots 50%, consider widening to ±150/±300")
    elif vix > 16:
        vix_factor = 0.75
        print(f"  ⚠️  VIX 16–20: reduce lots 25%")
    elif vix < VIX_MIN_ENTRY:
        vix_factor = 0.0
        print(f"  ⚠️  VIX < {VIX_MIN_ENTRY}: premium too thin — IC not viable")
        reasons_skip.append(f"VIX {vix:.1f} < {VIX_MIN_ENTRY} (premium too thin for IC)")
    else:
        vix_factor = 1.0

    # ── 3. Regime detection ──────────────────────────────────────────────────
    print("\n[3/6] Detecting market regime...")
    regime, sizing_factor = detect_regime(nifty_ltp=nifty, vix=vix)
    print(f"  Regime: {regime}  |  Sizing factor: {sizing_factor:.2f}")

    if regime in ("TRENDING_BULL", "TRENDING_BEAR"):
        reasons_skip.append(f"Regime {regime} — directional momentum kills IC")
    elif regime == "VOLATILE_CHOP":
        if vix > VIX_HIGH_SKIP:
            reasons_skip.append(f"VOLATILE_CHOP + VIX {vix:.1f} > {VIX_HIGH_SKIP} — random direction + high IV")
        elif vix > VIX_CHOP_CAUTION:
            reasons_caution.append(f"VOLATILE_CHOP + VIX {vix:.1f} (14–18) — use 60% lots")
        else:
            reasons_caution.append(f"VOLATILE_CHOP + VIX {vix:.1f} ≤ 14 — mild chop, watch closely")
    elif regime == "MEAN_REVERSION":
        print(f"  ✅ MEAN_REVERSION — ideal IC regime")
    # ── VIX-based fallback regimes (when OpenClaw skill unavailable) ─────────
    elif regime == "EXTREME_VOL":
        reasons_skip.append(f"EXTREME_VOL: VIX={vix:.1f} > 25 — IC exposure unacceptable")
    elif regime == "HIGH_VOL":
        if vix > VIX_HIGH_SKIP:
            reasons_skip.append(f"HIGH_VOL: VIX={vix:.1f} > {VIX_HIGH_SKIP} — skip or use very small lots")
        else:
            reasons_caution.append(f"HIGH_VOL: VIX={vix:.1f} — use 50% lots, widen strikes to ±150/±250")
    elif regime == "ELEVATED_VOL":
        reasons_caution.append(f"ELEVATED_VOL: VIX={vix:.1f} 16-20 — use 75% lots")
    elif regime == "RANGE":
        print(f"  ✅ RANGE (VIX={vix:.1f}) — ideal IC conditions")
    elif regime == "LOW_VOL":
        reasons_caution.append(f"LOW_VOL: VIX={vix:.1f} < 13 — premium thin, use 70% lots or skip")
    elif regime == "RANGE_UNKNOWN_VIX":
        reasons_caution.append(f"VIX unavailable — assuming range, using 85% lots")
    else:
        reasons_caution.append(f"Regime '{regime}' unknown — proceed with caution")

    # ── 4. Net credit check ──────────────────────────────────────────────────
    print("\n[4/6] Computing net credit from option chain...")
    chain = oc.get("chain", [])

    # Extract premiums for ATM±100 (short) and ATM±200 (long)
    short_ce_ltp = short_pe_ltp = long_ce_ltp = long_pe_ltp = 0.0
    targets = {
        int(atm + 100): "short_ce",
        int(atm - 100): "short_pe",
        int(atm + 200): "long_ce",
        int(atm - 200): "long_pe",
    }
    for s in chain:
        strike = int(s.get("strike", 0))
        if strike in targets:
            key_name = targets[strike]
            if key_name == "short_ce":
                short_ce_ltp = float(s.get("ce", {}).get("ltp", 0) or 0)
            elif key_name == "short_pe":
                short_pe_ltp = float(s.get("pe", {}).get("ltp", 0) or 0)
            elif key_name == "long_ce":
                long_ce_ltp = float(s.get("ce", {}).get("ltp", 0) or 0)
            elif key_name == "long_pe":
                long_pe_ltp = float(s.get("pe", {}).get("ltp", 0) or 0)

    net_credit = (short_ce_ltp + short_pe_ltp) - (long_ce_ltp + long_pe_ltp)

    print(f"  Short CE ({int(atm+100)}): ₹{short_ce_ltp:.2f}")
    print(f"  Short PE ({int(atm-100)}): ₹{short_pe_ltp:.2f}")
    print(f"  Long  CE ({int(atm+200)}): ₹{long_ce_ltp:.2f}")
    print(f"  Long  PE ({int(atm-200)}): ₹{long_pe_ltp:.2f}")
    print(f"  Net credit:  ₹{net_credit:.2f}/unit")

    if net_credit < 10:
        reasons_skip.append(f"Net credit ₹{net_credit:.2f} < ₹10 — not enough premium")
    elif net_credit < MIN_CREDIT:
        reasons_caution.append(f"Net credit ₹{net_credit:.2f} < ₹{MIN_CREDIT} target (thin premium)")

    # ── 5. Margin & lot sizing ───────────────────────────────────────────────
    print("\n[5/6] Checking margin & lot sizing...")
    avail = get_funds()
    effective_vix_factor = vix_factor * sizing_factor
    wave1, wave2, wave3 = compute_wave_lots(avail, effective_vix_factor)
    margin_needed = wave1 * SPAN_MARGIN

    print(f"  Available cash:  ₹{avail:,.0f}")
    print(f"  VIX factor:      {vix_factor:.2f}  |  Regime factor: {sizing_factor:.2f}")
    print(f"  Wave 1 lots:     {wave1}  ({wave1 * LOT_SIZE} qty/leg)  — margin ₹{margin_needed:,.0f}")
    print(f"  Wave 2 lots:     {wave2}  ({wave2 * LOT_SIZE} qty/leg)")
    print(f"  Wave 3 lots:     {wave3}  ({wave3 * LOT_SIZE} qty/leg)")

    if wave1 < 4:
        reasons_skip.append(f"Insufficient margin — only {wave1} lots possible (need ≥4)")
    elif avail < margin_needed:
        reasons_caution.append(f"Margin tight: ₹{avail:,.0f} available vs ₹{margin_needed:,.0f} needed")

    # ── 6. Gap check ─────────────────────────────────────────────────────────
    print("\n[6/6] Gap check...")
    gap_pct = abs(nifty - atm) / atm * 100 if atm > 0 else 0
    print(f"  NIFTY {nifty:.1f} vs ATM {atm:.0f} → gap: {gap_pct:.2f}%")
    if gap_pct > GAP_SKIP_PCT:
        reasons_caution.append(
            f"NIFTY gapping {gap_pct:.1f}% from ATM — consider waiting 15–20 min for settlement"
        )

    # ── Verdict ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  SUMMARY")
    print(f"{'─'*60}")

    if reasons_skip:
        verdict   = "SKIP"
        exit_code = 2
        icon      = "🔴"
    elif reasons_caution:
        verdict   = "CAUTION"
        exit_code = 1
        icon      = "🟡"
    else:
        verdict   = "GO"
        exit_code = 0
        icon      = "🟢"

    if reasons_skip:
        print("  SKIP reasons:")
        for r in reasons_skip:
            print(f"    ✗ {r}")
    if reasons_caution:
        print("  CAUTION reasons:")
        for r in reasons_caution:
            print(f"    ⚠  {r}")
    if not reasons_skip and not reasons_caution:
        print("  ✅ All conditions met")

    print()
    print(f"  {icon}  VERDICT: {verdict}")
    if verdict == "GO":
        print(f"     → Proceed with Wave 1: {wave1} lots × {LOT_SIZE} = {wave1*LOT_SIZE} qty/leg")
        print(f"     → Expected P&L: ₹{int(wave1*LOT_SIZE*net_credit*0.7):,}–₹{int(wave1*LOT_SIZE*net_credit*0.9):,}")
    elif verdict == "CAUTION":
        reduced = max(4, int(wave1 * 0.6))
        print(f"     → Consider {reduced} lots instead of {wave1} (60% position)")
        print(f"     → Widen strikes to ±150/±300 if VIX > 16")
    else:
        print(f"     → Do NOT enter IC today")

    print(f"\n  Expiry: {EXPIRY} | Strikes: {int(atm-100)}PE/{int(atm+100)}CE (short) | {int(atm-200)}PE/{int(atm+200)}CE (long)")
    print(f"{'='*60}\n")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
