#!/usr/bin/env python3
"""
Equity Strategy Backtest Runner — ₹5L Allocation
Tests 3 strategies × 6 candidate NSE stocks, selects best performers.

Criteria: Profit Factor > 2.5 AND Max Drawdown < 6%
Allocation: ORB ₹2L, VWAP RSI ₹1.5L, EMA SuperTrend ₹1.5L

Usage:
    cd ~/openalgo
    python3 backtest_equity_5l.py
    python3 backtest_equity_5l.py --days 60 --verbose
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

# ─── PATH SETUP ───────────────────────────────────────────────────────────────
_BASE   = os.path.dirname(os.path.abspath(__file__))
_OA     = os.path.join(_BASE, "openalgo")
_UTILS  = os.path.join(_OA, "strategies", "utils")
_SCRIPTS = os.path.join(_OA, "strategies", "scripts")

for p in [_BASE, _OA, _UTILS, _SCRIPTS]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Load config for API key
sys.path.insert(0, _BASE)
try:
    import ic_config
    API_KEY = ic_config.OPENALGO_KEY
    HOST    = "http://127.0.0.1:5002"
except ImportError:
    _FALLBACK = "09854f66270c372a56b5560970270d00e375d2e63131a3f5d9dd0f7d2505aae7"
    API_KEY   = os.environ.get("OPENALGO_API_KEY", _FALLBACK)
    HOST      = os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5002")

# Load indicator functions
from trading_utils import (
    APIClient,
    calculate_ema,
    calculate_atr,
    calculate_supertrend,
    calculate_adx,
    calculate_intraday_vwap,
    calculate_rsi,
)

import pandas as pd

# ─── CANDIDATES ───────────────────────────────────────────────────────────────
CANDIDATES     = ["RELIANCE", "ICICIBANK", "HDFCBANK", "INFY", "TCS", "SBIN"]
ORB_CANDIDATES = ["RELIANCE", "ICICIBANK", "HDFCBANK", "INFY", "TCS", "SBIN",
                  "BAJFINANCE", "KOTAKBANK"]
EXCHANGE   = "NSE"

PF_MIN  = 2.5
DD_MAX  = 6.0

# Capital per strategy
CAPITAL_ORB  = 200_000   # ₹2L
CAPITAL_VWAP = 150_000   # ₹1.5L
CAPITAL_EMA  = 150_000   # ₹1.5L

# Risk per trade (1% of allocation)
RISK_ORB  = 2_000
RISK_VWAP = 1_500
RISK_EMA  = 1_500


# ─── SHARED HELPERS ───────────────────────────────────────────────────────────

def _fetch(symbol: str, days: int) -> pd.DataFrame:
    client   = APIClient(api_key=API_KEY, host=HOST)
    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    df = client.history(symbol=symbol, exchange=EXCHANGE, interval="5m",
                        start_date=start_dt.strftime("%Y-%m-%d"),
                        end_date=end_dt.strftime("%Y-%m-%d"))
    if df is None:
        return pd.DataFrame()
    # Normalize index
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("datetime", "timestamp"):
            if col in df.columns:
                df.index = pd.to_datetime(df[col]) if col == "datetime" \
                           else pd.to_datetime(df[col], unit="s")
                break
    df.index = df.index.tz_localize(None) if hasattr(df.index, "tzinfo") and df.index.tzinfo else df.index
    return df


def _metrics(trades: list, capital: float, name: str, symbol: str) -> dict:
    if not trades:
        return {"status": "no_trades", "total_trades": 0, "strategy": name,
                "symbol": symbol, "pass": False}
    wins   = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gp = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.0
    pf = round(gp / gl, 2) if gl > 0 else 99.0
    wr = round(len(wins) / len(trades) * 100, 1)

    equity, peak, max_dd = [0.0], 0.0, 0.0
    for t in trades:
        equity.append(equity[-1] + t["pnl"])
    for e in equity:
        peak = max(peak, e)
        dd   = (peak - e) / capital * 100 if capital > 0 else 0
        max_dd = max(max_dd, dd)

    return {
        "status": "success", "strategy": name, "symbol": symbol,
        "total_trades": len(trades), "win_rate": wr,
        "profit_factor": pf, "max_drawdown_pct": round(max_dd, 2),
        "net_pnl": round(sum(t["pnl"] for t in trades), 2),
        "pass": pf >= PF_MIN and max_dd < DD_MAX,
    }


# ─── STRATEGY 1: ORB EQUITY VOLUME ────────────────────────────────────────────

def _backtest_orb(df: pd.DataFrame, symbol: str, risk_per_trade=RISK_ORB, capital=CAPITAL_ORB,
                  orb_minutes=30, buffer_pct=0.1, sl_pct=0.5, tp_pct=1.5,
                  vol_mult=1.7, vol_lb=20, max_orders=2, max_hold_min=90,
                  gap_filter=True, gap_threshold=0.15) -> dict:
    """gap_filter: only trade longs on gap-up days, shorts on gap-down days.
    gap_threshold: minimum gap % to classify as directional (default 0.15%)."""
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(vol_lb).mean()
    buf = buffer_pct / 100.0

    ENTRY_START = 9 * 60 + orb_minutes
    ENTRY_END   = 14 * 60
    FORCE_CLOSE = 15 * 60 + 10
    orb_n       = max(1, orb_minutes // 5)

    # Build sorted day index for gap look-up
    all_dates = sorted(set(df.index.date))
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        opening = day.iloc[:orb_n]
        if len(opening) < max(orb_n // 2, 3):
            continue
        or_high = float(opening["high"].max())
        or_low  = float(opening["low"].min())

        # ── Gap direction filter ──────────────────────────────────────────────
        can_long = True; can_short = True
        if gap_filter:
            idx = date_to_idx.get(date, 0)
            if idx > 0:
                prev_date = all_dates[idx - 1]
                prev_day_df = df.loc[df.index.date == prev_date]
                if not prev_day_df.empty:
                    prev_close = float(prev_day_df.iloc[-1]["close"])
                    today_open = float(day.iloc[0]["open"])
                    gap_pct = (today_open - prev_close) / prev_close * 100
                    if gap_pct > gap_threshold:
                        can_short = False   # gap-up day → only trade longs
                    elif gap_pct < -gap_threshold:
                        can_long = False    # gap-down day → only trade shorts

        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; entry_tod = None; orders = 0
        long_done = False; short_done = False
        for _, b in day[day["tod"] >= (9 * 60 + orb_minutes)].iterrows():
            tod = int(b["tod"]); px = float(b["close"])
            if pos > 0:
                held = (tod - entry_tod) if entry_tod is not None else 0
                if float(b["low"]) <= sl:
                    trades.append({"pnl": (sl - ep) * pos, "reason": "sl"}); pos = 0; continue
                if float(b["high"]) >= tp:
                    trades.append({"pnl": (tp - ep) * pos, "reason": "tp"}); pos = 0; continue
                if held >= max_hold_min or tod >= FORCE_CLOSE:
                    trades.append({"pnl": (px - ep) * pos, "reason": "max_hold"}); pos = 0; continue
            elif pos < 0:
                held = (tod - entry_tod) if entry_tod is not None else 0
                if float(b["high"]) >= sl:
                    trades.append({"pnl": (ep - sl) * abs(pos), "reason": "sl"}); pos = 0; continue
                if float(b["low"]) <= tp:
                    trades.append({"pnl": (ep - tp) * abs(pos), "reason": "tp"}); pos = 0; continue
                if held >= max_hold_min or tod >= FORCE_CLOSE:
                    trades.append({"pnl": (ep - px) * abs(pos), "reason": "max_hold"}); pos = 0; continue

            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                vol_ok = pd.isna(b["vol_ma"]) or float(b["volume"]) > vol_mult * float(b["vol_ma"])
                qty = max(1, int(risk_per_trade / (px * sl_pct / 100)))
                if px > or_high * (1 + buf) and vol_ok and not long_done and can_long:
                    ep = px; sl = px * (1 - sl_pct / 100); tp = px * (1 + tp_pct / 100)
                    pos = qty; entry_tod = tod; orders += 1; long_done = True
                elif px < or_low * (1 - buf) and vol_ok and not short_done and can_short:
                    ep = px; sl = px * (1 + sl_pct / 100); tp = px * (1 - tp_pct / 100)
                    pos = -qty; entry_tod = tod; orders += 1; short_done = True

        if pos != 0 and not day.empty:
            cp = float(day.iloc[-1]["close"])
            trades.append({"pnl": (cp - ep) * pos if pos > 0 else (ep - cp) * abs(pos), "reason": "eod_final"})

    return _metrics(trades, capital, "orb_equity_volume", symbol)


# ─── STRATEGY 2: VWAP RSI REVERSION ───────────────────────────────────────────

def _backtest_vwap(df: pd.DataFrame, symbol: str, risk_per_trade=RISK_VWAP, capital=CAPITAL_VWAP,
                   vwap_std_mult=1.5, rsi_period=14, rsi_os=30, rsi_ob=70,
                   sl_pct=0.4, tp_pct=1.0, max_hold_min=60, max_orders=4) -> dict:
    df = calculate_intraday_vwap(df.copy())
    # RSI computed cross-day for Wilder EMA stability
    df["rsi"] = calculate_rsi(df["close"], period=rsi_period)

    ENTRY_START = 9 * 60 + 30
    ENTRY_END   = 13 * 60 + 30
    FORCE_CLOSE = 15 * 60 + 10

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < 15:
            continue

        # Per-day expanding std — avoids cross-day VWAP contamination
        day["price_dev"]  = day["close"] - day["vwap"]
        day["vwap_std"]   = day["price_dev"].expanding(min_periods=5).std()
        day["upper_band"] = day["vwap"] + vwap_std_mult * day["vwap_std"]
        day["lower_band"] = day["vwap"] - vwap_std_mult * day["vwap_std"]

        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; entry_tod = None; orders = 0
        for _, b in day.iterrows():
            tod = int(b["tod"]); px = float(b["close"])
            if pd.isna(b.get("upper_band")) or pd.isna(b.get("rsi")):
                continue
            vwap = float(b["vwap"])

            if pos > 0:
                if float(b["low"]) <= sl:
                    trades.append({"pnl": (sl - ep) * pos, "reason": "sl"}); pos = 0; continue
                if float(b["high"]) >= tp:
                    trades.append({"pnl": (tp - ep) * pos, "reason": "tp_fixed"}); pos = 0; continue
                if float(b["high"]) >= vwap and ep < vwap:
                    tp_px = min(px, vwap)
                    trades.append({"pnl": (tp_px - ep) * pos, "reason": "tp_vwap"}); pos = 0; continue
                if (entry_tod is not None and (tod - entry_tod) >= max_hold_min) or tod >= FORCE_CLOSE:
                    trades.append({"pnl": (px - ep) * pos, "reason": "eod"}); pos = 0; continue
            elif pos < 0:
                if float(b["high"]) >= sl:
                    trades.append({"pnl": (ep - sl) * abs(pos), "reason": "sl"}); pos = 0; continue
                if float(b["low"]) <= tp:
                    trades.append({"pnl": (ep - tp) * abs(pos), "reason": "tp_fixed"}); pos = 0; continue
                if float(b["low"]) <= vwap and ep > vwap:
                    tp_px = max(px, vwap)
                    trades.append({"pnl": (ep - tp_px) * abs(pos), "reason": "tp_vwap"}); pos = 0; continue
                if (entry_tod is not None and (tod - entry_tod) >= max_hold_min) or tod >= FORCE_CLOSE:
                    trades.append({"pnl": (ep - px) * abs(pos), "reason": "eod"}); pos = 0; continue

            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                qty = max(1, int(risk_per_trade / (px * sl_pct / 100)))
                if px < float(b["lower_band"]) and float(b["rsi"]) < rsi_os:
                    ep = px; sl = px * (1 - sl_pct / 100); tp = px * (1 + tp_pct / 100)
                    pos = qty; entry_tod = tod; orders += 1
                elif px > float(b["upper_band"]) and float(b["rsi"]) > rsi_ob:
                    ep = px; sl = px * (1 + sl_pct / 100); tp = px * (1 - tp_pct / 100)
                    pos = -qty; entry_tod = tod; orders += 1

        if pos != 0 and not day.empty:
            cp = float(day.iloc[-1]["close"])
            trades.append({"pnl": (cp - ep) * pos if pos > 0 else (ep - cp) * abs(pos), "reason": "eod_final"})

    return _metrics(trades, capital, "vwap_rsi_equity", symbol)


# ─── STRATEGY 3: EMA SUPERTREND ───────────────────────────────────────────────

def _backtest_ema_st(df: pd.DataFrame, symbol: str, risk_per_trade=RISK_EMA, capital=CAPITAL_EMA,
                     fast_ema=5, slow_ema=13, st_period=10, st_mult=2.5,
                     atr_period=14, atr_sl_mult=1.5, atr_tp_mult=3.0, adx_min=0,
                     max_orders=4) -> dict:
    df = df.copy()
    df["ema_fast"]     = calculate_ema(df["close"], period=fast_ema)
    df["ema_slow"]     = calculate_ema(df["close"], period=slow_ema)
    df["atr"]          = calculate_atr(df, period=atr_period)
    df["adx"]          = calculate_adx(df, period=atr_period)
    st_vals, st_dir    = calculate_supertrend(df, period=st_period, multiplier=st_mult)
    df["st_dir"]       = st_dir

    ENTRY_START = 9 * 60 + 30
    ENTRY_END   = 14 * 60 + 30
    FORCE_CLOSE = 15 * 60 + 10

    trades = []
    for date, day in df.groupby(df.index.date):
        day = day.sort_index().copy()
        day["tod"] = day.index.hour * 60 + day.index.minute
        if len(day) < max(slow_ema + 5, atr_period + 5, 30):
            continue

        rows = list(day.iterrows())
        pos = 0; ep = 0.0; sl = 0.0; tp = 0.0; orders = 0

        for i in range(1, len(rows)):
            _, b  = rows[i]
            _, pb = rows[i - 1]
            tod = int(b["tod"]); px = float(b["close"])
            if pd.isna(b["ema_slow"]) or pd.isna(b["atr"]) or pd.isna(b["adx"]):
                continue

            if pos > 0:
                if float(b["low"]) <= sl:
                    trades.append({"pnl": (sl - ep) * pos, "reason": "sl"}); pos = 0; continue
                if float(b["high"]) >= tp:
                    trades.append({"pnl": (tp - ep) * pos, "reason": "tp"}); pos = 0; continue
                if int(b["st_dir"]) == -1 and int(pb["st_dir"]) == 1:
                    trades.append({"pnl": (px - ep) * pos, "reason": "st_flip"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    trades.append({"pnl": (px - ep) * pos, "reason": "eod"}); pos = 0; continue
            elif pos < 0:
                if float(b["high"]) >= sl:
                    trades.append({"pnl": (ep - sl) * abs(pos), "reason": "sl"}); pos = 0; continue
                if float(b["low"]) <= tp:
                    trades.append({"pnl": (ep - tp) * abs(pos), "reason": "tp"}); pos = 0; continue
                if int(b["st_dir"]) == 1 and int(pb["st_dir"]) == -1:
                    trades.append({"pnl": (ep - px) * abs(pos), "reason": "st_flip"}); pos = 0; continue
                if tod >= FORCE_CLOSE:
                    trades.append({"pnl": (ep - px) * abs(pos), "reason": "eod"}); pos = 0; continue

            if pos == 0 and orders < max_orders and ENTRY_START <= tod < ENTRY_END:
                atr_v = float(b["atr"]); adx_v = float(b["adx"])
                if pd.isna(atr_v) or atr_v <= 0 or adx_v < adx_min:
                    continue
                cross_up   = (float(pb["ema_fast"]) <= float(pb["ema_slow"])) and \
                             (float(b["ema_fast"]) > float(b["ema_slow"]))
                cross_down = (float(pb["ema_fast"]) >= float(pb["ema_slow"])) and \
                             (float(b["ema_fast"]) < float(b["ema_slow"]))
                qty = max(1, int(risk_per_trade / (atr_v * atr_sl_mult)))
                if cross_up and int(b["st_dir"]) == 1:
                    ep = px; sl = px - atr_sl_mult * atr_v; tp = px + atr_tp_mult * atr_v
                    pos = qty; orders += 1
                elif cross_down and int(b["st_dir"]) == -1:
                    ep = px; sl = px + atr_sl_mult * atr_v; tp = px - atr_tp_mult * atr_v
                    pos = -qty; orders += 1

        if pos != 0 and not day.empty:
            cp = float(day.iloc[-1]["close"])
            trades.append({"pnl": (cp - ep) * pos if pos > 0 else (ep - cp) * abs(pos), "reason": "eod_final"})

    return _metrics(trades, capital, "ema_supertrend_equity", symbol)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def _qty_for_deployment(symbol: str, strategy: str, api_key: str, host: str) -> int:
    """Estimate deployment quantity based on current price and risk per trade."""
    try:
        client = APIClient(api_key=api_key, host=host)
        today  = datetime.now().strftime("%Y-%m-%d")
        df = client.history(symbol=symbol, exchange=EXCHANGE, interval="5m",
                            start_date=today, end_date=today)
        if df is not None and not df.empty:
            price = float(df.iloc[-1]["close"])
            risk  = {"orb_equity_volume": RISK_ORB,
                     "vwap_rsi_equity":   RISK_VWAP,
                     "ema_supertrend_equity": RISK_EMA}.get(strategy, RISK_ORB)
            sl    = {"orb_equity_volume": 0.5,
                     "vwap_rsi_equity":   0.4,
                     "ema_supertrend_equity": 1.5}.get(strategy, 0.5)
            if strategy == "ema_supertrend_equity":
                atr = calculate_atr(df, period=14)
                atr_val = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else price * 0.005
                return max(1, int(risk / (atr_val * 1.5)))
            return max(1, int(risk / (price * sl / 100)))
    except Exception:
        pass
    return 1


def main(days: int = 90, verbose: bool = False):
    print("=" * 70)
    print(f"  Equity Strategy Backtest — ₹5L Allocation ({days}d, 5m)")
    print(f"  Candidates: {', '.join(CANDIDATES)}")
    print(f"  Criteria: PF > {PF_MIN} AND DD < {DD_MAX}%")
    print(f"  Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # Cache fetched data (fetch once per symbol)
    all_syms = list(dict.fromkeys(ORB_CANDIDATES + CANDIDATES))   # deduplicated
    data_cache: dict[str, pd.DataFrame] = {}
    for sym in all_syms:
        print(f"  Fetching {sym} ({days}d 5m)...", end=" ", flush=True)
        df = _fetch(sym, days)
        data_cache[sym] = df
        print(f"{len(df)} bars" if not df.empty else "NO DATA")

    print()

    strategy_configs = [
        ("VWAP RSI Reversion",  "vwap_rsi_equity",        _backtest_vwap,   CAPITAL_VWAP, CANDIDATES),
        ("EMA SuperTrend",      "ema_supertrend_equity",  _backtest_ema_st, CAPITAL_EMA,  CANDIDATES),
    ]

    winners = {}

    # ── ORB: scan two window sizes to pick best ──────────────────────────────
    print(f"\n── ORB Volume (₹{CAPITAL_ORB//1000}K allocation) — scanning 15m + 30m ORB ──────────────────")
    orb_results_all = []
    for orb_min in (15, 30):
        entry_start = 9 * 60 + orb_min
        label = f"{orb_min}m"
        for sym in ORB_CANDIDATES:
            df = data_cache.get(sym, pd.DataFrame())
            if df.empty:
                continue
            try:
                r = _backtest_orb(df, sym, orb_minutes=orb_min)
                r["orb_minutes"] = orb_min
                status = "PASS ✓" if r.get("pass") else "FAIL ✗"
                print(f"  {sym:12s} [{label}]  PF={r.get('profit_factor', 0):5.2f}  "
                      f"DD={r.get('max_drawdown_pct', 0):5.2f}%  "
                      f"WR={r.get('win_rate', 0):5.1f}%  "
                      f"Trades={r.get('total_trades', 0):3d}  "
                      f"PnL=₹{r.get('net_pnl', 0):8,.0f}  {status}")
                if r.get("status") == "success":
                    orb_results_all.append(r)
            except Exception as e:
                print(f"  {sym} [{label}]: ERROR — {e}")

    pass_results = [r for r in orb_results_all if r.get("pass")]
    if pass_results:
        best_orb = max(pass_results, key=lambda x: x["profit_factor"])
        winners["orb_equity_volume"] = best_orb
        print(f"\n  ★ BEST: {best_orb['symbol']} [{best_orb['orb_minutes']}m ORB]  (PF={best_orb['profit_factor']:.2f})")
    else:
        print(f"\n  ✗ No symbol/window met criteria for ORB Volume")
        if orb_results_all:
            fallback = max(orb_results_all, key=lambda x: x["profit_factor"])
            winners["orb_equity_volume"] = {**fallback, "pass": False}
            print(f"  (Fallback best: {fallback['symbol']} [{fallback['orb_minutes']}m]  "
                  f"PF={fallback['profit_factor']:.2f})")

    for strat_label, strat_name, backtest_fn, capital, sym_list in strategy_configs:
        print(f"\n── {strat_label} (₹{capital//1000}K allocation) ──────────────────")
        results = []
        for sym in sym_list:
            df = data_cache.get(sym, pd.DataFrame())
            if df.empty:
                print(f"  {sym}: NO DATA — skipped")
                continue
            try:
                r = backtest_fn(df, sym)
                status = "PASS ✓" if r.get("pass") else "FAIL ✗"
                print(f"  {sym:12s}  PF={r.get('profit_factor', 0):5.2f}  "
                      f"DD={r.get('max_drawdown_pct', 0):5.2f}%  "
                      f"WR={r.get('win_rate', 0):5.1f}%  "
                      f"Trades={r.get('total_trades', 0):3d}  "
                      f"PnL=₹{r.get('net_pnl', 0):8,.0f}  {status}")
                if verbose:
                    print(f"           GrossProfit=₹{r.get('gross_profit',0):,.0f}  "
                          f"GrossLoss=₹{r.get('gross_loss',0):,.0f}")
                if r.get("pass") and r.get("status") == "success":
                    results.append(r)
            except Exception as e:
                print(f"  {sym}: ERROR — {e}")

        if results:
            best = max(results, key=lambda x: x["profit_factor"])
            winners[strat_name] = best
            print(f"\n  ★ BEST: {best['symbol']}  (PF={best['profit_factor']:.2f})")
        else:
            print(f"\n  ✗ No symbol met criteria for {strat_label}")
            # Pick best available even if not passing (for operator decision)
            all_results = []
            for sym in sym_list:
                df = data_cache.get(sym, pd.DataFrame())
                if not df.empty:
                    try:
                        r = backtest_fn(df, sym)
                        if r.get("status") == "success":
                            all_results.append(r)
                    except Exception:
                        pass
            if all_results:
                fallback = max(all_results, key=lambda x: x["profit_factor"])
                winners[strat_name] = {**fallback, "pass": False}
                print(f"  (Fallback best: {fallback['symbol']}  PF={fallback['profit_factor']:.2f})")

    # ─── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    all_pass = True
    deploy_info = {}

    for strat_name in ["orb_equity_volume", "vwap_rsi_equity", "ema_supertrend_equity"]:
        w = winners.get(strat_name)
        if w:
            sym    = w["symbol"]
            passed = w.get("pass", False)
            all_pass = all_pass and passed
            qty    = _qty_for_deployment(sym, strat_name, API_KEY, HOST)
            deploy_info[strat_name] = {"symbol": sym, "qty": qty, "pass": passed}
            print(f"  {strat_name:30s}  {sym:12s}  "
                  f"PF={w['profit_factor']:.2f}  DD={w['max_drawdown_pct']:.1f}%  "
                  f"Qty={qty}  {'✓' if passed else '⚠ WARN'}")
        else:
            print(f"  {strat_name:30s}  NO WINNER FOUND")

    # ─── Deployment commands ───────────────────────────────────────────────────
    if deploy_info:
        print("\n" + "=" * 70)
        if not all_pass:
            print("  ⚠  WARNING: one or more strategies did NOT meet PF>2.5 / DD<6%")
            print("     Review results above before deploying.")
        else:
            print("  ✓  All strategies passed criteria. Deployment commands:")
        print("=" * 70)
        print()

        orb  = deploy_info.get("orb_equity_volume")
        vwap = deploy_info.get("vwap_rsi_equity")
        ema  = deploy_info.get("ema_supertrend_equity")

        print("  cd ~/openalgo/openalgo")
        print()

        if orb:
            orb_min_val = winners.get("orb_equity_volume", {}).get("orb_minutes", 30)
            print(f"  # Strategy 1: ORB Volume — {orb['symbol']} [{orb_min_val}m ORB] (₹2L)")
            print(f"  OPENALGO_HOST=http://127.0.0.1:5002 \\")
            print(f"  SYMBOL={orb['symbol']} EXCHANGE=NSE PRODUCT=MIS \\")
            print(f"  QUANTITY={orb['qty']} ORB_MINUTES={orb_min_val} ORB_BUFFER_PCT=0.1 \\")
            print(f"  SL_PCT=0.5 TP_PCT=1.5 VOLUME_MULTIPLIER=1.7 MAX_HOLD_MIN=90 GAP_FILTER=true MAX_ORDERS_PER_DAY=2 \\")
            print(f"  nohup .venv/bin/python3 strategies/scripts/orb_equity_volume.py \\")
            print(f"  > /tmp/orb_equity.log 2>&1 &")
            print()

        if vwap:
            print(f"  # Strategy 2: VWAP RSI — {vwap['symbol']} (₹1.5L)")
            print(f"  OPENALGO_HOST=http://127.0.0.1:5002 \\")
            print(f"  SYMBOL={vwap['symbol']} EXCHANGE=NSE PRODUCT=MIS \\")
            print(f"  QUANTITY={vwap['qty']} SL_PCT=0.4 VWAP_STD_MULT=1.5 \\")
            print(f"  RSI_OVERSOLD=30 RSI_OVERBOUGHT=70 MAX_ORDERS_PER_DAY=4 \\")
            print(f"  nohup .venv/bin/python3 strategies/scripts/vwap_rsi_equity.py \\")
            print(f"  > /tmp/vwap_equity.log 2>&1 &")
            print()

        if ema:
            print(f"  # Strategy 3: EMA SuperTrend — {ema['symbol']} (₹1.5L)")
            print(f"  OPENALGO_HOST=http://127.0.0.1:5002 \\")
            print(f"  SYMBOL={ema['symbol']} EXCHANGE=NSE PRODUCT=MIS \\")
            print(f"  QUANTITY={ema['qty']} ATR_SL_MULT=1.5 ATR_TP_MULT=3.0 \\")
            print(f"  SUPERTREND_MULT=2.5 ADX_MIN=15 MAX_ORDERS_PER_DAY=4 \\")
            print(f"  nohup .venv/bin/python3 strategies/scripts/ema_supertrend_equity.py \\")
            print(f"  > /tmp/ema_equity.log 2>&1 &")
            print()

        print("  # Monitor:")
        print("  tail -f /tmp/orb_equity.log /tmp/vwap_equity.log /tmp/ema_equity.log")
        print()

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Equity Strategy Backtest Runner — ₹5L")
    parser.add_argument("--days",    type=int,  default=90,    help="Lookback days (default 90)")
    parser.add_argument("--verbose", action="store_true",      help="Show extra metrics")
    args = parser.parse_args()
    main(days=args.days, verbose=args.verbose)
