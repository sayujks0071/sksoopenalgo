#!/usr/bin/env python3
"""
Standalone equity strategy backtests using yfinance data.
Strategies: SuperTrend_NIFTY, AI_Hybrid_RELIANCE, MCX_SILVER

Run: python run_equity_backtests.py
"""
import json
import math
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

TODAY = datetime.today().strftime("%Y-%m-%d")

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
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, min_periods=period).mean()


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma, sma + mult * std, sma - mult * std


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    idx = df.index
    up   = h.diff()
    down = -l.diff()
    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=idx)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=idx)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_s = tr.ewm(span=period, min_periods=period).mean()
    pdi   = 100 * plus_dm.ewm(span=period, min_periods=period).mean() / atr_s
    mdi   = 100 * minus_dm.ewm(span=period, min_periods=period).mean() / atr_s
    dx    = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(span=period, min_periods=period).mean()


def intraday_vwap(df: pd.DataFrame) -> pd.Series:
    """Reset VWAP each calendar day."""
    typ = (df["high"] + df["low"] + df["close"]) / 3
    df2 = df.copy()
    df2["_typ"] = typ
    df2["_date"] = df.index.date
    df2["_cum_tv"] = df2.groupby("_date").apply(
        lambda g: (g["_typ"] * g["volume"]).cumsum()
    ).droplevel(0)
    df2["_cum_v"]  = df2.groupby("_date")["volume"].cumsum()
    return df2["_cum_tv"] / df2["_cum_v"].replace(0, np.nan)


def poc(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """Rolling POC: close of the bar with max volume in the last `lookback` bars."""
    result = pd.Series(np.nan, index=df.index)
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback : i]
        result.iloc[i] = window.loc[window["volume"].idxmax(), "close"]
    return result


# ─── METRICS ─────────────────────────────────────────────────────────────────

def trade_metrics(trades: list, initial_cap: float = 200_000) -> dict:
    if not trades:
        return {"pf": 0.0, "wr_pct": 0.0, "dd_pct": 0.0, "trades": 0, "net_pnl": 0.0}
    pnls   = [t["pnl"] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else 99.0
    wr = round(100 * len(wins) / len(pnls), 1)
    # equity curve → max drawdown
    equity = initial_cap + pd.Series(pnls).cumsum()
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


# ─── DATA FETCH ──────────────────────────────────────────────────────────────

def fetch(ticker: str, interval: str = "5m", days: int = 58) -> pd.DataFrame:
    """Download OHLCV via yfinance and normalise column names."""
    end   = datetime.today()
    start = end - timedelta(days=days)
    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No data returned for {ticker}")
    # Flatten MultiIndex if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    # Remove pre/post market rows (only keep 9:15–15:30 IST)
    if hasattr(df.index, "tz") and df.index.tz is not None:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)
    return df


# ─── STRATEGY 1: SuperTrend_NIFTY ────────────────────────────────────────────

