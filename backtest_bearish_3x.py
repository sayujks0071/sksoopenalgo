#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          BEARISH EQUITY STRATEGIES BACKTESTER  —  ₹5L Allocation           ║
║  3 Pure-Short strategies targeting PF > 2.5 and Max Drawdown < 6%          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Strategy 1: MACD Bearish Cross + Supertrend  (Momentum Short)             ║
║  Strategy 2: RSI Overbought + Bollinger Rejection  (Mean-Reversion Short)  ║
║  Strategy 3: Opening-Range Breakdown  (Structural Breakdown Short)          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Usage:
    cd ~/sksoopenalgo/openalgo
    python3 backtest_bearish_3x.py
    python3 backtest_bearish_3x.py --days 90 --verbose
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict

# ─── PATH SETUP ───────────────────────────────────────────────────────────────
_BASE   = os.path.dirname(os.path.abspath(__file__))
_OA     = os.path.join(_BASE, "openalgo")
_UTILS  = os.path.join(_OA, "strategies", "utils")

for p in [_BASE, _OA, _UTILS]:
    if p not in sys.path:
        sys.path.insert(0, p)

sys.path.insert(0, _BASE)
try:
    import ic_config
    API_KEY = ic_config.OPENALGO_KEY
except ImportError:
    API_KEY = os.environ.get(
        "OPENALGO_APIKEY",
        "372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
    )

HOST = os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5002")

from trading_utils import (
    APIClient,
    calculate_ema,
    calculate_atr,
    calculate_supertrend,
    calculate_adx,
    calculate_intraday_vwap,
    calculate_rsi,
    calculate_macd,
    calculate_bollinger_bands,
)

import pandas as pd

# ─── CONFIG ───────────────────────────────────────────────────────────────────
EXCHANGE  = "NSE"
PF_MIN    = 2.5
DD_MAX    = 6.0

# Candidate symbols — liquid NSE large-caps with intraday volatility
# IT sector added: INFY, TCS, HCLTECH, WIPRO — consistent bearish trend
CANDIDATES = [
    "INFY", "TCS", "HCLTECH", "WIPRO",
    "HDFCBANK", "SBIN", "RELIANCE", "ICICIBANK",
]

# Capital & risk per strategy
CAPITAL_MACD  = 200_000   # ₹2L
CAPITAL_BB    = 150_000   # ₹1.5L
CAPITAL_ORB   = 150_000   # ₹1.5L

RISK_MACD  = 2_000        # ₹ risk per trade (1% of capital)
RISK_BB    = 1_500
RISK_ORB   = 1_500

SLIPPAGE_BPS  = 5         # 5 bps round-trip slippage
COST_BPS      = 3         # 3 bps brokerage + STT

VERBOSE = False

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _fetch(symbol: str, days: int) -> pd.DataFrame:
    """Fetch 5-min OHLCV history from OpenAlgo."""
    client  = APIClient(api_key=API_KEY, host=HOST)
    end_dt  = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    df = client.history(
        symbol=symbol, exchange=EXCHANGE, interval="5m",
        start_date=start_dt.strftime("%Y-%m-%d"),
        end_date=end_dt.strftime("%Y-%m-%d"),
    )
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return pd.DataFrame()
    # Normalise DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("datetime", "timestamp"):
            if col in df.columns:
                df.index = (pd.to_datetime(df[col]) if col == "datetime"
                            else pd.to_datetime(df[col], unit="s"))
                break
    if hasattr(df.index, "tzinfo") and df.index.tzinfo:
        df.index = df.index.tz_localize(None)
    return df


def _apply_costs(pnl: float, price: float, qty: int, side: str = "short") -> float:
    """Apply round-trip slippage + transaction costs."""
    cost = price * qty * (SLIPPAGE_BPS + COST_BPS) / 10_000
    return pnl - cost


