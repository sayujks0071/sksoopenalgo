#!/usr/bin/env python3
"""
NIFTY Iron Condor Strategy Backtester v1.0
==========================================
Backtests the ic_monitor.py strategy using:
  - 2 years of real NIFTY + India VIX daily data (via yfinance)
  - Black-Scholes option pricing for each leg
  - Full simulation of all exit conditions from ic_monitor.py:
      1. Premium capture milestones (75%, 60%+2PM, 50%+proximity)
      2. Gamma zone close (60pt partial, 30pt emergency)
      3. Trailing profit lock (70% of peak)
      4. Per-leg SL (3x initial, adaptive tightening)
      5. VIX spike (+15%)
      6. Premium stop (2x entry credit)
      7. Hard close at 3:10 PM
      8. Max daily loss (₹1,01,000)
  - Realistic intraday simulation using daily OHLCV

Performance targets:
  - Profit Factor > 1.8
  - Max Drawdown < 6%
  - Win rate > 55%
  - Minimum 40 trades

Usage:
    cd ~/sksoopenalgo/openalgo
    python3 ic_backtest.py
    python3 ic_backtest.py --days 365 --lots 12 --verbose
    python3 ic_backtest.py --optimize       # grid search for best params
    python3 ic_backtest.py --report         # detailed trade-by-trade report
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import json
from datetime import datetime, timedelta, date
from typing import List, Dict, Tuple, Optional

import numpy as np
import pandas as pd

# ─── CONFIG (mirrors ic_config.py) ──────────────────────────────────────────
DEFAULT_DAYS          = 400        # ~1.5 years of data
LOT_SIZE              = 65
SPAN_PER_LOT          = 32_000    # MIS margin per IC spread lot
INITIAL_CAPITAL       = 1_688_000 # ₹16.88L (as per risk rule)

# Entry params (configurable for grid search)
SHORT_OFFSET_DEFAULT  = 100       # ATM ± 100 short strikes
LONG_OFFSET_DEFAULT   = 200       # ATM ± 200 long wings
WAVE1_LOTS_DEFAULT    = 12        # Wave 1 lots (matches live system)

# Exit params (from ic_config.py)
PREMIUM_CLOSE_PCT     = 0.75      # 75% capture → close all
PREMIUM_CLOSE_AFTER   = 0.60      # 60% + after 2PM → close all
PREMIUM_CLOSE_PROX    = 0.50      # 50% + within 50pt → close all
PREMIUM_STOP_MULTIPLE = 2.0       # max loss = 2x entry credit
GAMMA_ZONE_PARTIAL    = 60        # 60pt → close that side
GAMMA_ZONE_FULL       = 30        # 30pt → emergency close all
TRAIL_LOCK_THRESHOLD  = 40_000    # activate trailing at ₹40K peak
TRAIL_LOCK_PCT        = 0.70      # protect 70% of peak
VIX_SPIKE_TRIGGER     = 0.15      # VIX +15% → close
PER_LEG_SL_INITIAL    = 3.0       # 3x avg (NOT 2x — the bug)
PER_LEG_SL_AFTER_60   = 2.5       # after 60% captured
PER_LEG_SL_AFTER_2PM  = 2.0       # after 2 PM
PER_LEG_SL_PORTFOLIO_GUARD = True  # skip per-leg SL if portfolio < -30%
MIN_ENTRY_DISTANCE    = 100       # NIFTY must be > 100pt from shorts
WIDEN_SHORT_OFFSET    = 150       # fallback when < 100pt
MAX_DAILY_LOSS        = -101_000
VIX_MIN_ENTRY         = 13.0      # skip if VIX < this

# Costs (conservative)
BROKERAGE_PER_LOT     = 40        # ₹40 per lot round trip (both legs)
SLIPPAGE_PER_CONTRACT = 0.50      # ₹0.50/contract slippage (market order)

# Intraday simulation params
INTRADAY_STEPS        = 12        # simulate 12 time steps per day (9:20→3:10)
INTRADAY_HOURS        = [
    (9,20), (9,45), (10,15), (10,45), (11,15), (11,30),
    (12,00), (12,30), (13,00), (14,00), (14,30), (15,10)
]

# ─── BLACK-SCHOLES PRICING ───────────────────────────────────────────────────

def _bsm_d1(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bsm_price(S: float, K: float, T: float, r: float, sigma: float,
               opt_type: str) -> float:
    """Black-Scholes option price.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate (use 0.065 for India)
        sigma: Implied volatility (annualized, decimal)
        opt_type: 'CE' or 'PE'

    Returns:
        Option price (≥ intrinsic value, ≥ 0.05)
    """
    if T <= 0:
        # At expiry — intrinsic only
        if opt_type == "CE":
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)

    d1 = _bsm_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)

    if opt_type == "CE":
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

    return max(0.05, price)  # minimum tick


def ic_entry_credit(S: float, short_offset: int, long_offset: int,
                    T: float, sigma: float, r: float = 0.065) -> Tuple[float, float, float, float]:
    """Compute IC entry net credit (per unit).

    Returns: (net_credit, short_ce_price, short_pe_price, long_ce_price, long_pe_price)
    """
    atm     = round(S / 50) * 50

    # Apply MIN_ENTRY_DISTANCE check
    std_dist_ce = (atm + short_offset) - S
    std_dist_pe = S - (atm - short_offset)
    if std_dist_ce < MIN_ENTRY_DISTANCE or std_dist_pe < MIN_ENTRY_DISTANCE:
        short_offset = WIDEN_SHORT_OFFSET
        long_offset  = WIDEN_SHORT_OFFSET + 100

    short_ce_strike = atm + short_offset
    short_pe_strike = atm - short_offset
    long_ce_strike  = atm + long_offset
    long_pe_strike  = atm - long_offset

    short_ce = bsm_price(S, short_ce_strike, T, r, sigma, "CE")
    short_pe = bsm_price(S, short_pe_strike, T, r, sigma, "PE")
    long_ce  = bsm_price(S, long_ce_strike,  T, r, sigma, "CE")
    long_pe  = bsm_price(S, long_pe_strike,  T, r, sigma, "PE")

    net_credit = (short_ce + short_pe) - (long_ce + long_pe)

    return (net_credit, short_ce_strike, short_pe_strike,
            long_ce_strike, long_pe_strike,
            short_ce, short_pe, long_ce, long_pe)


def ic_current_value(S: float, short_ce_strike: float, short_pe_strike: float,
                     long_ce_strike: float, long_pe_strike: float,
                     entry_short_ce: float, entry_short_pe: float,
                     entry_long_ce: float, entry_long_pe: float,
                     T: float, sigma: float, r: float = 0.065) -> float:
    """Current IC value (positive = profit).

    MTM = entry_net_credit - current_net_credit
    """
    cur_short_ce = bsm_price(S, short_ce_strike, T, r, sigma, "CE")
    cur_short_pe = bsm_price(S, short_pe_strike, T, r, sigma, "PE")
    cur_long_ce  = bsm_price(S, long_ce_strike,  T, r, sigma, "CE")
    cur_long_pe  = bsm_price(S, long_pe_strike,  T, r, sigma, "PE")

    entry_net = (entry_short_ce + entry_short_pe) - (entry_long_ce + entry_long_pe)
    cur_net   = (cur_short_ce  + cur_short_pe)  - (cur_long_ce  + cur_long_pe)

    # MTM per unit = entry_net - current_net (we collected entry_net, current cost to close is cur_net)
    return entry_net - cur_net


# ─── DATA FETCHING ───────────────────────────────────────────────────────────

def fetch_nifty_vix(days: int = 400) -> pd.DataFrame:
    """Fetch NIFTY + VIX daily data via yfinance. Returns merged DataFrame."""
    import yfinance as yf

    print(f"📥 Fetching {days} days of NIFTY + VIX data...", flush=True)
    nifty = yf.download("^NSEI",     period=f"{days}d", interval="1d", progress=False)
    vix   = yf.download("^INDIAVIX", period=f"{days}d", interval="1d", progress=False)

    # Flatten multi-level columns
    nifty.columns = [c[0] for c in nifty.columns]
    vix.columns   = [c[0] for c in vix.columns]

    # Merge on date index
    df = nifty[["Open", "High", "Low", "Close"]].copy()
    df.columns = ["n_open", "n_high", "n_low", "n_close"]
    df["vix"]  = vix["Close"]

    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    print(f"   {len(df)} trading days loaded ({df.index[0].date()} → {df.index[-1].date()})", flush=True)
    return df


def get_thursday_expiries(df: pd.DataFrame) -> List[date]:
    """Return all Thursday expiry dates in the data range (weekly NIFTY expiry)."""
    thursdays = []
    for d in df.index:
        if d.weekday() == 3:  # Thursday
            thursdays.append(d.date())
    return sorted(thursdays)


# ─── INTRADAY SIMULATION ─────────────────────────────────────────────────────

def simulate_intraday_path(open_price: float, high: float, low: float,
                            close: float, vix: float, n_steps: int = 12,
                            seed: int = None) -> List[Tuple[int, int, float, float]]:
    """Simulate intraday NIFTY path as (hour, minute, price, sigma_iv).

    Uses daily range to calibrate intraday vol. Returns time-price pairs.
    Heuristic: prices follow a GBM constrained to [low, high].
    """
    if seed is not None:
        np.random.seed(seed)

    daily_range = high - low
    intraday_vol = (daily_range / open_price) / math.sqrt(n_steps) * 0.8  # 80% of realized

    # Convert VIX to PER-STEP sigma.
    # BUG FIX: daily_sigma must be divided by √n_steps to get per-step sigma.
    # Previously daily_sigma was applied to each step unchanged, making NIFTY
    # move a full day's worth of volatility in each 25-minute step (12× too fast).
    # Correct: per-step vol = annual_vol / √(252 × n_steps_per_day).
    daily_sigma  = (vix / 100) / math.sqrt(252)           # one full day's vol
    step_sigma   = daily_sigma / math.sqrt(n_steps)        # per 25-min step

    prices = [open_price]
    sigma = max(intraday_vol, step_sigma)

    for _ in range(n_steps - 1):
        ret = np.random.normal(0, sigma)
        next_p = prices[-1] * (1 + ret)
        # Soft-clamp to daily range (not hard — allow slight breaches intraday)
        next_p = max(low * 0.998, min(high * 1.002, next_p))
        prices.append(next_p)

    # Force last price toward actual close
    if len(prices) >= 4:
        prices[-1] = close

    # Pair with time slots
    steps = INTRADAY_HOURS[:n_steps]
    while len(steps) < len(prices):
        steps.append((15, 10))

    result = []
    for i, (price, (h, m)) in enumerate(zip(prices, steps)):
        # IV (sigma): start with historical vol, allow intraday variation
        iv = vix / 100 * (1 + np.random.normal(0, 0.02))  # small IV noise
        iv = max(0.08, min(0.60, iv))  # clamp to [8%, 60%]
        result.append((h, m, price, iv))

    return result


# ─── BACKTEST CORE ───────────────────────────────────────────────────────────

class ICBacktest:
    def __init__(self, short_offset: int = SHORT_OFFSET_DEFAULT,
                 long_offset: int = LONG_OFFSET_DEFAULT,
                 lots: int = WAVE1_LOTS_DEFAULT,
                 verbose: bool = False,
                 weekly_hold: bool = False):
        self.short_offset  = short_offset
        self.long_offset   = long_offset
        self.lots          = lots
        self.verbose       = verbose
        self.weekly_hold   = weekly_hold   # True = NRML (hold Mon→Thu); False = MIS (intraday)
        self.trades: List[Dict] = []

    def _entry_time_to_T(self, hour: int, minute: int, expiry_date: date) -> float:
        """Time to expiry in years from given hour:minute on entry day."""
        # Trading days remaining (approximate)
        entry_dt = datetime.combine(expiry_date, datetime.min.time()).replace(
            hour=hour, minute=minute
        )
        # Business days from entry to expiry close (3:30 PM)
        close_dt = datetime.combine(expiry_date, datetime.min.time()).replace(
            hour=15, minute=30
        )
        delta_hours = (close_dt - entry_dt).total_seconds() / 3600
        return max(delta_hours / (365 * 6.5), 1/365/24)  # min 1 hour

    def _time_to_T(self, hour: int, minute: int,
                   entry_date: date, expiry_date: date) -> float:
        """Days between current time and expiry, in years."""
        entry_dt  = datetime(entry_date.year, entry_date.month, entry_date.day,
                             hour, minute)
        expiry_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day,
                             15, 30)
        delta_secs = (expiry_dt - entry_dt).total_seconds()
        return max(delta_secs / (365 * 24 * 3600), 1/(365*24))

    def simulate_week(self, week_days: pd.DataFrame, expiry: date,
                      week_seed: int = 42) -> Optional[Dict]:
        """Simulate an IC INTRADAY trade (MIS) — entry at 9:20 AM, hard-close 3:10 PM, SAME DAY.

        The live ic_monitor strategy uses MIS product which mandates same-day close.
        T (time-to-expiry) still reflects real calendar days to Thursday expiry so
        BSM option pricing is realistic, but the price simulation only runs the
        entry day's intraday session (9:20–15:10).

        Returns trade dict or None if no entry taken.
        """
        # ── Entry: Monday (or Tuesday if Monday is holiday) at 9:20 AM ──────
        entry_day = None
        for idx, row in week_days.iterrows():
            if idx.weekday() == 0:   # Monday
                entry_day = idx
                entry_row = row
                break
        if entry_day is None:
            # Use first available day of the week
            entry_day = week_days.index[0]
            entry_row = week_days.iloc[0]

        open_p = float(entry_row["n_open"])
        vix    = float(entry_row["vix"])

        # ── Pre-entry checks (mirrors ic_pre_entry.py) ────────────────────
        # Skip if VIX out of range
        if vix < VIX_MIN_ENTRY:
            if self.verbose:
                print(f"   {entry_day.date()}: SKIP (VIX={vix:.1f} < {VIX_MIN_ENTRY})")
            return None
        if vix > 25:
            if self.verbose:
                print(f"   {entry_day.date()}: SKIP (VIX={vix:.1f} > 25)")
            return None

        # ── Compute IC entry params ────────────────────────────────────────
        sigma  = vix / 100   # use VIX as proxy for ATM IV
        T_entry = self._time_to_T(9, 20, entry_day.date(), expiry)

        result = ic_entry_credit(open_p, self.short_offset, self.long_offset,
                                  T_entry, sigma)
        (net_credit_per_unit, short_ce_strike, short_pe_strike,
         long_ce_strike, long_pe_strike,
         entry_short_ce, entry_short_pe, entry_long_ce, entry_long_pe) = result

        # Skip if net credit too thin
        if net_credit_per_unit < 15:
            if self.verbose:
                print(f"   {entry_day.date()}: SKIP (credit ₹{net_credit_per_unit:.1f}/unit < ₹15)")
            return None

        qty             = self.lots * LOT_SIZE
        entry_premium   = net_credit_per_unit * qty  # total net credit in ₹

        if self.verbose:
            print(f"\n   📅 Entry {entry_day.date()} | NIFTY={open_p:.0f} VIX={vix:.1f}"
                  f" | Credit=₹{net_credit_per_unit:.1f}/u = ₹{entry_premium:,.0f} total"
                  f" | Strikes CE={short_ce_strike}/{long_ce_strike} PE={short_pe_strike}/{long_pe_strike}")

        # ── Simulate intraday on entry day only (MIS: must close by 3:10 PM) ─
        peak_mtm   = 0.0
        mae        = 0.0
        exit_mtm   = 0.0
        exit_reason = "HARD_CLOSE"
        exit_date  = expiry
        vix_entry  = vix

        trade_open = True
        day_idx    = 0

        for sim_date, row in week_days.iterrows():
            if not trade_open:
                break

            # ── MIS vs NRML hold mode ─────────────────────────────────────
            # MIS (default): broker forces close by 3:10 PM on entry day only.
            # NRML (--weekly): hold Mon→Thu; simulate all days until expiry.
            if not self.weekly_hold and sim_date.date() != entry_day.date():
                break

            day_idx += 1

            is_expiry = sim_date.date() == expiry
            intraday_vix = float(row["vix"])

            # Simulate intraday path for this day
            path = simulate_intraday_path(
                open_price=float(row["n_open"]),
                high=float(row["n_high"]),
                low=float(row["n_low"]),
                close=float(row["n_close"]),
                vix=intraday_vix,
                n_steps=len(INTRADAY_HOURS),
                seed=week_seed + day_idx
            )

            for (h, m, nifty, iv_now) in path:
                if not trade_open:
                    break

                # Skip before entry time on entry day
                if sim_date == entry_day and (h, m) < (9, 20):
                    continue

                T_now = self._time_to_T(h, m, sim_date.date(), expiry)

                # Adjust IV slightly for intraday VIX dynamics
                iv_adj = iv_now * (1 + (intraday_vix - vix_entry) / vix_entry * 0.3)
                iv_adj = max(0.08, min(0.60, iv_adj))

                # Current IC MTM (per unit, then scaled by qty)
                mtm_per_unit = ic_current_value(
                    nifty,
                    short_ce_strike, short_pe_strike,
                    long_ce_strike, long_pe_strike,
                    entry_short_ce, entry_short_pe,
                    entry_long_ce, entry_long_pe,
                    T_now, iv_adj
                )
                mtm = mtm_per_unit * qty

                if mtm > peak_mtm:
                    peak_mtm = mtm
                if mtm < mae:
                    mae = mtm

                pct_captured = mtm / entry_premium if entry_premium > 0 else 0

                # ── Check exit conditions (mirrors check_dynamic_exit) ────
                reason = None

                # 1. Premium capture milestones
                if pct_captured >= PREMIUM_CLOSE_PCT:
                    reason = f"Premium capture {pct_captured:.1%}"
                elif pct_captured >= PREMIUM_CLOSE_AFTER and (h, m) >= (14, 0):
                    reason = f"Premium {pct_captured:.1%} after 2PM"
                elif pct_captured >= PREMIUM_CLOSE_PROX:
                    if (short_ce_strike > 0 and abs(nifty - short_ce_strike) < 50):
                        reason = f"Premium {pct_captured:.1%} + near short CE"
                    elif (short_pe_strike > 0 and abs(nifty - short_pe_strike) < 50):
                        reason = f"Premium {pct_captured:.1%} + near short PE"

                # 2. Gamma zone close
                if reason is None:
                    dist_ce = short_ce_strike - nifty
                    dist_pe = nifty - short_pe_strike
                    if dist_ce <= GAMMA_ZONE_FULL or dist_pe <= GAMMA_ZONE_FULL:
                        reason = f"Emergency gamma zone (dist_CE={dist_ce:.0f} dist_PE={dist_pe:.0f})"
                    elif dist_ce <= GAMMA_ZONE_PARTIAL or dist_pe <= GAMMA_ZONE_PARTIAL:
                        reason = f"Gamma zone partial (dist_CE={dist_ce:.0f} dist_PE={dist_pe:.0f})"

                # 3. Trailing profit lock
                if reason is None and peak_mtm >= TRAIL_LOCK_THRESHOLD:
                    floor = peak_mtm * TRAIL_LOCK_PCT
                    if mtm < floor:
                        reason = f"Trail lock: {mtm:+.0f} < floor {floor:.0f}"

                # 4. Per-leg SL (short CE or PE LTP vs avg)
                if reason is None:
                    cur_short_ce_ltp = bsm_price(nifty, short_ce_strike, T_now, 0.065, iv_adj, "CE")
                    cur_short_pe_ltp = bsm_price(nifty, short_pe_strike, T_now, 0.065, iv_adj, "PE")
                    portfolio_loss_pct = mtm / entry_premium if entry_premium > 0 else 0
                    if not PER_LEG_SL_PORTFOLIO_GUARD or portfolio_loss_pct <= -0.30:
                        sl_mult = PER_LEG_SL_INITIAL
                        if pct_captured >= 0.60:
                            sl_mult = PER_LEG_SL_AFTER_60
                        if (h, m) >= (14, 0):
                            sl_mult = PER_LEG_SL_AFTER_2PM
                        if cur_short_ce_ltp >= entry_short_ce * sl_mult:
                            reason = f"Per-leg SL: CE LTP {cur_short_ce_ltp:.1f} >= {sl_mult}x avg {entry_short_ce:.1f}"
                        elif cur_short_pe_ltp >= entry_short_pe * sl_mult:
                            reason = f"Per-leg SL: PE LTP {cur_short_pe_ltp:.1f} >= {sl_mult}x avg {entry_short_pe:.1f}"

                # 5. VIX spike
                if reason is None and vix_entry > 0 and intraday_vix > 0:
                    vix_rise = (intraday_vix - vix_entry) / vix_entry
                    if vix_rise >= VIX_SPIKE_TRIGGER:
                        reason = f"VIX spike {intraday_vix:.1f} vs entry {vix_entry:.1f} (+{vix_rise:.1%})"

                # 6. Premium stop (2x entry)
                if reason is None:
                    prem_stop = -(entry_premium * PREMIUM_STOP_MULTIPLE)
                    if mtm < prem_stop:
                        reason = f"Premium stop: {mtm:+.0f} < 2x entry {entry_premium:,.0f}"

                # 7. Max daily loss
                if reason is None and mtm < MAX_DAILY_LOSS:
                    reason = f"Max daily loss: {mtm:+.0f}"

                # 8. Hard close at 3:10 PM
                if (h, m) >= (15, 10):
                    reason = reason or "Hard close 3:10PM"

                if reason:
                    exit_mtm    = mtm
                    exit_reason = reason
                    exit_date   = sim_date.date()
                    trade_open  = False
                    if self.verbose:
                        print(f"   🔴 EXIT: {sim_date.date()} {h:02d}:{m:02d} | "
                              f"MTM={mtm:+,.0f} | {reason}")
                    break

            # If still open on expiry day at EOD, close at intrinsic
            if trade_open and is_expiry:
                # Expiry close: most ICs expire worthless if NIFTY stayed in range
                close_p = float(row["n_close"])
                T_exp   = 1 / (365 * 24)  # ~1 hour to expiry
                final_val = ic_current_value(
                    close_p, short_ce_strike, short_pe_strike,
                    long_ce_strike, long_pe_strike,
                    entry_short_ce, entry_short_pe,
                    entry_long_ce, entry_long_pe,
                    T_exp, max(0.10, intraday_vix / 100)
                )
                exit_mtm    = final_val * qty
                exit_reason = "Expiry"
                exit_date   = expiry
                trade_open  = False

        # ── Compute costs ─────────────────────────────────────────────────
        slippage = SLIPPAGE_PER_CONTRACT * qty * 4   # 4 legs
        brokerage = BROKERAGE_PER_LOT * self.lots * 2  # entry + exit
        net_pnl = exit_mtm - slippage - brokerage

        pct_captured = exit_mtm / entry_premium if entry_premium > 0 else 0

        trade = {
            "entry_date":       str(entry_day.date()),
            "exit_date":        str(exit_date),
            "expiry":           str(expiry),
            "entry_price":      round(open_p, 1),
            "short_ce":         int(short_ce_strike),
            "short_pe":         int(short_pe_strike),
            "long_ce":          int(long_ce_strike),
            "long_pe":          int(long_pe_strike),
            "vix_entry":        round(vix_entry, 2),
            "lots":             self.lots,
            "entry_premium":    round(entry_premium, 0),
            "exit_mtm":         round(exit_mtm, 0),
            "slippage":         round(slippage, 0),
            "brokerage":        round(brokerage, 0),
            "net_pnl":          round(net_pnl, 0),
            "pct_captured":     round(pct_captured, 4),
            "peak_mtm":         round(peak_mtm, 0),
            "mae":              round(mae, 0),
            "exit_reason":      exit_reason,
            "win":              net_pnl > 0,
        }
        return trade

    def run(self, df: pd.DataFrame) -> List[Dict]:
        """Run backtest across all weeks in dataset."""
        thursdays  = get_thursday_expiries(df)
        self.trades = []

        print(f"\n🏃 Running IC backtest: {len(thursdays)} weekly expiries "
              f"| shorts=±{self.short_offset} longs=±{self.long_offset} lots={self.lots}", flush=True)

        for i, expiry in enumerate(thursdays):
            # Get this week's trading days (Mon–Thu)
            week_start = expiry - timedelta(days=3)  # Monday
            week_mask  = (df.index.date >= week_start) & (df.index.date <= expiry)
            week_days  = df[week_mask]

            if len(week_days) == 0:
                continue

            trade = self.simulate_week(week_days, expiry, week_seed=i * 17 + 42)
            if trade is not None:
                self.trades.append(trade)

        return self.trades


# ─── PERFORMANCE METRICS ─────────────────────────────────────────────────────

def compute_metrics(trades: List[Dict], capital: float = INITIAL_CAPITAL) -> Dict:
    """Compute full performance metrics for a set of trades."""
    if not trades:
        return {"error": "no_trades", "profit_factor": 0, "max_drawdown_pct": 100}

    pnls       = [t["net_pnl"] for t in trades]
    gross_wins = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    net_pnl    = sum(pnls)
    win_count  = sum(1 for p in pnls if p > 0)
    total      = len(pnls)
    win_rate   = win_count / total if total > 0 else 0

    profit_factor = gross_wins / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown
    equity     = [capital]
    for p in pnls:
        equity.append(equity[-1] + p)
    equity_arr   = np.array(equity)
    running_max  = np.maximum.accumulate(equity_arr)
    drawdowns    = (equity_arr - running_max) / running_max * 100
    max_drawdown = abs(float(np.min(drawdowns)))

    # Expectancy
    avg_win  = gross_wins / win_count if win_count > 0 else 0
    avg_loss = gross_loss / (total - win_count) if (total - win_count) > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Annualized return
    trading_weeks = total
    annual_trades = trading_weeks * (52 / max(1, trading_weeks)) * (trading_weeks / 52)
    ann_return_pct = (net_pnl / capital) * (52 / max(1, trading_weeks / 1)) * 100

    # Sharpe-like ratio (weekly)
    weekly_ret = [p / capital for p in pnls]
    sharpe = np.mean(weekly_ret) / np.std(weekly_ret) * math.sqrt(52) if np.std(weekly_ret) > 0 else 0

    return {
        "total_trades":    total,
        "win_rate":        round(win_rate, 4),
        "profit_factor":   round(profit_factor, 3),
        "gross_wins":      round(gross_wins, 0),
        "gross_loss":      round(gross_loss, 0),
        "net_pnl":         round(net_pnl, 0),
        "avg_win":         round(avg_win, 0),
        "avg_loss":        round(avg_loss, 0),
        "expectancy":      round(expectancy, 0),
        "max_drawdown_pct":round(max_drawdown, 3),
        "ann_return_pct":  round(ann_return_pct, 2),
        "sharpe_weekly":   round(sharpe, 3),
        "final_capital":   round(equity[-1], 0),
        "targets_met": {
            "profit_factor":    profit_factor >= 1.8,
            "drawdown":         max_drawdown < 6.0,
            "min_trades":       total >= 40,
            "win_rate":         win_rate >= 0.55,
        }
    }


def print_metrics(m: Dict, label: str = "", short_offset: int = 100,
                  long_offset: int = 200, lots: int = 12):
    """Print formatted metrics summary."""
    ok = "✅" if m.get("profit_factor", 0) >= 1.8 else "❌"
    dd = "✅" if m.get("max_drawdown_pct", 100) < 6.0 else "❌"
    header = f"\n{'─'*70}"
    if label:
        header += f"\n  {label}"
    header += f"\n  Config: shorts=±{short_offset} longs=±{long_offset} lots={lots}"
    print(header)
    print(f"  Trades:         {m['total_trades']}")
    print(f"  Win Rate:       {m['win_rate']:.1%}")
    print(f"  Profit Factor:  {m['profit_factor']:.3f}  {ok}  (target ≥ 1.8)")
    print(f"  Max Drawdown:   {m['max_drawdown_pct']:.2f}%  {dd}  (target < 6%)")
    print(f"  Net P&L:        ₹{m['net_pnl']:>10,.0f}")
    print(f"  Avg Win:        ₹{m['avg_win']:>10,.0f}")
    print(f"  Avg Loss:       ₹{m['avg_loss']:>10,.0f}")
    print(f"  Expectancy:     ₹{m['expectancy']:>10,.0f}/trade")
    print(f"  Ann. Return:    {m['ann_return_pct']:.1f}%")
    print(f"  Sharpe (wkly):  {m['sharpe_weekly']:.3f}")
    print(f"  Final Capital:  ₹{m['final_capital']:>12,.0f}")
    all_pass = all(m.get("targets_met", {}).values())
    print(f"\n  {'✅ ALL TARGETS MET' if all_pass else '⚠️  TARGETS NOT ALL MET'}")
    targets = m.get("targets_met", {})
    for k, v in targets.items():
        print(f"     {'✅' if v else '❌'} {k}")
    print(f"{'─'*70}")


def print_trade_report(trades: List[Dict]):
    """Print detailed trade-by-trade report."""
    print(f"\n{'─'*95}")
    print(f"{'#':>3} {'Entry':>10} {'Expiry':>10} {'NIFTY':>7} {'VIX':>5} "
          f"{'CE/PE':>11} {'Credit':>8} {'Net P&L':>9} {'Captured':>9} {'Exit Reason'}")
    print(f"{'─'*95}")
    for i, t in enumerate(trades, 1):
        strike_str = f"{t['short_ce']}/{t['short_pe']}"
        pnl_str    = f"₹{t['net_pnl']:>+8,.0f}"
        capt_str   = f"{t['pct_captured']:>+7.1%}"
        print(f"{i:>3} {t['entry_date']:>10} {t['expiry']:>10} {t['entry_price']:>7.0f} "
              f"{t['vix_entry']:>5.1f} {strike_str:>11} ₹{t['entry_premium']:>7,.0f} "
              f"{pnl_str} {capt_str} {t['exit_reason'][:35]}")
    print(f"{'─'*95}")


# ─── GRID SEARCH OPTIMIZER ───────────────────────────────────────────────────

def run_grid_search(df: pd.DataFrame, weekly_hold: bool = False) -> pd.DataFrame:
    """Test all parameter combinations and find optimal config."""
    results = []

    if weekly_hold:
        # NRML weekly hold: shorts can be tighter since theta accumulates 4 days
        short_offsets = [80, 100, 120, 150, 200, 250]
        long_offsets  = [200, 250, 300, 350]
        lot_sizes     = [8, 10, 12, 15]
    else:
        # MIS intraday: must use very wide shorts — NIFTY sigma ~200–300pt/day
        short_offsets = [100, 150, 200, 250, 300, 350]
        long_offsets  = [250, 300, 350, 400, 450]
        lot_sizes     = [6, 8, 10, 12]

    total = len(short_offsets) * len(long_offsets) * len(lot_sizes)
    print(f"\n🔍 Grid search: {total} configurations...", flush=True)

    best_score = -float("inf")
    best_params = None
    best_metrics = None

    for i, (so, lo, lots) in enumerate([
        (so, lo, ls)
        for so in short_offsets
        for lo in long_offsets
        for ls in lot_sizes
    ], 1):
        if lo <= so:  # long must be further out than short
            continue

        bt = ICBacktest(short_offset=so, long_offset=lo, lots=lots, weekly_hold=weekly_hold)
        trades = bt.run(df)
        if not trades:
            continue

        m = compute_metrics(trades, INITIAL_CAPITAL)
        pf = m["profit_factor"]
        dd = m["max_drawdown_pct"]
        wr = m["win_rate"]
        nt = m["total_trades"]

        # Score: maximize PF while keeping DD < 6%
        # Penalize DD > 5% and PF < 1.8
        dd_penalty = max(0, dd - 5.0) * 0.5
        pf_score   = min(pf, 4.0)  # cap at 4x to avoid overfitting
        score = pf_score * wr * (1 - dd_penalty / 10)

        status = "✅" if (pf >= 1.8 and dd < 6.0 and nt >= 40) else ""

        results.append({
            "short_offset": so, "long_offset": lo, "lots": lots,
            "profit_factor": round(pf, 3), "max_drawdown_pct": round(dd, 2),
            "win_rate": round(wr, 3), "total_trades": nt,
            "net_pnl": round(m["net_pnl"], 0), "ann_return_pct": round(m["ann_return_pct"], 1),
            "score": round(score, 4), "status": status
        })

        if score > best_score:
            best_score = score
            best_params = (so, lo, lots)
            best_metrics = m

        if i % 10 == 0:
            print(f"   [{i:>3}/{total}] Best so far: "
                  f"shorts=±{best_params[0]} longs=±{best_params[1]} lots={best_params[2]} "
                  f"PF={best_metrics['profit_factor']:.2f} DD={best_metrics['max_drawdown_pct']:.1f}%", flush=True)

    results_df = pd.DataFrame(results).sort_values("score", ascending=False)
    return results_df, best_params, best_metrics


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NIFTY IC Strategy Backtester")
    parser.add_argument("--days",     type=int,   default=DEFAULT_DAYS,   help="History days to use")
    parser.add_argument("--lots",     type=int,   default=WAVE1_LOTS_DEFAULT, help="Wave 1 lots")
    parser.add_argument("--short",    type=int,   default=SHORT_OFFSET_DEFAULT, help="Short offset (ATM±x)")
    parser.add_argument("--long",     type=int,   default=LONG_OFFSET_DEFAULT,  help="Long offset (ATM±x)")
    parser.add_argument("--verbose",  action="store_true", help="Show per-trade details")
    parser.add_argument("--optimize", action="store_true", help="Run grid search optimization")
    parser.add_argument("--report",   action="store_true", help="Print trade-by-trade report")
    parser.add_argument("--weekly",   action="store_true", help="Simulate NRML weekly hold (Mon→Thu) instead of MIS intraday")
    parser.add_argument("--save",     type=str,   default="",            help="Save results to JSON")
    args = parser.parse_args()

    # ── Fetch data ───────────────────────────────────────────────────────────
    try:
        df = fetch_nifty_vix(args.days)
    except Exception as e:
        print(f"❌ Failed to fetch data: {e}")
        sys.exit(1)

    if len(df) < 20:
        print(f"❌ Insufficient data ({len(df)} rows)")
        sys.exit(1)

    hold_label = "NRML weekly (Mon→Thu)" if args.weekly else "MIS intraday (same day)"
    print(f"\n📋 Hold mode: {hold_label}")

    if args.optimize:
        # ── Grid search ──────────────────────────────────────────────────────
        results_df, best_params, best_metrics = run_grid_search(df, weekly_hold=args.weekly)

        print(f"\n{'═'*75}")
        print(f"  GRID SEARCH RESULTS — Top 10 Configurations")
        print(f"{'═'*75}")
        top10 = results_df.head(10)
        for _, row in top10.iterrows():
            print(f"  {row.get('status','  '):2} shorts=±{row['short_offset']:3d} "
                  f"longs=±{row['long_offset']:3d} lots={row['lots']:2d} | "
                  f"PF={row['profit_factor']:.2f} DD={row['max_drawdown_pct']:.1f}% "
                  f"WR={row['win_rate']:.0%} trades={row['total_trades']:3d} "
                  f"P&L=₹{row['net_pnl']:>9,.0f} Ret={row['ann_return_pct']:.0f}%")

        print(f"\n  🏆 Best Config: shorts=±{best_params[0]} longs=±{best_params[1]} lots={best_params[2]}")
        print_metrics(best_metrics, "BEST CONFIGURATION",
                      best_params[0], best_params[1], best_params[2])

        # Also print all configs that meet ALL targets
        qualified = results_df[
            (results_df["profit_factor"] >= 1.8) &
            (results_df["max_drawdown_pct"] < 6.0) &
            (results_df["total_trades"] >= 40)
        ]
        if not qualified.empty:
            print(f"\n  ✅ CONFIGS MEETING ALL TARGETS (PF≥1.8 DD<6% trades≥40):")
            for _, row in qualified.iterrows():
                print(f"    shorts=±{row['short_offset']:3d} longs=±{row['long_offset']:3d} "
                      f"lots={row['lots']:2d} | PF={row['profit_factor']:.2f} "
                      f"DD={row['max_drawdown_pct']:.1f}% WR={row['win_rate']:.0%} "
                      f"Ret={row['ann_return_pct']:.0f}% P&L=₹{row['net_pnl']:>9,.0f}")
        else:
            print(f"\n  ⚠️  No config met all targets simultaneously.")
            print(f"  Best PF config: PF={results_df.iloc[0]['profit_factor']:.2f} "
                  f"DD={results_df.iloc[0]['max_drawdown_pct']:.1f}%")

        if args.save:
            results_df.to_json(args.save, orient="records", indent=2)
            print(f"\n  💾 Results saved to {args.save}")

    else:
        # ── Single backtest run ───────────────────────────────────────────────
        bt = ICBacktest(short_offset=args.short, long_offset=args.long,
                        lots=args.lots, verbose=args.verbose,
                        weekly_hold=args.weekly)
        trades = bt.run(df)

        if not trades:
            print("❌ No trades generated")
            sys.exit(1)

        m = compute_metrics(trades, INITIAL_CAPITAL)
        print_metrics(m, "NIFTY IRON CONDOR — v3 STRATEGY",
                      args.short, args.long, args.lots)

        if args.report:
            print_trade_report(trades)

        if args.save:
            output = {"metrics": m, "trades": trades,
                      "config": {"short_offset": args.short, "long_offset": args.long,
                                 "lots": args.lots, "days": args.days}}
            with open(args.save, "w") as f:
                json.dump(output, f, indent=2)
            print(f"\n💾 Results saved to {args.save}")

        # Exit code reflects whether targets are met
        targets = m.get("targets_met", {})
        if all(targets.values()):
            sys.exit(0)
        else:
            sys.exit(2)   # partial pass


if __name__ == "__main__":
    main()