def backtest_supertrend_nifty(days: int = 58) -> dict:
    """
    VWAP reversion / momentum on NIFTY 5-min bars.
    Symbol: NIFTYBEES.NS (NIFTY 50 ETF proxy — has real volume; ^NSEI has zero volume)
    Quantity: 25 (1 lot NIFTY futures equivalent)
    Note: NIFTYBEES ≈ NIFTY/80; PnL scaled by 80 to match NIFTY futures exposure.
    """
    print("  Downloading NIFTYBEES.NS 5-min (proxy for NIFTY — ^NSEI has zero volume) …")
    try:
        df = fetch("NIFTYBEES.NS", interval="5m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    # Add indicators
    df["vwap"]     = intraday_vwap(df)
    df["vwap_dev"] = (df["close"] - df["vwap"]) / df["vwap"]
    df["atr14"]    = atr(df)
    df["vol_mean"] = df["volume"].rolling(20).mean()
    df["vol_std"]  = df["volume"].rolling(20).std()
    df["poc20"]    = poc(df, lookback=20)

    # NIFTYBEES ≈ NIFTY/80. To match 1 NIFTY lot (25 qty) exposure, we trade
    # 25 × 80 = 2000 NIFTYBEES units. PnL per point = same as NIFTY futures.
    QTY        = 2000    # ≈ 25 NIFTY lots equivalent in NIFTYBEES
    ATR_SL     = 3.0     # trailing stop multiplier
    CAPITAL    = 500_000

    trades      = []
    position    = None   # dict: {entry, stop, side}
    trailing_stop = 0.0

    for i in range(50, len(df)):
        bar = df.iloc[i]
        if pd.isna(bar["vwap"]) or pd.isna(bar["atr14"]) or pd.isna(bar["poc20"]):
            continue

        vol_threshold = bar["vol_mean"] + 1.5 * bar["vol_std"]

        if position is not None:
            # Update trailing stop
            new_stop = bar["close"] - ATR_SL * bar["atr14"]
            if new_stop > trailing_stop:
                trailing_stop = new_stop
            # Exit conditions
            exit_now = (
                bar["close"] < trailing_stop or   # trailing stop hit
                bar["close"] < bar["vwap"]         # crossed below VWAP
            )
            if exit_now:
                pnl = (bar["close"] - position["entry"]) * QTY
                trades.append({"pnl": pnl, "entry": position["entry"], "exit": bar["close"]})
                position = None
                trailing_stop = 0.0
        else:
            # Entry conditions
            is_above_vwap  = bar["close"] > bar["vwap"]
            is_vol_spike   = (not pd.isna(bar["vol_mean"])) and bar["volume"] > vol_threshold
            is_above_poc   = bar["close"] > bar["poc20"]
            is_not_extreme = abs(bar["vwap_dev"]) < 0.03

            if is_above_vwap and is_vol_spike and is_above_poc and is_not_extreme:
                position      = {"entry": bar["close"]}
                trailing_stop = bar["close"] - ATR_SL * bar["atr14"]

    # Close open position at last bar
    if position is not None:
        last = df.iloc[-1]
        pnl  = (last["close"] - position["entry"]) * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 5m"
    m["run_date"] = TODAY
    m["symbol"]   = "NIFTY (^NSEI)"
    return m


# ─── STRATEGY 2: AI_Hybrid_RELIANCE ─────────────────────────────────────────

def backtest_ai_hybrid_reliance(days: int = 58) -> dict:
    """
    Mean-reversion + breakout on RELIANCE 5-min bars.
    Symbol: RELIANCE.NS
    Entry (reversion): RSI<30 AND close<lower_BB AND volume>1.2×avg
    Entry (breakout):  RSI>60 AND close>upper_BB AND volume>2×avg AND close>SMA200
    Exit: 1% SL OR close>SMA20 (reversion) / 1% SL (breakout)
    """
    print("  Downloading RELIANCE.NS 5-min …")
    try:
        df = fetch("RELIANCE.NS", interval="5m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    df["rsi14"]   = rsi(df["close"])
    df["sma20"]   = df["close"].rolling(20).mean()
    df["sma200"]  = df["close"].rolling(200).mean()
    df["ub"], df["lb"] = bollinger(df["close"])[1], bollinger(df["close"])[2]
    df["vol_avg"] = df["volume"].rolling(20).mean()

    QTY     = 268    # from active_strategies.json params
    SL_PCT  = 0.01   # 1%
    CAPITAL = 150_000

    trades   = []
    position = None  # dict: {entry, side, stop, target_type}

    for i in range(210, len(df)):  # wait for SMA200 warmup
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        if pd.isna(bar["rsi14"]) or pd.isna(bar["sma20"]) or pd.isna(bar["vol_avg"]):
            continue

        if position is not None:
            close = bar["close"]
            entry = position["entry"]
            side  = position["side"]
            stop  = position["stop"]

            if side == "BUY":
                sl_hit = close < stop
                tp_hit = (position["target_type"] == "REVERSION") and (close > bar["sma20"])
                if sl_hit or tp_hit:
                    pnl = (close - entry) * QTY
                    trades.append({"pnl": pnl, "entry": entry, "exit": close,
                                   "type": position["target_type"]})
                    position = None
        else:
            vol_ok  = bar["volume"] > bar["vol_avg"] * 1.2
            vol_ok2 = bar["volume"] > bar["vol_avg"] * 2.0
            regime  = not pd.isna(bar["sma200"]) and bar["close"] > bar["sma200"]

            # Reversion: oversold
            if bar["rsi14"] < 30 and bar["close"] < bar["lb"] and vol_ok:
                stop = bar["close"] * (1 - SL_PCT)
                position = {"entry": bar["close"], "side": "BUY",
                            "stop": stop, "target_type": "REVERSION"}

            # Breakout: overbought + above SMA200
            elif bar["rsi14"] > 60 and bar["close"] > bar["ub"] and vol_ok2 and regime:
                stop = bar["close"] * (1 - SL_PCT)
                position = {"entry": bar["close"], "side": "BUY",
                            "stop": stop, "target_type": "BREAKOUT"}

    if position is not None:
        last = df.iloc[-1]
        pnl  = (last["close"] - position["entry"]) * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"],
                       "type": position["target_type"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 5m"
    m["run_date"] = TODAY
    m["symbol"]   = "RELIANCE.NS"
    return m


# ─── STRATEGY 3: MCX_SILVER ──────────────────────────────────────────────────

def backtest_mcx_silver(days: int = 58) -> dict:
    """
    ADX momentum on Silver 15-min bars.
    Symbol: SILVER.NS (NSE Silver ETF — MCX Silver proxy; yfinance has no direct MCX data)
    Price: ~₹175/unit. 1 MCX Silver lot = 30 kg. Backtest uses 30 units as lot equivalent.
    Entry BUY: ADX>25 AND RSI>55 AND close>prev_close
    Entry SELL: ADX>25 AND RSI<45 AND close<prev_close
    Exit: RSI reverts OR ADX<20
    """
    ticker = "SILVER.NS"
    print(f"  Downloading {ticker} 15-min (NSE Silver ETF proxy for MCX Silver) …")
    try:
        df = fetch(ticker, interval="15m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        df = pd.DataFrame()

    if df.empty:
        print("  ERROR: Could not fetch Silver data")
        return {}

    df["rsi14"] = rsi(df["close"])
    df["atr14"] = atr(df)
    df["adx14"] = adx(df)

    QTY     = 1        # 1 lot
    LOT_SZ  = 30       # SILVER.NS ETF: 30 units ≈ 1 MCX Silver lot (signal quality proxy)
    CAPITAL = 100_000  # margin approx

    trades   = []
    position = None  # {entry, side}

    ADX_ENTRY = 25
    ADX_EXIT  = 20

    for i in range(30, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        if pd.isna(bar["rsi14"]) or pd.isna(bar["adx14"]):
            continue

        if position is not None:
            side  = position["side"]
            close = bar["close"]
            entry = position["entry"]

            if side == "BUY":
                exit_now = bar["rsi14"] < 45 or bar["adx14"] < ADX_EXIT
            else:
                exit_now = bar["rsi14"] > 55 or bar["adx14"] < ADX_EXIT

            if exit_now:
                mul = 1 if side == "BUY" else -1
                pnl = mul * (close - entry) * LOT_SZ * QTY
                trades.append({"pnl": pnl, "entry": entry, "exit": close, "side": side})
                position = None
        else:
            strong = bar["adx14"] > ADX_ENTRY

            if strong and bar["rsi14"] > 55 and bar["close"] > prev["close"]:
                position = {"entry": bar["close"], "side": "BUY"}
            elif strong and bar["rsi14"] < 45 and bar["close"] < prev["close"]:
                position = {"entry": bar["close"], "side": "SELL"}

    if position is not None:
        last = df.iloc[-1]
        mul  = 1 if position["side"] == "BUY" else -1
        pnl  = mul * (last["close"] - position["entry"]) * LOT_SZ * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"],
                       "side": position["side"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 15m"
    m["run_date"] = TODAY
    m["symbol"]   = ticker
    return m


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    results = {}

    print("\n[1/3] SuperTrend_NIFTY (^NSEI 5m)")
    r1 = backtest_supertrend_nifty(days=58)
    results["SuperTrend_NIFTY"] = r1
    if r1:
        print(f"      PF={r1['pf']:.2f}  WR={r1['wr_pct']:.1f}%  "
              f"DD={r1['dd_pct']:.2f}%  Trades={r1['trades']}  "
              f"NetPnL=₹{r1['net_pnl']:,.0f}")

    print("\n[2/3] AI_Hybrid_RELIANCE (RELIANCE.NS 5m)")
    r2 = backtest_ai_hybrid_reliance(days=58)
    results["AI_Hybrid_RELIANCE"] = r2
    if r2:
        print(f"      PF={r2['pf']:.2f}  WR={r2['wr_pct']:.1f}%  "
              f"DD={r2['dd_pct']:.2f}%  Trades={r2['trades']}  "
              f"NetPnL=₹{r2['net_pnl']:,.0f}")

    print("\n[3/3] MCX_SILVER (SILVER.NS proxy 15m)")
    r3 = backtest_mcx_silver(days=58)
    results["MCX_SILVER"] = r3
    if r3:
        print(f"      PF={r3['pf']:.2f}  WR={r3['wr_pct']:.1f}%  "
              f"DD={r3['dd_pct']:.2f}%  Trades={r3['trades']}  "
              f"NetPnL=₹{r3['net_pnl']:,.0f}")

    print("\n" + "="*60)
    print("SUMMARY — to paste into active_strategies.json:")
    print("="*60)
    for name, r in results.items():
        if r and r.get("trades", 0) > 0:
            backtest_entry = {
                "pf":      r["pf"],
                "dd_pct":  r["dd_pct"],
                "wr_pct":  r["wr_pct"],
                "trades":  r["trades"],
                "window":  r["window"],
                "run_date": r["run_date"],
            }
            print(f'\n"{name}" backtest:')
            print(json.dumps(backtest_entry, indent=4))
        else:
            print(f'\n"{name}": No trades generated — strategy may need calibration on this data')

    # Save full results
    out = "/Users/mac/sksoopenalgo/openalgo/equity_backtest_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {out}")


if __name__ == "__main__":
    main()
