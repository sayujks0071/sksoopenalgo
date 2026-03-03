#!/usr/bin/env python3
"""
run_mcx_backtest_sweep.py
─────────────────────────
Parameter sweep for 3 MCX strategies:
  1. MCX_SILVER   — SILVER.NS 15m proxy   (30 units ≈ 1 Silver Mini lot)
  2. MCX_GOLD     — GOLDBEES.NS 15m proxy (100 units ≈ 1 Gold Mini lot)
  3. MCX_CRUDEOIL — BZ=F (Brent) 15m      ($1 × ₹85 × 10 bbl = ₹850/lot)

Exit logic: ATR-based SL + TP (fixes CrudeOil PF=0.76 slow-exit problem)
Targets:    PF > 2.0  |  MaxDD < 6%  |  Trades ≥ 12

Usage: python run_mcx_backtest_sweep.py [--days N] [--min-trades N]
"""
import argparse
import itertools
import json
import os
import pickle
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

TODAY = datetime.today().strftime("%Y-%m-%d")
CACHE_DIR = tempfile.gettempdir()


# ─── TARGETS ──────────────────────────────────────────────────────────────────
TARGET_PF    = 2.0
TARGET_DD    = 6.0
MIN_TRADES   = 12


# ─── INDICATOR HELPERS ────────────────────────────────────────────────────────

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    ag = gain.ewm(com=period - 1, min_periods=period).mean()
    al = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, min_periods=period).mean()