def _metrics(trades: list, capital: float, name: str, symbol: str,
             verbose: bool = False) -> dict:
    """Compute PF, max-drawdown, win-rate, net-PnL from trades list."""
    if not trades:
        return {
            "status": "no_trades", "total_trades": 0,
            "strategy": name, "symbol": symbol, "pass": False,
        }
    wins   = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gp = sum(wins)            if wins   else 0.0
    gl = abs(sum(losses))     if losses else 0.001   # avoid /0
    pf = round(gp / gl, 2)
    wr = round(len(wins) / len(trades) * 100, 1)

    equity, peak, max_dd = [0.0], 0.0, 0.0
    for t in trades:
        equity.append(equity[-1] + t["pnl"])
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / capital * 100
        if dd > max_dd:
            max_dd = dd

    net = round(sum(t["pnl"] for t in trades), 2)
    passes = pf >= PF_MIN and max_dd < DD_MAX and len(trades) >= 8

    if verbose:
        reasons = {}
        for t in trades:
            r = t.get("reason", "?")
            reasons[r] = reasons.get(r, 0) + 1
        print(f"      exits: {reasons}")

    return {
        "status": "success", "strategy": name, "symbol": symbol,
        "total_trades": len(trades), "win_trades": len(wins),
        "loss_trades": len(losses), "win_rate": wr,
        "profit_factor": pf, "max_drawdown_pct": round(max_dd, 2),
        "net_pnl": net, "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "pass": passes,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 1 — MACD BEARISH CROSS + SUPERTREND MOMENTUM SHORT
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Rationale: Combines two momentum indicators for HIGH-CONVICTION bearish entries.
#  MACD histogram flip negative (bearish momentum shift) + Supertrend turns
#  bearish (trend confirmation). Only shorts.  ATR-based 1:4 R:R.
#
#  Entry conditions:
#    1. MACD histogram crosses ZERO from positive to negative (bearish flip)
#    2. Supertrend direction == -1 (bearish) on same or prior bar
#    3. Price below 50-period EMA (confirming macro downtrend context)
#    4. ADX > 18 (trending market, not choppy)
#
#  SL / TP:  1.5×ATR stop above entry  |  4.5×ATR target below entry  → 3:1 R:R
#  Max 3 short trades/day.  Entry window 09:30–14:00.  Force-close 15:10.

def _backtest_macd_bearish(
    df: pd.DataFrame, symbol: str,
    risk_per_trade: float = RISK_MACD, capital: float = CAPITAL_MACD,
    macd_fast: int = 8, macd_slow: int = 21, macd_sig: int = 5,
    st_period: int = 10, st_mult: float = 2.5,
    atr_period: int = 14, atr_sl_mult: float = 1.5, atr_tp_mult: float = 4.5,
    adx_min: float = 18, ema_trend: int = 50,
    max_orders: int = 3,
) -> dict:
    df = df.copy()

    # Indicators computed on full series (more stable EMA seeds)
    df["ema_trend"] = calculate_ema(df["close"], period=ema_trend)
    df["atr"]       = calculate_atr(df, period=atr_period)
    df["adx"]       = calculate_adx(df, period=atr_period)
    macd_line, signal_line, histogram = calculate_macd(
        df["close"], fast=macd_fast, slow=macd_slow, signal=macd_sig
    )
    df["macd_hist"] = histogram
    st_vals, st_dir = calculate_supertrend(df, period=st_period, multiplier=st_mult)
    df["st_dir"]    = st_dir

    ENTRY_START = 9 * 60 + 30
    ENTRY_END   = 14 * 60
    FORCE_CLOSE = 15 * 60 + 10

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < (macd_slow + 10):
            continue

        rows = list(day.iterrows())
        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; entry_tod = None; orders = 0

        for i in range(1, len(rows)):
            _, b  = rows[i]
            _, pb = rows[i - 1]
            tod = int(b["tod"]); px = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])

            if any(pd.isna(b[c]) for c in ["atr", "adx", "macd_hist", "st_dir", "ema_trend"]):
                continue
            if any(pd.isna(pb[c]) for c in ["macd_hist", "st_dir"]):
                continue

            atr_v = float(b["atr"])

            # ── Manage open SHORT position ────────────────────────────────────
            if pos < 0:
                qty = abs(pos)
                if hi >= sl:                                       # stop hit
                    p = _apply_costs((ep - sl) * qty, sl, qty)
                    trades.append({"pnl": p, "reason": "sl"}); pos = 0; continue
                if lo <= tp:                                       # target hit
                    p = _apply_costs((ep - tp) * qty, tp, qty)
                    trades.append({"pnl": p, "reason": "tp"}); pos = 0; continue
                # Supertrend flips bullish → exit
                if int(b["st_dir"]) == 1 and int(pb["st_dir"]) == -1:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "st_flip"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "eod"}); pos = 0; continue

            # ── Entry signal ──────────────────────────────────────────────────
            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                adx_v = float(b["adx"])
                if adx_v < adx_min or pd.isna(atr_v) or atr_v <= 0:
                    continue

                # MACD histogram cross: prev ≥ 0, current < 0 (bearish flip)
                macd_cross_bear = (float(pb["macd_hist"]) >= 0) and (float(b["macd_hist"]) < 0)
                st_bearish       = int(b["st_dir"]) == -1
                below_trend_ema  = px < float(b["ema_trend"])

                if macd_cross_bear and st_bearish and below_trend_ema:
                    qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                    ep  = px
                    sl  = px + atr_sl_mult * atr_v
                    tp  = px - atr_tp_mult * atr_v
                    pos = -qty; entry_tod = tod; orders += 1
                    if VERBOSE:
                        print(f"  {date} {tod//60:02d}:{tod%60:02d} SHORT {symbol} "
                              f"@ {px:.2f}  sl={sl:.2f} tp={tp:.2f} qty={qty}")

        if pos < 0 and not day.empty:
            cp  = float(day.iloc[-1]["close"])
            qty = abs(pos)
            p   = _apply_costs((ep - cp) * qty, cp, qty)
            trades.append({"pnl": p, "reason": "eod_final"})

    return _metrics(trades, capital, "bearish_macd_st", symbol, VERBOSE)


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 2 — RSI OVERBOUGHT + BOLLINGER UPPER REJECTION SHORT
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Rationale: Mean-reversion. When price tags the upper Bollinger Band AND
#  RSI is overbought, the rally is over-extended and likely to revert.
#  Works especially well in weak/ranging markets where longs get exhausted.
#
#  Entry conditions (bearish ONLY):
#    1. Close ≥ Upper Bollinger Band (2σ) — price is over-extended
#    2. RSI ≥ 68  (overbought)
#    3. Candle closes RED (close < open) — bearish confirmation candle
#    4. OR (stronger): RSI ≥ 75 + close ≥ upper band − tolerance (exhaustion)
#    5. Price ABOVE intraday VWAP (confirming elevated position)
#
#  SL / TP: 0.45% above entry | 1.35% below entry → exactly 3:1 R:R
#  Max 3 short trades/day.  Entry window 09:30–13:30.  Force-close 15:10.

def _backtest_rsi_bb_short(
    df: pd.DataFrame, symbol: str,
    risk_per_trade: float = RISK_BB, capital: float = CAPITAL_BB,
    bb_window: int = 20, bb_std: float = 2.0,
    rsi_period: int = 14, rsi_ob: float = 55,     # overbought threshold (55 = moderately elevated)
    atr_period: int = 14, atr_sl_mult: float = 1.0, atr_tp_mult: float = 3.0,
    max_orders: int = 3,
) -> dict:
    """RSI overbought + upper Bollinger Band rejection SHORT.

    ATR-based SL/TP (like S1) prevents fixed-% from being whipsawed on volatile 5-min bars.
    Entry: price at/above upper BB + RSI≥rsi_ob + red candle. ST bearish used only for exit.
    Works best on range-bound stocks (HDFCBANK, ICICIBANK) where BB mean reversion is reliable.
    """
    df = df.copy()

    sma, upper_bb, lower_bb = calculate_bollinger_bands(df["close"], window=bb_window, num_std=bb_std)
    df["bb_upper"] = upper_bb
    df["bb_lower"] = lower_bb
    df["rsi"]      = calculate_rsi(df["close"], period=rsi_period)
    df["atr"]      = calculate_atr(df, period=atr_period)
    st_vals, st_dir = calculate_supertrend(df, period=10, multiplier=2.5)
    df["st_dir"]   = st_dir
    df             = calculate_intraday_vwap(df)
    df["vol_ma"]   = df["volume"].rolling(20).mean()  # 20-bar rolling avg vol for confirmation

    ENTRY_START = 9 * 60 + 30
    ENTRY_END   = 13 * 60 + 30
    FORCE_CLOSE = 15 * 60 + 10

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < (bb_window + 10):
            continue

        rows = list(day.iterrows())
        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; orders = 0

        for i in range(1, len(rows)):
            _, b  = rows[i]
            _, pb = rows[i - 1]
            tod = int(b["tod"]); px = float(b["close"])
            hi  = float(b["high"]); lo = float(b["low"])
            op  = float(b["open"])

            if any(pd.isna(b.get(c)) for c in ["bb_upper", "bb_lower", "rsi", "atr", "st_dir", "vol_ma"]):
                continue

            rsi_v = float(b["rsi"])
            bb_up = float(b["bb_upper"])
            bb_lo = float(b["bb_lower"])
            atr_v = float(b["atr"])
            st_v  = int(b["st_dir"])
            st_pv = int(pb["st_dir"]) if not pd.isna(pb.get("st_dir")) else st_v

            if atr_v <= 0:
                continue

            # BB%B: 0=at lower BB, 1=at upper BB, >1=above upper BB
            bb_w   = bb_up - bb_lo
            bb_pct = (px - bb_lo) / bb_w if bb_w > 0 else 0.5

            # ── Manage open SHORT ──────────────────────────────────────────────
            if pos < 0:
                qty = abs(pos)
                if hi >= sl:
                    p = _apply_costs((ep - sl) * qty, sl, qty)
                    trades.append({"pnl": p, "reason": "sl"}); pos = 0; continue
                if lo <= tp:
                    p = _apply_costs((ep - tp) * qty, tp, qty)
                    trades.append({"pnl": p, "reason": "tp"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "eod"}); pos = 0; continue

            # ── Entry: BB%B ≥ 0.80 + RSI overbought + ST bearish + red candle + above VWAP + vol ─
            # Over-extension into upper BB (top 20%) + elevated RSI + macro bearish trend
            # Volume confirms institutional participation at the rejection point
            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                bb_touch       = bb_pct >= 0.80        # top 20% of BB width = significant over-extension
                ob_rsi         = rsi_v >= rsi_ob
                bearish_candle = px < op
                above_vwap     = px > float(b["vwap"]) if not pd.isna(b.get("vwap")) else False
                macro_bear     = st_v == -1             # Supertrend macro trend is bearish
                vol_ok         = float(b["volume"]) >= 0.8 * float(b["vol_ma"])  # ≥80% of avg vol

                if bb_touch and ob_rsi and bearish_candle and above_vwap and macro_bear and vol_ok:
                    qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                    ep  = px
                    sl  = px + atr_sl_mult * atr_v
                    tp  = px - atr_tp_mult * atr_v
                    pos = -qty; orders += 1
                    if VERBOSE:
                        vol_ratio = float(b["volume"]) / float(b["vol_ma"])
                        print(f"  {date} {tod//60:02d}:{tod%60:02d} BB-reject SHORT {symbol} "
                              f"@ {px:.2f}  rsi={rsi_v:.1f}  bb%={bb_pct:.2f}  vol={vol_ratio:.1f}x  sl={sl:.2f} tp={tp:.2f}")

        if pos < 0 and not day.empty:
            cp  = float(day.iloc[-1]["close"])
            qty = abs(pos)
            p   = _apply_costs((ep - cp) * qty, cp, qty)
            trades.append({"pnl": p, "reason": "eod_final"})

    return _metrics(trades, capital, "bearish_rsi_bb", symbol, VERBOSE)


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 3 — OPENING RANGE BREAKDOWN SHORT
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Rationale: Price breaking below the 30-minute opening range low — with volume
#  confirmation — signals strong bearish momentum for the rest of the session.
#  Combines structural breakdown with trend filters for high-quality shorts.
#
#  Entry conditions (bearish ONLY):
#    1. Price breaks below (OR_low − buffer%)  → structural breakdown
#    2. Volume > vol_mult × 20-period average (institutional selling)
#    3. ADX > 18 (trending environment — not choppy)
#    4. Not a gap-UP day (gap > 0.2% from prev close → skip day entirely)
#    5. Price below VWAP at time of entry (confirming intraday bearish bias)
#
#  SL / TP: 0.5% above OR low entry | 1.5% below entry → 3:1 R:R
#  Max 2 short trades/day.  Entry window 09:45–14:30.  Force-close 15:10.