def adx_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    idx = df.index
    up   = h.diff()
    down = -l.diff()
    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=idx)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=idx)
    tr = pd.concat(
        [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    atr_s = tr.ewm(span=period, min_periods=period).mean()
    pdi   = 100 * plus_dm.ewm(span=period, min_periods=period).mean() / atr_s
    mdi   = 100 * minus_dm.ewm(span=period, min_periods=period).mean() / atr_s
    dx    = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(span=period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, min_periods=period).mean()


# ─── METRICS ──────────────────────────────────────────────────────────────────

def trade_metrics(trades: list, initial_cap: float = 200_000) -> dict:
    if not trades:
        return {"pf": 0.0, "wr_pct": 0.0, "dd_pct": 0.0, "trades": 0, "net_pnl": 0.0}
    pnls       = [t["pnl"] for t in trades]
    wins       = [p for p in pnls if p > 0]
    losses     = [p for p in pnls if p <= 0]
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf  = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    wr  = round(100 * len(wins) / len(pnls), 1)
    equity   = initial_cap + pd.Series(pnls).cumsum()
    roll_max = equity.cummax()
    dd_abs   = (roll_max - equity).max()
    dd_pct   = round(100 * dd_abs / roll_max.max(), 2)
    return {
        "pf":      pf,
        "wr_pct":  wr,
        "dd_pct":  dd_pct,
        "trades":  len(pnls),
        "net_pnl": round(sum(pnls), 0),
    }


def passes_targets(m: dict) -> bool:
    return (
        m["pf"]     >= TARGET_PF  and
        m["dd_pct"] <= TARGET_DD  and
        m["trades"] >= MIN_TRADES
    )


# ─── DATA FETCH + CACHE ───────────────────────────────────────────────────────

def fetch_cached(ticker: str, interval: str = "15m", days: int = 58) -> pd.DataFrame:
    """Download yfinance data with file-based caching (invalidates after 3 hours)."""
    cache_file = os.path.join(CACHE_DIR, f"mcx_sweep_{ticker.replace('=','_').replace('.','_')}_{interval}_{days}.pkl")
    if os.path.exists(cache_file):
        age_hours = (datetime.now().timestamp() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 3:
            with open(cache_file, "rb") as f:
                return pickle.load(f)

    end   = datetime.today()
    start = end - timedelta(days=days)
    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if df.empty:
        raise ValueError(f"No data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)

    with open(cache_file, "wb") as f:
        pickle.dump(df, f)
    return df


# ─── CORE BACKTEST ENGINE (ATR SL/TP exit) ───────────────────────────────────

def backtest_atr_trend(
    df: pd.DataFrame,
    p: dict,
    lot_value: float,
    capital: float,
) -> dict:
    """
    Generic ATR-based trend strategy.
    Entry: EMA crossover + RSI band + ADX threshold + prev-bar price confirmation
    Exit:  ATR-based fixed SL and TP (prevents slow-exit overtrading)

    p keys:
      ema_fast, ema_slow     — EMA periods
      rsi_buy, rsi_sell      — RSI thresholds for entry
      adx_threshold          — minimum ADX for trend confirmation
      atr_sl                 — ATR multiplier for stop loss
      atr_tp                 — ATR multiplier for take profit
    """
    ema_f  = p["ema_fast"]
    ema_s  = p["ema_slow"]
    rsi_b  = p["rsi_buy"]
    rsi_s  = p["rsi_sell"]
    adx_th = p["adx_threshold"]
    sl_m   = p["atr_sl"]
    tp_m   = p["atr_tp"]

    min_bars = max(ema_s, 30)

    trades   = []
    position = None  # {"side", "entry", "sl", "tp"}

    for i in range(min_bars, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]

        if any(pd.isna(bar[c]) for c in ["rsi14", "adx14", "ema_f", "ema_s", "atr14"]):
            continue

        close = bar["close"]
        atr14 = bar["atr14"]

        if position is not None:
            side = position["side"]
            # Check SL/TP hit
            if side == "BUY":
                exit_now = close <= position["sl"] or close >= position["tp"]
                mul = 1
            else:
                exit_now = close >= position["sl"] or close <= position["tp"]
                mul = -1

            if exit_now:
                pnl = mul * (close - position["entry"]) * lot_value
                trades.append({"pnl": pnl, "entry": position["entry"],
                               "exit": close, "side": side})
                position = None
        else:
            # Entry conditions
            adx_ok   = bar["adx14"] > adx_th
            ema_bull  = bar["ema_f"] > bar["ema_s"]
            ema_bear  = bar["ema_f"] < bar["ema_s"]

            if (adx_ok and ema_bull and bar["rsi14"] > rsi_b
                    and close > prev["close"]):
                position = {
                    "side":  "BUY",
                    "entry": close,
                    "sl":    close - sl_m * atr14,
                    "tp":    close + tp_m * atr14,
                }
            elif (adx_ok and ema_bear and bar["rsi14"] < rsi_s
                    and close < prev["close"]):
                position = {
                    "side":  "SELL",
                    "entry": close,
                    "sl":    close + sl_m * atr14,
                    "tp":    close - tp_m * atr14,
                }

    # Close open position at last bar
    if position is not None:
        last = df.iloc[-1]
        mul  = 1 if position["side"] == "BUY" else -1
        pnl  = mul * (last["close"] - position["entry"]) * lot_value
        trades.append({"pnl": pnl, "entry": position["entry"],
                       "exit": last["close"], "side": position["side"]})

    return trade_metrics(trades, capital)


def prepare_df(df: pd.DataFrame, ema_fast: int, ema_slow: int) -> pd.DataFrame:
    """Pre-compute indicators into a copy of df."""
    df = df.copy()
    df["ema_f"] = ema(df["close"], ema_fast)
    df["ema_s"] = ema(df["close"], ema_slow)
    df["rsi14"] = rsi(df["close"], 14)
    df["atr14"] = atr(df, 14)
    df["adx14"] = adx_series(df, 14)
    return df


# ─── PARAMETER GRIDS ──────────────────────────────────────────────────────────

def make_grid():
    """Return a list of parameter dicts for sweeping (Silver)."""
    ema_pairs   = [(9, 21), (12, 26), (21, 50)]
    rsi_bands   = [(55, 45), (58, 42), (60, 40)]
    adx_threshs = [20, 25, 30]
    atr_sl_muls = [1.5, 2.0, 2.5]
    atr_tp_muls = [2.5, 3.5, 5.0]

    grid = []
    for (ef, es), (rb, rs), adx, sl, tp in itertools.product(
            ema_pairs, rsi_bands, adx_threshs, atr_sl_muls, atr_tp_muls):
        grid.append({
            "ema_fast":      ef,
            "ema_slow":      es,
            "rsi_buy":       rb,
            "rsi_sell":      rs,
            "adx_threshold": adx,
            "atr_sl":        sl,
            "atr_tp":        tp,
        })
    return grid


def make_gold_grid():
    """Wider grid for Gold — higher TP range to achieve PF>2."""
    ema_pairs   = [(9, 21), (12, 26), (21, 50), (9, 50)]
    rsi_bands   = [(55, 45), (58, 42), (60, 40), (52, 48)]
    adx_threshs = [20, 25, 30]
    atr_sl_muls = [1.5, 2.0, 2.5]
    atr_tp_muls = [3.5, 5.0, 7.0, 10.0]   # extended TP range

    grid = []
    for (ef, es), (rb, rs), adx, sl, tp in itertools.product(
            ema_pairs, rsi_bands, adx_threshs, atr_sl_muls, atr_tp_muls):
        grid.append({
            "ema_fast":      ef,
            "ema_slow":      es,
            "rsi_buy":       rb,
            "rsi_sell":      rs,
            "adx_threshold": adx,
            "atr_sl":        sl,
            "atr_tp":        tp,
        })
    return grid


def make_crude_grid():
    """Wider grid for CrudeOil — aggressive sweep, higher RR to fix PF=0.76."""
    ema_pairs   = [(9, 21), (12, 26), (21, 50), (9, 50)]
    rsi_bands   = [(55, 45), (58, 42), (60, 40), (62, 38)]
    adx_threshs = [25, 28, 30, 35]
    atr_sl_muls = [1.5, 2.0, 2.5]
    atr_tp_muls = [4.0, 6.0, 8.0, 10.0]  # high RR needed (crude is volatile)

    grid = []
    for (ef, es), (rb, rs), adx, sl, tp in itertools.product(
            ema_pairs, rsi_bands, adx_threshs, atr_sl_muls, atr_tp_muls):
        grid.append({
            "ema_fast":      ef,
            "ema_slow":      es,
            "rsi_buy":       rb,
            "rsi_sell":      rs,
            "adx_threshold": adx,
            "atr_sl":        sl,
            "atr_tp":        tp,
        })
    return grid


# ─── SWEEP RUNNER ─────────────────────────────────────────────────────────────

def run_sweep(name: str, raw_df: pd.DataFrame, lot_value: float,
              capital: float, grid: list, verbose: bool = False) -> dict:
    """
    Run parameter sweep and return best result.
    Returns dict with keys: best_params, best_metrics, all_passing, top5.
    """
    all_passing = []
    top_by_pf   = []

    # Pre-compute unique EMA pairs to avoid redundant calculations
    seen_ema_dfs = {}

    total = len(grid)
    print(f"  Sweeping {total:,} combos for {name}…")
    dot_every = max(1, total // 20)

    for i, p in enumerate(grid):
        if i % dot_every == 0:
            sys.stdout.write(f"\r  Progress: {i}/{total} ({100*i//total}%)  ")
            sys.stdout.flush()

        ema_key = (p["ema_fast"], p["ema_slow"])
        if ema_key not in seen_ema_dfs:
            seen_ema_dfs[ema_key] = prepare_df(raw_df, p["ema_fast"], p["ema_slow"])
        df_prep = seen_ema_dfs[ema_key]

        m = backtest_atr_trend(df_prep, p, lot_value, capital)
        m["params"] = p

        top_by_pf.append(m)

        if passes_targets(m):
            all_passing.append(m)

    sys.stdout.write("\r" + " " * 60 + "\r")  # clear progress line

    # Sort by PF descending
    top_by_pf.sort(key=lambda x: x["pf"], reverse=True)
    all_passing.sort(key=lambda x: (x["pf"], -x["dd_pct"]), reverse=True)

    top5 = top_by_pf[:5]

    if all_passing:
        best = all_passing[0]
        print(f"  ✅ {name}: {len(all_passing)} combos PASSED targets  |  Best PF={best['pf']:.2f}, DD={best['dd_pct']:.1f}%, Trades={best['trades']}, PnL=₹{best['net_pnl']:,.0f}")
    else:
        best = top_by_pf[0] if top_by_pf else {}
        print(f"  ⚠️  {name}: 0 combos met all targets. Best found: PF={best.get('pf',0):.2f}, DD={best.get('dd_pct',0):.1f}%, Trades={best.get('trades',0)}")

    return {
        "best":        best,
        "all_passing": all_passing,
        "top5":        top5,
    }


# ─── STRATEGY-SPECIFIC WRAPPERS ───────────────────────────────────────────────

def sweep_silver(days: int) -> dict:
    print("\n[1/3] MCX_SILVER  (SILVER.NS 15m — 30 units per lot)")
    try:
        raw = fetch_cached("SILVER.NS", interval="15m", days=days)
        print(f"  Data: {len(raw)} bars from {raw.index[0].date()} to {raw.index[-1].date()}")
    except Exception as e:
        print(f"  ERROR fetching SILVER.NS: {e}")
        return {}

    # SILVER.NS: 30 units ≈ 1 Silver Mini lot (30kg)
    LOT_VALUE = 30     # ₹ per ₹1 move in SILVER.NS per lot
    CAPITAL   = 150_000

    return run_sweep("MCX_SILVER", raw, LOT_VALUE, CAPITAL, make_grid())


def sweep_gold(days: int) -> dict:
    print("\n[2/3] MCX_GOLD    (GOLDBEES.NS 15m — 100 units per lot)")
    try:
        raw = fetch_cached("GOLDBEES.NS", interval="15m", days=days)
        print(f"  Data: {len(raw)} bars from {raw.index[0].date()} to {raw.index[-1].date()}")
    except Exception as e:
        print(f"  ERROR fetching GOLDBEES.NS: {e}")
        return {}

    # GOLDBEES.NS: 100 units ≈ 1 Gold Mini lot (100g)
    LOT_VALUE = 100    # ₹ per ₹1 move in GOLDBEES.NS per lot
    CAPITAL   = 100_000

    return run_sweep("MCX_GOLD", raw, LOT_VALUE, CAPITAL, make_gold_grid())


def filter_mcx_hours(df: pd.DataFrame) -> pd.DataFrame:
    """Filter BZ=F data to MCX trading hours (09:00–23:30 IST)."""
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(ist)
    elif str(df.index.tz) != "Asia/Kolkata":
        df.index = df.index.tz_convert(ist)
    # Keep bars from 09:00 to 23:30 IST only (MCX hours)
    hours = df.index.hour + df.index.minute / 60
    mask  = (hours >= 9.0) & (hours <= 23.5)
    filtered = df[mask]
    return filtered


def sweep_crudeoil(days: int) -> dict:
    print("\n[3/3] MCX_CRUDEOIL (BZ=F 15m — $1 move = ₹850 per lot)")
    try:
        raw = fetch_cached("BZ=F", interval="15m", days=days)
        raw = filter_mcx_hours(raw)  # restrict to MCX trading window
        print(f"  Data: {len(raw)} bars from {raw.index[0].date()} to {raw.index[-1].date()} (MCX hours only)")
    except Exception as e:
        print(f"  ERROR fetching BZ=F: {e}")
        return {}

    # BZ=F Brent Crude in USD. $1 move × ₹85 × 10 bbl = ₹850/lot (MCX Mini)
    LOT_VALUE = 850    # ₹ per $1 move in BZ=F per lot
    CAPITAL   = 100_000

    return run_sweep("MCX_CRUDEOIL", raw, LOT_VALUE, CAPITAL, make_crude_grid())


# ─── REPORT + DEPLOYMENT COMMANDS ─────────────────────────────────────────────

def print_params_table(name: str, result: dict):
    best = result.get("best", {})
    if not best:
        print(f"\n  {name}: No result available.")
        return

    p = best.get("params", {})
    m_keys = ["pf", "wr_pct", "dd_pct", "trades", "net_pnl"]

    print(f"\n{'─'*60}")
    print(f"  {name}  —  Best Parameters")
    print(f"{'─'*60}")
    print(f"  EMA:   {p.get('ema_fast')}/{p.get('ema_slow')}"
          f"   RSI buy>{p.get('rsi_buy')} / sell<{p.get('rsi_sell')}"
          f"   ADX>{p.get('adx_threshold')}")
    print(f"  SL:    {p.get('atr_sl')}×ATR    TP: {p.get('atr_tp')}×ATR")
    print(f"  PF={best['pf']:.2f}  WR={best['wr_pct']:.1f}%"
          f"  DD={best['dd_pct']:.1f}%"
          f"  Trades={best['trades']}"
          f"  PnL=₹{best['net_pnl']:,.0f}")
    status = "✅ TARGETS MET" if passes_targets(best) else "⚠️  BEST AVAILABLE (targets not fully met)"
    print(f"  {status}")

    if result.get("top5"):
        print(f"\n  Top-5 combos (by PF):")
        print(f"  {'EMA':10} {'RSI-B/S':10} {'ADX':5} {'SL':5} {'TP':5} {'PF':6} {'DD%':6} {'Tr':4}")
        for r in result["top5"]:
            pp = r.get("params", {})
            print(f"  {pp.get('ema_fast')}/{pp.get('ema_slow'):<7}"
                  f" {pp.get('rsi_buy')}/{pp.get('rsi_sell'):<7}"
                  f" {pp.get('adx_threshold'):<5}"
                  f" {pp.get('atr_sl'):<5}"
                  f" {pp.get('atr_tp'):<5}"
                  f" {r['pf']:<6.2f}"
                  f" {r['dd_pct']:<6.1f}"
                  f" {r['trades']:<4}")


def print_deployment_commands(results: dict):
    """Print ready-to-run deployment commands for winning strategies."""

    OPENALGO_APIKEY = "372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
    OPENALGO_HOST   = "http://127.0.0.1:5002"
    SCRIPTS_DIR     = "/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/scripts"
    LOGS_DIR        = "/Users/mac/sksoopenalgo/openalgo/openalgo/strategies/logs"

    # Map strategy to script and MCX symbol
    config_map = {
        "silver": {
            "script":   "mcx_commodity_momentum_strategy.py",
            "symbol":   "SILVERM30APR26FUT",
            "exchange": "MCX",
            "product":  "NRML",
            "qty":      1,
            "log":      "mcx_silver_live.log",
        },
        "gold": {
            "script":   "mcx_gold_momentum_strategy.py",
            "symbol":   "GOLDM02APR26FUT",
            "exchange": "MCX",
            "product":  "NRML",
            "qty":      1,
            "log":      "mcx_gold_live.log",
        },
        "crudeoil": {
            "script":   "mcx_atr_trend_strategy.py",   # new unified script
            "symbol":   "CRUDEOILM18MAR26FUT",
            "exchange": "MCX",
            "product":  "NRML",
            "qty":      1,
            "log":      "mcx_crudeoil_live.log",
        },
    }

    print(f"\n{'='*60}")
    print("  DEPLOYMENT COMMANDS  (run at MCX open 17:00 IST)")
    print(f"{'='*60}")

    for key, label in [("silver","MCX_SILVER"), ("gold","MCX_GOLD"), ("crudeoil","MCX_CRUDEOIL")]:
        result = results.get(key, {})
        best   = result.get("best", {})
        if not best:
            print(f"\n# {label}: No valid result — skip deployment")
            continue

        cfg = config_map[key]
        p   = best.get("params", {})
        passed = passes_targets(best)
        status = "DEPLOY" if passed else "REVIEW (targets not met)"

        print(f"\n# ── {label} [{status}] ──")
        print(f"# PF={best['pf']:.2f} DD={best['dd_pct']:.1f}% Trades={best['trades']} PnL=₹{best['net_pnl']:,.0f}")

        cmd_parts = [
            f"nohup env",
            f"OPENALGO_APIKEY={OPENALGO_APIKEY}",
            f"OPENALGO_HOST={OPENALGO_HOST}",
            f"python3 {SCRIPTS_DIR}/{cfg['script']}",
            f"--symbol {cfg['symbol']}",
            f"--exchange {cfg['exchange']}",
            f"--product {cfg['product']}",
            f"--quantity {cfg['qty']}",
            f"--interval 15m",
            f"--host {OPENALGO_HOST}",
            # Pass winning params as CLI args (these args need to be added to the script)
            f"--ema-fast {p.get('ema_fast', 9)}",
            f"--ema-slow {p.get('ema_slow', 21)}",
            f"--rsi-buy {p.get('rsi_buy', 55)}",
            f"--rsi-sell {p.get('rsi_sell', 45)}",
            f"--adx-threshold {p.get('adx_threshold', 25)}",
            f"--atr-sl {p.get('atr_sl', 2.0)}",
            f"--atr-tp {p.get('atr_tp', 3.5)}",
            f"> {LOGS_DIR}/{cfg['log']} 2>&1 &",
        ]
        print("  " + " \\\n  ".join(cmd_parts))


def save_results(results: dict):
    """Save winning configurations to JSON."""
    out_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "mcx_sweep_results.json"
    )
    serializable = {}
    for key, result in results.items():
        best = result.get("best", {})
        serializable[key] = {
            "params":   best.get("params", {}),
            "metrics":  {k: v for k, v in best.items() if k != "params"},
            "passed":   passes_targets(best) if best else False,
            "top5":     [
                {"params": r.get("params", {}),
                 "metrics": {k: v for k, v in r.items() if k != "params"}}
                for r in result.get("top5", [])
            ],
        }
    class _Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            return super().default(obj)

    with open(out_file, "w") as f:
        json.dump(serializable, f, indent=2, cls=_Encoder)
    print(f"\n  Results saved to: {out_file}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    global TARGET_PF, TARGET_DD, MIN_TRADES  # declared first, before any usage

    parser = argparse.ArgumentParser(description="MCX Strategy Parameter Sweep")
    parser.add_argument("--days",       type=int, default=58,
                        help="Backtest window in days (max 58 for 15m yfinance)")
    parser.add_argument("--min-trades", type=int, default=12,
                        help="Minimum trades threshold")
    parser.add_argument("--target-pf",  type=float, default=2.0,
                        help="Target profit factor")
    parser.add_argument("--target-dd",  type=float, default=6.0,
                        help="Target max drawdown %%")
    parser.add_argument("--skip-cache", action="store_true",
                        help="Force fresh data download (ignore cache)")
    args = parser.parse_args()

    # Apply user overrides
    TARGET_PF  = args.target_pf
    TARGET_DD  = args.target_dd
    MIN_TRADES = args.min_trades

    if args.skip_cache:
        # Remove any cached files
        import glob
        for f in glob.glob(os.path.join(CACHE_DIR, "mcx_sweep_*.pkl")):
            os.remove(f)
        print("  Cache cleared.")

    print("\n" + "="*60)
    print(f"  MCX PARAMETER SWEEP — {TODAY}")
    print(f"  Targets: PF≥{TARGET_PF}  DD≤{TARGET_DD}%  Trades≥{MIN_TRADES}")
    print(f"  Window: {args.days} days of 15m bars")
    print("="*60)

    # Run sweeps for all 3 instruments
    results = {}
    results["silver"]   = sweep_silver(args.days)
    results["gold"]     = sweep_gold(args.days)
    results["crudeoil"] = sweep_crudeoil(args.days)

    # Print detailed reports
    print(f"\n\n{'='*60}")
    print("  RESULTS SUMMARY")
    print(f"{'='*60}")

    for key, label in [("silver","MCX_SILVER"), ("gold","MCX_GOLD"), ("crudeoil","MCX_CRUDEOIL")]:
        print_params_table(label, results.get(key, {}))

    # Print deployment commands
    print_deployment_commands(results)

    # Save to JSON
    save_results(results)

    # Final summary
    print(f"\n{'='*60}")
    passed = []
    failed = []
    for key, label in [("silver","SILVER"), ("gold","GOLD"), ("crudeoil","CRUDEOIL")]:
        best = results.get(key, {}).get("best", {})
        if best and passes_targets(best):
            passed.append(label)
        else:
            failed.append(label)

    if passed:
        print(f"  ✅ READY TO DEPLOY: {', '.join(passed)}")
    if failed:
        print(f"  ⚠️  NEEDS REVIEW:    {', '.join(failed)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