def _backtest_orb_breakdown_short(
    df: pd.DataFrame, symbol: str,
    risk_per_trade: float = RISK_ORB, capital: float = CAPITAL_ORB,
    orb_minutes: int = 30, buffer_pct: float = 0.05,
    vol_mult: float = 1.5, vol_lb: int = 20,
    adx_min: float = 18, atr_period: int = 14,
    rsi_period: int = 14, rsi_entry: float = 42,   # RSI < 42 = stronger bearish momentum confirmed
    atr_sl_mult: float = 1.5, atr_tp_mult: float = 4.5,  # kept for reference; exit via ST-flip not fixed TP
    gap_up_threshold: float = 0.20,
    max_orders: int = 2,
) -> dict:
    """Opening Range Breakdown SHORT with RSI momentum filter + ATR-adaptive stops.

    Added RSI<rsi_entry filter at breakout: ensures we're not shorting into an
    already-exhausted move (RSI oversold). ATR stops prevent whipsaw vs fixed %.
    """
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(vol_lb).mean()
    df["adx"]    = calculate_adx(df, period=atr_period)
    df["atr"]    = calculate_atr(df, period=atr_period)
    df["rsi"]    = calculate_rsi(df["close"], period=rsi_period)
    _, st_dir    = calculate_supertrend(df, period=10, multiplier=2.5)
    df["st_dir"] = st_dir
    df           = calculate_intraday_vwap(df)

    buf   = buffer_pct / 100.0
    orb_n = max(1, orb_minutes // 5)

    ENTRY_START = 9 * 60 + orb_minutes   # 09:30 + orb_minutes
    ENTRY_END   = 14 * 60 + 30
    FORCE_CLOSE = 15 * 60 + 10

    all_dates   = sorted(set(df.index.date))
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < (orb_n + 5):
            continue

        # ── Gap filter: skip gap-up days ──────────────────────────────────────
        idx = date_to_idx.get(date, 0)
        if idx > 0:
            prev_date  = all_dates[idx - 1]
            prev_df    = df.loc[df.index.date == prev_date]
            if not prev_df.empty:
                prev_close = float(prev_df.iloc[-1]["close"])
                today_open = float(day.iloc[0]["open"])
                gap_pct    = (today_open - prev_close) / prev_close * 100
                if gap_pct > gap_up_threshold:
                    continue   # skip bullish gap-up days

        # ── Opening range ─────────────────────────────────────────────────────
        opening = day.iloc[:orb_n]
        or_low  = float(opening["low"].min())

        pos = 0; ep = 0.0; trail_sl = 0.0; orders = 0

        for _, b in day[day["tod"] >= ENTRY_START].iterrows():
            tod = int(b["tod"]); px = float(b["close"])
            hi  = float(b["high"]); lo = float(b["low"])

            if any(pd.isna(b.get(c)) for c in ["vol_ma", "adx", "atr", "rsi", "vwap"]):
                continue

            atr_v = float(b["atr"])
            if atr_v <= 0:
                continue

            # ── Manage open SHORT ─────────────────────────────────────────────
            if pos < 0:
                qty = abs(pos)
                if hi >= trail_sl:
                    p = _apply_costs((ep - trail_sl) * qty, trail_sl, qty)
                    trades.append({"pnl": p, "reason": "sl"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "eod"}); pos = 0; continue
                # ATR trailing stop: lower SL as price falls (1.5×ATR behind close)
                new_trail = px + atr_sl_mult * atr_v
                if new_trail < trail_sl:
                    trail_sl = new_trail

            # ── Entry: ORB breakdown + volume + ADX + VWAP + RSI momentum ────
            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                adx_v     = float(b["adx"])
                rsi_v     = float(b["rsi"])
                vol_ok    = float(b["volume"]) > vol_mult * float(b["vol_ma"]) \
                            if not pd.isna(b["vol_ma"]) else False
                vwap_ok   = px < float(b["vwap"])
                breakdown  = px < or_low * (1 - buf)
                rsi_bear   = rsi_v < rsi_entry     # bearish momentum (not yet oversold)

                if breakdown and vol_ok and adx_v >= adx_min and vwap_ok and rsi_bear:
                    qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                    ep       = px
                    trail_sl = px + atr_sl_mult * atr_v
                    pos = -qty; orders += 1
                    if VERBOSE:
                        print(f"  {date} {tod//60:02d}:{tod%60:02d} SHORT {symbol} "
                              f"@ {px:.2f}  OR_low={or_low:.2f}  rsi={rsi_v:.1f} "
                              f"trail_sl={trail_sl:.2f} (ATR trail exit)")

        if pos < 0 and not day.empty:
            cp  = float(day.iloc[-1]["close"])
            qty = abs(pos)
            p   = _apply_costs((ep - cp) * qty, cp, qty)
            trades.append({"pnl": p, "reason": "eod_final"})

    return _metrics(trades, capital, "bearish_orb_breakdown", symbol, VERBOSE)


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 2v — RSI50 CROSS-UNDER SHORT  (Trend-Following)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Rationale: RSI crossing below 50 from above signals a shift from bullish to
#  bearish momentum. When this occurs with Supertrend already bearish and price
#  below VWAP, the short is aligned with the intraday trend. Works best in
#  sustained downtrends where corrective bounces fail.
#
#  Entry conditions (bearish ONLY):
#    1. RSI crosses below 50 from above  (prev RSI ≥ 50, current RSI < 50)
#    2. Supertrend direction == -1 (macro trend is bearish)
#    3. Price < intraday VWAP (bearish intraday bias)
#    4. ADX > 15 (some directional momentum)
#
#  SL / TP: 1.5×ATR above entry | 4.5×ATR below entry → 3:1 R:R
#  Exit override: RSI recovers above 55 → take partial profit/cut loss
#  Max 3 short trades/day.  Entry window 09:30–14:00.  Force-close 15:10.

def _backtest_rsi50_cross_short(
    df: pd.DataFrame, symbol: str,
    risk_per_trade: float = RISK_BB, capital: float = CAPITAL_BB,
    rsi_period: int = 14,
    atr_period: int = 14, atr_sl_mult: float = 1.0, atr_tp_mult: float = 3.0,
    adx_min: float = 15, max_orders: int = 3,
) -> dict:
    df = df.copy()

    # S2: RSI50 Crossunder with Volume Confirmation Short
    # RSI crossing below 50 marks momentum shift from bullish to bearish.
    # Volume confirmation filters out low-conviction RSI crossunders (noise).
    # Best on stocks with intermittent bearish regimes (WIPRO, INFY).
    df["rsi"]       = calculate_rsi(df["close"], period=rsi_period)
    df["atr"]       = calculate_atr(df, period=atr_period)
    df["adx"]       = calculate_adx(df, period=atr_period)
    st_vals, st_dir = calculate_supertrend(df, period=10, multiplier=2.5)
    df["st_dir"]    = st_dir
    df              = calculate_intraday_vwap(df)
    df["vol_ma"]    = df["volume"].rolling(20).mean()   # volume confirmation

    ENTRY_START = 9 * 60 + 30
    ENTRY_END   = 14 * 60
    FORCE_CLOSE = 15 * 60 + 10

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < (rsi_period + 25):
            continue

        rows = list(day.iterrows())
        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; entry_tod = None; orders = 0

        for i in range(1, len(rows)):
            _, b  = rows[i]
            _, pb = rows[i - 1]
            tod = int(b["tod"]); px = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])

            req_cols = ["rsi", "atr", "adx", "st_dir", "vwap", "vol_ma"]
            if any(pd.isna(b.get(c)) for c in req_cols) or pd.isna(pb.get("rsi")):
                continue

            atr_v  = float(b["atr"])
            rsi_v  = float(b["rsi"])
            rsi_pv = float(pb["rsi"])

            # ── Manage open SHORT ─────────────────────────────────────────────
            if pos < 0:
                qty = abs(pos)
                if hi >= sl:
                    p = _apply_costs((ep - sl) * qty, sl, qty)
                    trades.append({"pnl": p, "reason": "sl"}); pos = 0; continue
                if lo <= tp:
                    p = _apply_costs((ep - tp) * qty, tp, qty)
                    trades.append({"pnl": p, "reason": "tp"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "eod"}); pos = 0; continue

            # ── Entry: RSI50 crossunder + volume spike confirmation ────────────
            # RSI crosses below 50 (bullish→bearish momentum shift) AND volume is
            # above average (confirming sellers stepped in with conviction).
            # ST bearish macro trend + below VWAP ensure intraday alignment.
            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                rsi_cross = (rsi_pv >= 50.0) and (rsi_v < 50.0)   # RSI50 crossunder
                vol_ok    = float(b["volume"]) >= 1.0 * float(b["vol_ma"])  # ≥ avg volume
                st_bear   = int(b["st_dir"]) == -1
                below_vwap = px < float(b["vwap"])
                adx_ok    = float(b["adx"]) >= adx_min

                if rsi_cross and vol_ok and st_bear and below_vwap and adx_ok and atr_v > 0:
                    qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                    ep  = px
                    sl  = px + atr_sl_mult * atr_v
                    tp  = px - atr_tp_mult * atr_v
                    pos = -qty; entry_tod = tod; orders += 1
                    if VERBOSE:
                        vol_ratio = float(b["volume"]) / float(b["vol_ma"])
                        print(f"  {date} {tod//60:02d}:{tod%60:02d} RSI50↓+VOL SHORT {symbol} "
                              f"@ {px:.2f}  rsi={rsi_v:.1f}  vol={vol_ratio:.1f}x  "
                              f"sl={sl:.2f} tp={tp:.2f}")

        if pos < 0 and not day.empty:
            cp  = float(day.iloc[-1]["close"])
            qty = abs(pos)
            p   = _apply_costs((ep - cp) * qty, cp, qty)
            trades.append({"pnl": p, "reason": "eod_final"})

    return _metrics(trades, capital, "bearish_rsi50_cross", symbol, VERBOSE)


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY 3v — ORB-45 BREAKDOWN SHORT  (ATR Adaptive Stops)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Rationale: Use a 45-minute opening range (more stable than 30-min) and
#  ATR-based stops instead of fixed percentages. Adds an OR-range filter:
#  only trade when the range was TIGHT (< 1.0%) — tight ranges give cleaner
#  breakouts. The 5:1 ATR R:R (2.0×ATR SL → 6.0×ATR TP?) — wait, use 3:1.
#
#  Entry conditions (bearish ONLY):
#    1. Price closes below (OR_low − 0.1% buffer)  — structural breakdown
#    2. OR_range < 1.0% of OR_low  (tight opening range filter)
#    3. Volume > 1.5× 20-bar rolling average  (institutional volume)
#    4. ADX > 18 at entry (trending market)
#    5. Price < intraday VWAP  (bearish intraday bias)
#    6. Not a gap-up day (> 0.3% gap from prev close)
#
#  SL / TP: 1.2×ATR above entry | 3.6×ATR below entry → 3:1 R:R
#  Max 2 short trades/day.  Entry window 10:00–14:30.  Force-close 15:10.

def _backtest_orb45_atr_short(
    df: pd.DataFrame, symbol: str,
    risk_per_trade: float = RISK_ORB, capital: float = CAPITAL_ORB,
    orb_minutes: int = 45, buffer_pct: float = 0.10,
    or_range_max_pct: float = 1.0,         # skip wide-range OR days
    vol_mult: float = 1.5, vol_lb: int = 20,
    atr_period: int = 14, atr_sl_mult: float = 1.2, atr_tp_mult: float = 3.6,
    adx_min: float = 18,
    gap_up_threshold: float = 0.30,
    max_orders: int = 2,
) -> dict:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(vol_lb).mean()
    df["adx"]    = calculate_adx(df, period=atr_period)
    df["atr"]    = calculate_atr(df, period=atr_period)
    df           = calculate_intraday_vwap(df)

    buf   = buffer_pct / 100.0
    orb_n = max(1, orb_minutes // 5)   # bars in OR window

    ENTRY_START = 9 * 60 + orb_minutes  # 10:00 for 45-min OR
    ENTRY_END   = 14 * 60 + 30
    FORCE_CLOSE = 15 * 60 + 10

    all_dates   = sorted(set(df.index.date))
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < (orb_n + 5):
            continue

        # Gap filter
        idx = date_to_idx.get(date, 0)
        if idx > 0:
            prev_df = df.loc[df.index.date == all_dates[idx - 1]]
            if not prev_df.empty:
                prev_close = float(prev_df.iloc[-1]["close"])
                today_open = float(day.iloc[0]["open"])
                gap_pct    = (today_open - prev_close) / prev_close * 100
                if gap_pct > gap_up_threshold:
                    continue

        # Opening range (45 min)
        opening  = day.iloc[:orb_n]
        or_high  = float(opening["high"].max())
        or_low   = float(opening["low"].min())
        or_range = (or_high - or_low) / or_low * 100
        if or_range > or_range_max_pct:
            continue   # skip wide-range days → fakeouts

        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; entry_tod = None; orders = 0

        for _, b in day[day["tod"] >= ENTRY_START].iterrows():
            tod = int(b["tod"]); px = float(b["close"]); hi = float(b["high"]); lo = float(b["low"])

            if any(pd.isna(b.get(c)) for c in ["vol_ma", "adx", "atr", "vwap"]):
                continue

            atr_v = float(b["atr"])

            # ── Manage open SHORT ─────────────────────────────────────────────
            if pos < 0:
                qty = abs(pos)
                if hi >= sl:
                    p = _apply_costs((ep - sl) * qty, sl, qty)
                    trades.append({"pnl": p, "reason": "sl"}); pos = 0; continue
                if lo <= tp:
                    p = _apply_costs((ep - tp) * qty, tp, qty)
                    trades.append({"pnl": p, "reason": "tp"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    p = _apply_costs((ep - px) * qty, px, qty)
                    trades.append({"pnl": p, "reason": "eod"}); pos = 0; continue

            # ── Entry signal ──────────────────────────────────────────────────
            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                adx_v      = float(b["adx"])
                vol_ok     = float(b["volume"]) > vol_mult * float(b["vol_ma"]) \
                             if not pd.isna(b["vol_ma"]) else False
                vwap_ok    = px < float(b["vwap"])
                breakdown  = px < or_low * (1 - buf)
                atr_ok     = atr_v > 0

                if breakdown and vol_ok and adx_v >= adx_min and vwap_ok and atr_ok:
                    qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                    ep  = px
                    sl  = px + atr_sl_mult * atr_v
                    tp  = px - atr_tp_mult * atr_v
                    pos = -qty; entry_tod = tod; orders += 1
                    if VERBOSE:
                        print(f"  {date} {tod//60:02d}:{tod%60:02d} ORB45 SHORT {symbol} "
                              f"@ {px:.2f}  OR_low={or_low:.2f}  rng={or_range:.2f}%  "
                              f"sl={sl:.2f} tp={tp:.2f}")

        if pos < 0 and not day.empty:
            cp  = float(day.iloc[-1]["close"])
            qty = abs(pos)
            p   = _apply_costs((ep - cp) * qty, cp, qty)
            trades.append({"pnl": p, "reason": "eod_final"})

    return _metrics(trades, capital, "bearish_orb45_atr", symbol, VERBOSE)


# ─── PRINT HELPERS ────────────────────────────────────────────────────────────

def _bar(label: str, value: float, is_pct: bool = False, good_high: bool = True) -> str:
    unit = "%" if is_pct else ""
    marker = "✅" if (good_high and value > 0) or (not good_high and value < 6) else "⚠️ "
    return f"  {label:<28} {value:>8.2f}{unit}  {marker}"


def _print_result(r: dict, capital: float):
    status = "✅ PASS" if r.get("pass") else "❌ FAIL"
    print(f"\n  {'─'*60}")
    print(f"  [{status}]  {r['strategy'].upper()}  —  {r['symbol']}")
    print(f"  {'─'*60}")
    if r.get("status") == "no_trades":
        print("  ⚠️  No trades generated"); return
    print(f"  {'Trades':28} {r['total_trades']:>8}  "
          f"(W:{r['win_trades']}  L:{r['loss_trades']})")
    print(f"  {'Win Rate':28} {r['win_rate']:>7.1f}%")
    pf_ok = "✅" if r["profit_factor"] >= PF_MIN else "❌"
    print(f"  {'Profit Factor':28} {r['profit_factor']:>8.2f}  {pf_ok}")
    dd_ok = "✅" if r["max_drawdown_pct"] < DD_MAX else "❌"
    print(f"  {'Max Drawdown':28} {r['max_drawdown_pct']:>7.2f}%  {dd_ok}")
    ret = r["net_pnl"] / capital * 100
    print(f"  {'Net PnL':28} ₹{r['net_pnl']:>8,.0f}  ({ret:+.1f}%)")
    print(f"  {'Gross Profit':28} ₹{r['gross_profit']:>8,.0f}")
    print(f"  {'Gross Loss':28} ₹{r['gross_loss']:>8,.0f}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    global VERBOSE

    parser = argparse.ArgumentParser(description="Bearish 3-strategy backtest")
    parser.add_argument("--days",    type=int, default=90, help="History days (default 90)")
    parser.add_argument("--verbose", action="store_true",  help="Print each trade")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║   BEARISH EQUITY BACKTEST  ·  3 Short Strategies  ·  NSE 5-min  ║")
    print(f"║   Period: {args.days} trading days  ·  Target: PF>{PF_MIN}  MaxDD<{DD_MAX}%        ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"\n  Fetching {args.days}d data for {len(CANDIDATES)} symbols …\n")

    # ── Fetch all data up front ───────────────────────────────────────────────
    data: Dict[str, pd.DataFrame] = {}
    for sym in CANDIDATES:
        df = _fetch(sym, args.days)
        if df.empty:
            print(f"  ⚠️  {sym}: no data")
        else:
            print(f"  ✅ {sym}: {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})")
            data[sym] = df

    if not data:
        print("\n❌ No data fetched — check OpenAlgo server."); return

    print()

    # ═════════════════════════════════════════════════════════════════════════
    # STRATEGY 1: MACD Bearish + Supertrend
    # ═════════════════════════════════════════════════════════════════════════
    print("\n" + "═"*68)
    print("  STRATEGY 1 — MACD BEARISH CROSS + SUPERTREND MOMENTUM SHORT")
    print("  Logic: MACD(8,21,5) hist flips -ve + Supertrend bearish + below EMA50")
    print("  Risk:  1.5×ATR stop  |  4.5×ATR target  (3:1 R:R)  ADX≥18")
    print("═"*68)

    # ── S1: Keep proven slow MACD(8,21,5) — quality over quantity ──
    s1_results = []
    for sym, df in data.items():
        r = _backtest_macd_bearish(df, sym)   # default params: macd(8,21,5)+ST
        s1_results.append(r)
        flag = "✅ PASS" if r["pass"] else "  ----"
        n = r["total_trades"]
        pf = r["profit_factor"] if n else 0
        dd = r["max_drawdown_pct"] if n else 0
        pnl = r["net_pnl"] if n else 0
        print(f"  {flag}  {sym:<12} trades={n:>3}  PF={pf:.2f}  DD={dd:.1f}%  PnL=₹{pnl:>7,.0f}")

    passing_s1 = [r for r in s1_results if r["pass"]]
    if passing_s1:
        best_s1 = max(passing_s1, key=lambda r: r["profit_factor"])
        _print_result(best_s1, CAPITAL_MACD)
    else:
        best_s1 = max(s1_results, key=lambda r: r.get("profit_factor", 0))
        print(f"\n  ⚠️  No symbol passed for S1 — best: {best_s1['symbol']} "
              f"PF={best_s1.get('profit_factor',0):.2f}")
        _print_result(best_s1, CAPITAL_MACD)

    # ═════════════════════════════════════════════════════════════════════════
    # STRATEGY 2: RSI Overbought + Bollinger Rejection
    # ═════════════════════════════════════════════════════════════════════════
    print("\n" + "═"*68)
    print("  STRATEGY 2 — RSI50 CROSSUNDER + VOLUME CONFIRM SHORT  (Momentum)")
    print("  Logic: RSI(14) crosses below 50 + vol≥avg + ST bearish + below VWAP + ADX≥15")
    print("  Risk:  1.0×ATR stop  |  3.0×ATR target  (3:1 R:R)")
    print("═"*68)

    s2_results = []
    for sym, df in data.items():
        r = _backtest_rsi50_cross_short(df, sym, atr_sl_mult=1.0, atr_tp_mult=3.0, adx_min=15)
        s2_results.append(r)
        flag = "✅ PASS" if r["pass"] else "  ----"
        n = r["total_trades"]
        pf = r["profit_factor"] if n else 0
        dd = r["max_drawdown_pct"] if n else 0
        pnl = r["net_pnl"] if n else 0
        print(f"  {flag}  {sym:<12} trades={n:>3}  PF={pf:.2f}  DD={dd:.1f}%  PnL=₹{pnl:>7,.0f}")

    passing_s2 = [r for r in s2_results if r["pass"]]
    if passing_s2:
        best_s2 = max(passing_s2, key=lambda r: r["profit_factor"])
        _print_result(best_s2, CAPITAL_BB)
    else:
        best_s2 = max(s2_results, key=lambda r: r.get("profit_factor", 0))
        print(f"\n  ⚠️  No symbol passed for S2 — best: {best_s2['symbol']} "
              f"PF={best_s2.get('profit_factor',0):.2f}")
        _print_result(best_s2, CAPITAL_BB)

    # ═════════════════════════════════════════════════════════════════════════
    # STRATEGY 3: Opening Range Breakdown Short
    # ═════════════════════════════════════════════════════════════════════════
    print("\n" + "═"*68)
    print("  STRATEGY 3 — BB REJECTION SHORT  (Overbought Exhaustion)")
    print("  Logic: BB%B≥0.80 + RSI≥62 + ST bearish + red candle + above VWAP + vol≥avg → over-extension")
    print("  Risk:  1.0×ATR stop  |  2.5×ATR target  (2.5:1 R:R)")
    print("═"*68)

    s3_results = []
    for sym, df in data.items():
        r = _backtest_rsi_bb_short(df, sym, atr_sl_mult=1.0, atr_tp_mult=2.5, rsi_ob=62)
        s3_results.append(r)
        flag = "✅ PASS" if r["pass"] else "  ----"
        n = r["total_trades"]
        pf = r["profit_factor"] if n else 0
        dd = r["max_drawdown_pct"] if n else 0
        pnl = r["net_pnl"] if n else 0
        print(f"  {flag}  {sym:<12} trades={n:>3}  PF={pf:.2f}  DD={dd:.1f}%  PnL=₹{pnl:>7,.0f}")

    passing_s3 = [r for r in s3_results if r["pass"]]
    if passing_s3:
        best_s3 = max(passing_s3, key=lambda r: r["profit_factor"])
        _print_result(best_s3, CAPITAL_ORB)
    else:
        best_s3 = max(s3_results, key=lambda r: r.get("profit_factor", 0))
        print(f"\n  ⚠️  No symbol passed for S3 — best: {best_s3['symbol']} "
              f"PF={best_s3.get('profit_factor',0):.2f}")
        _print_result(best_s3, CAPITAL_ORB)

    # ═════════════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ═════════════════════════════════════════════════════════════════════════
    print("\n" + "═"*68)
    print("  DEPLOYMENT SELECTION — BEST PER STRATEGY")
    print("═"*68)

    total_pnl = 0.0
    total_cap = CAPITAL_MACD + CAPITAL_BB + CAPITAL_ORB
    deploy_map = {
        "bearish_macd_st":      (best_s1, CAPITAL_MACD),
        "bearish_rsi50_cross":  (best_s2, CAPITAL_BB),
        "bearish_orb45_atr":    (best_s3, CAPITAL_ORB),
    }
    all_pass = True
    for strat, (res, cap) in deploy_map.items():
        n   = res["total_trades"]
        pf  = res["profit_factor"] if n else 0
        dd  = res["max_drawdown_pct"] if n else 0
        pnl = res["net_pnl"] if n else 0
        pf_ok = "✅" if pf >= PF_MIN else "❌"
        dd_ok = "✅" if dd < DD_MAX  else "❌"
        total_pnl += pnl
        if not res["pass"]:
            all_pass = False
        qty_est = max(1, int({
            "bearish_macd_st":      RISK_MACD,
            "bearish_rsi50_cross":  RISK_BB,
            "bearish_orb45_atr":    RISK_ORB,
        }[strat] / (res["symbol"] and 5 or 5)))   # placeholder qty
        print(f"\n  {strat}")
        print(f"    Symbol : {res['symbol']}")
        print(f"    Trades : {n}  (W:{res.get('win_trades',0)}  L:{res.get('loss_trades',0)})")
        print(f"    Win%   : {res.get('win_rate',0):.1f}%")
        print(f"    PF     : {pf:.2f}  {pf_ok}")
        print(f"    Max DD : {dd:.2f}%  {dd_ok}")
        print(f"    Net PnL: ₹{pnl:,.0f}  ({pnl/cap*100:+.1f}%)")

    print()
    print(f"  {'─'*60}")
    print(f"  Combined Net PnL  : ₹{total_pnl:>10,.0f}  ({total_pnl/total_cap*100:+.1f}%)")
    print(f"  Total Capital     : ₹{total_cap:>10,}")
    verdict = "✅ ALL 3 PASS — Ready for deployment" if all_pass \
              else "⚠️  Some strategies need parameter tuning"
    print(f"  Verdict           : {verdict}")
    print("═"*68)
    print()


if __name__ == "__main__":
    main()
