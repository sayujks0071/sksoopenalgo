#!/usr/bin/env python3
"""
Extended backtests — v2 improvements + new MCX instruments.

Strategies tested:
  1. SuperTrend_NIFTY_v2  — NIFTYBEES.NS 5m  (adds ADX + EMA50 + RSI filters vs v1)
  2. MCX_GOLD             — GOLDBEES.NS 15m   (EMA crossover + RSI momentum)
  3. MCX_CRUDEOIL         — BZ=F (Brent) 15m  (ADX trend-follow; MCX CrudeOil proxy)

Run: python run_extended_backtests.py
"""
import json
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


def adx_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
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


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, min_periods=period).mean()


def intraday_vwap(df: pd.DataFrame) -> pd.Series:
    """Reset VWAP each calendar day."""
    typ = (df["high"] + df["low"] + df["close"]) / 3
    df2 = df.copy()
    df2["_typ"]  = typ
    df2["_date"] = df.index.date
    df2["_cum_tv"] = df2.groupby("_date").apply(
        lambda g: (g["_typ"] * g["volume"]).cumsum(), include_groups=False
    ).droplevel(0)
    df2["_cum_v"] = df2.groupby("_date")["volume"].cumsum()
    return df2["_cum_tv"] / df2["_cum_v"].replace(0, np.nan)


def poc_series(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    result = pd.Series(np.nan, index=df.index)
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback : i]
        result.iloc[i] = window.loc[window["volume"].idxmax(), "close"]
    return result


# ─── METRICS ─────────────────────────────────────────────────────────────────

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


# ─── DATA FETCH ──────────────────────────────────────────────────────────────

def fetch(ticker: str, interval: str = "5m", days: int = 58) -> pd.DataFrame:
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
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)
    return df


# ─── STRATEGY 1: SuperTrend_NIFTY_v2 ─────────────────────────────────────────
#  Adds vs v1:
#    • ADX > 22 filter  (require trending market)
#    • EMA50 trend filter  (only long when close > EMA50)
#    • RSI 50-70 filter  (only enter with momentum confirmation)
#    • Tighter vol spike threshold: mean + 2.0×std (was 1.5)
#
#  v1 PF=0.81, WR=26.7%, 45 trades → expected: fewer but cleaner trades.

def backtest_supertrend_nifty_v2(days: int = 58) -> dict:
    """
    VWAP momentum on NIFTYBEES.NS 5-min bars.
    v2: ADX + EMA50 + RSI momentum filters added.
    """
    print("  Downloading NIFTYBEES.NS 5-min …")
    try:
        df = fetch("NIFTYBEES.NS", interval="5m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    df["vwap"]     = intraday_vwap(df)
    df["vwap_dev"] = (df["close"] - df["vwap"]) / df["vwap"]
    df["atr14"]    = atr(df)
    df["adx14"]    = adx_series(df)
    df["ema50"]    = ema(df["close"], 50)
    df["rsi14"]    = rsi(df["close"])
    df["vol_mean"] = df["volume"].rolling(20).mean()
    df["vol_std"]  = df["volume"].rolling(20).std()
    df["poc20"]    = poc_series(df, lookback=20)

    QTY     = 2000     # ≈ 25 NIFTY lot-equivalent in NIFTYBEES units
    ATR_SL  = 3.0
    CAPITAL = 500_000

    trades        = []
    position      = None
    trailing_stop = 0.0

    for i in range(55, len(df)):
        bar = df.iloc[i]
        if pd.isna(bar["vwap"]) or pd.isna(bar["atr14"]) or pd.isna(bar["poc20"]):
            continue
        if pd.isna(bar["adx14"]) or pd.isna(bar["ema50"]) or pd.isna(bar["rsi14"]):
            continue

        vol_threshold = bar["vol_mean"] + 2.0 * bar["vol_std"]  # tighter vs v1 (1.5)

        if position is not None:
            new_stop = bar["close"] - ATR_SL * bar["atr14"]
            if new_stop > trailing_stop:
                trailing_stop = new_stop
            exit_now = (
                bar["close"] < trailing_stop or
                bar["close"] < bar["vwap"]
            )
            if exit_now:
                pnl = (bar["close"] - position["entry"]) * QTY
                trades.append({"pnl": pnl, "entry": position["entry"], "exit": bar["close"]})
                position      = None
                trailing_stop = 0.0
        else:
            is_above_vwap    = bar["close"] > bar["vwap"]
            is_vol_spike     = (not pd.isna(bar["vol_mean"])) and bar["volume"] > vol_threshold
            is_above_poc     = bar["close"] > bar["poc20"]
            is_not_extreme   = abs(bar["vwap_dev"]) < 0.025   # tighter (was 0.03)
            is_trending      = bar["adx14"] > 22              # NEW: ADX filter
            is_uptrend       = bar["close"] > bar["ema50"]     # NEW: EMA50 trend
            is_rsi_momentum  = 52 < bar["rsi14"] < 72         # NEW: RSI momentum band

            if (is_above_vwap and is_vol_spike and is_above_poc and is_not_extreme
                    and is_trending and is_uptrend and is_rsi_momentum):
                position      = {"entry": bar["close"]}
                trailing_stop = bar["close"] - ATR_SL * bar["atr14"]

    if position is not None:
        last = df.iloc[-1]
        pnl  = (last["close"] - position["entry"]) * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 5m"
    m["run_date"] = TODAY
    m["symbol"]   = "NIFTY (NIFTYBEES.NS)"
    return m


# ─── STRATEGY 2: MCX_GOLD ─────────────────────────────────────────────────────
#  EMA-crossover (9/21) + RSI momentum on GOLDBEES.NS 15-min bars.
#  MCX Gold mini lot = 100g; GOLDBEES.NS ≈ 1g/unit ⟹ 100 units ~ 1 mini lot.
#  Both sides: BUY and SELL.

def backtest_mcx_gold(days: int = 58) -> dict:
    """
    EMA crossover + RSI momentum on GOLDBEES.NS 15-min (MCX Gold proxy).
    Entry BUY:  EMA9 > EMA21 AND RSI > 55 AND close > prev_close
    Entry SELL: EMA9 < EMA21 AND RSI < 45 AND close < prev_close
    Exit: EMA crossover reverses OR RSI reverts past 50
    """
    print("  Downloading GOLDBEES.NS 15-min (MCX Gold proxy) …")
    try:
        df = fetch("GOLDBEES.NS", interval="15m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    df["ema9"]  = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["rsi14"] = rsi(df["close"])
    df["atr14"] = atr(df)
    df["adx14"] = adx_series(df)

    QTY     = 1
    LOT_SZ  = 100     # 100 GOLDBEES units ≈ 1 MCX Gold Mini lot (100g)
    CAPITAL = 100_000

    trades   = []
    position = None

    for i in range(30, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        if pd.isna(bar["rsi14"]) or pd.isna(bar["ema9"]) or pd.isna(bar["ema21"]):
            continue

        if position is not None:
            side  = position["side"]
            close = bar["close"]
            entry = position["entry"]

            if side == "BUY":
                # Exit: EMA cross reverses or RSI drops below 40
                exit_now = (bar["ema9"] < bar["ema21"]) or (bar["rsi14"] < 40)
            else:
                exit_now = (bar["ema9"] > bar["ema21"]) or (bar["rsi14"] > 60)

            if exit_now:
                mul = 1 if side == "BUY" else -1
                pnl = mul * (close - entry) * LOT_SZ * QTY
                trades.append({"pnl": pnl, "entry": entry, "exit": close, "side": side})
                position = None
        else:
            adx_ok  = not pd.isna(bar["adx14"]) and bar["adx14"] > 20

            # BUY signal
            if (bar["ema9"] > bar["ema21"] and bar["rsi14"] > 55
                    and bar["close"] > prev["close"] and adx_ok):
                position = {"entry": bar["close"], "side": "BUY"}

            # SELL signal
            elif (bar["ema9"] < bar["ema21"] and bar["rsi14"] < 45
                    and bar["close"] < prev["close"] and adx_ok):
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
    m["symbol"]   = "GOLDBEES.NS"
    return m


# ─── STRATEGY 3: MCX_CRUDEOIL ─────────────────────────────────────────────────
#  ADX trend-following on Brent crude (BZ=F) 15-min bars.
#  MCX CrudeOil mini lot = 10 bbl. BZ=F is in USD; use 1 unit as signal proxy.
#  Both sides: BUY (momentum) and SELL (momentum reversal).

def backtest_mcx_crudeoil(days: int = 58) -> dict:
    """
    ADX trend-follow on BZ=F (Brent Crude) 15-min bars.
    Entry BUY:  ADX > 25 AND RSI > 55 AND EMA9 > EMA21
    Entry SELL: ADX > 25 AND RSI < 45 AND EMA9 < EMA21
    Exit: ADX < 20 OR RSI reverts past 50
    """
    print("  Downloading BZ=F (Brent Crude) 15-min (MCX CrudeOil proxy) …")
    try:
        df = fetch("BZ=F", interval="15m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    df["rsi14"] = rsi(df["close"])
    df["atr14"] = atr(df)
    df["adx14"] = adx_series(df)
    df["ema9"]  = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)

    # MCX CrudeOil: price ~₹6,000/bbl; 1 mini lot = 10 bbl → ₹60,000
    # BZ=F is in USD. For signal quality backtest, we use INR scaling:
    # 1 BZ=F point ≈ ₹85 (USD/INR rate). 10 bbl lot → ₹850 per $1 move.
    QTY      = 1
    LOT_VAL  = 850     # ₹ per $1 move in BZ=F for 1 MCX mini lot
    CAPITAL  = 100_000

    trades   = []
    position = None

    ADX_ENTRY = 25
    ADX_EXIT  = 20

    for i in range(30, len(df)):
        bar  = df.iloc[i]
        prev = df.iloc[i - 1]
        if pd.isna(bar["rsi14"]) or pd.isna(bar["adx14"]) or pd.isna(bar["ema9"]):
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
                pnl = mul * (close - entry) * LOT_VAL * QTY
                trades.append({"pnl": pnl, "entry": entry, "exit": close, "side": side})
                position = None
        else:
            strong   = bar["adx14"] > ADX_ENTRY
            ema_bull = bar["ema9"] > bar["ema21"]
            ema_bear = bar["ema9"] < bar["ema21"]

            if strong and bar["rsi14"] > 55 and bar["close"] > prev["close"] and ema_bull:
                position = {"entry": bar["close"], "side": "BUY"}
            elif strong and bar["rsi14"] < 45 and bar["close"] < prev["close"] and ema_bear:
                position = {"entry": bar["close"], "side": "SELL"}

    if position is not None:
        last = df.iloc[-1]
        mul  = 1 if position["side"] == "BUY" else -1
        pnl  = mul * (last["close"] - position["entry"]) * LOT_VAL * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"],
                       "side": position["side"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 15m"
    m["run_date"] = TODAY
    m["symbol"]   = "BZ=F (Brent proxy)"
    return m


# ─── BONUS: SuperTrend_BANKNIFTY ─────────────────────────────────────────────
#  If NIFTY v2 improves, also test BankNIFTY as NIFTY replacement candidate.
#  BANKBEES.NS = BankNIFTY ETF proxy (lot = 15).

def backtest_banknifty_vwap(days: int = 58) -> dict:
    """
    VWAP volume-spike on BANKBEES.NS 5-min (BankNIFTY proxy).
    Same v2 logic as SuperTrend_NIFTY_v2.
    """
    print("  Downloading BANKBEES.NS 5-min (BankNIFTY ETF proxy) …")
    try:
        df = fetch("BANKBEES.NS", interval="5m", days=days)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

    df["vwap"]     = intraday_vwap(df)
    df["vwap_dev"] = (df["close"] - df["vwap"]) / df["vwap"]
    df["atr14"]    = atr(df)
    df["adx14"]    = adx_series(df)
    df["ema50"]    = ema(df["close"], 50)
    df["rsi14"]    = rsi(df["close"])
    df["vol_mean"] = df["volume"].rolling(20).mean()
    df["vol_std"]  = df["volume"].rolling(20).std()
    df["poc20"]    = poc_series(df, lookback=20)

    # BANKBEES ≈ BANKNIFTY/100; 1 BankNIFTY lot = 15 contracts
    # 15 × 100 = 1500 BANKBEES units as lot equivalent
    QTY     = 1500
    ATR_SL  = 3.0
    CAPITAL = 500_000

    trades        = []
    position      = None
    trailing_stop = 0.0

    for i in range(55, len(df)):
        bar = df.iloc[i]
        if any(pd.isna(bar[col]) for col in ["vwap","atr14","poc20","adx14","ema50","rsi14"]):
            continue

        vol_threshold = bar["vol_mean"] + 2.0 * bar["vol_std"]

        if position is not None:
            new_stop = bar["close"] - ATR_SL * bar["atr14"]
            if new_stop > trailing_stop:
                trailing_stop = new_stop
            if bar["close"] < trailing_stop or bar["close"] < bar["vwap"]:
                pnl = (bar["close"] - position["entry"]) * QTY
                trades.append({"pnl": pnl, "entry": position["entry"], "exit": bar["close"]})
                position      = None
                trailing_stop = 0.0
        else:
            if (bar["close"] > bar["vwap"]
                    and bar["volume"] > vol_threshold
                    and bar["close"] > bar["poc20"]
                    and abs(bar["vwap_dev"]) < 0.025
                    and bar["adx14"] > 22
                    and bar["close"] > bar["ema50"]
                    and 52 < bar["rsi14"] < 72):
                position      = {"entry": bar["close"]}
                trailing_stop = bar["close"] - ATR_SL * bar["atr14"]

    if position is not None:
        last = df.iloc[-1]
        pnl  = (last["close"] - position["entry"]) * QTY
        trades.append({"pnl": pnl, "entry": position["entry"], "exit": last["close"]})

    m = trade_metrics(trades, CAPITAL)
    m["window"]   = f"{days}d 5m"
    m["run_date"] = TODAY
    m["symbol"]   = "BANKNIFTY (BANKBEES.NS)"
    return m


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    results = {}

    print("\n" + "="*60)
    print("EXTENDED BACKTESTS — " + TODAY)
    print("="*60)

    print("\n[1/4] SuperTrend_NIFTY_v2 (NIFTYBEES.NS 5m + ADX/EMA50/RSI filters)")
    r1 = backtest_supertrend_nifty_v2(days=58)
    results["SuperTrend_NIFTY_v2"] = r1
    if r1 and r1.get("trades", 0) > 0:
        print(f"      PF={r1['pf']:.2f}  WR={r1['wr_pct']:.1f}%  "
              f"DD={r1['dd_pct']:.2f}%  Trades={r1['trades']}  NetPnL=₹{r1['net_pnl']:,.0f}")
    else:
        print("      No trades generated")

    print("\n[2/4] BankNIFTY_VWAP_v2 (BANKBEES.NS 5m — alternative to NIFTY)")
    r2 = backtest_banknifty_vwap(days=58)
    results["BankNIFTY_VWAP_v2"] = r2
    if r2 and r2.get("trades", 0) > 0:
        print(f"      PF={r2['pf']:.2f}  WR={r2['wr_pct']:.1f}%  "
              f"DD={r2['dd_pct']:.2f}%  Trades={r2['trades']}  NetPnL=₹{r2['net_pnl']:,.0f}")
    else:
        print("      No trades generated")

    print("\n[3/4] MCX_GOLD (GOLDBEES.NS 15m — EMA crossover + RSI)")
    r3 = backtest_mcx_gold(days=58)
    results["MCX_GOLD"] = r3
    if r3 and r3.get("trades", 0) > 0:
        print(f"      PF={r3['pf']:.2f}  WR={r3['wr_pct']:.1f}%  "
              f"DD={r3['dd_pct']:.2f}%  Trades={r3['trades']}  NetPnL=₹{r3['net_pnl']:,.0f}")
    else:
        print("      No trades generated")

    print("\n[4/4] MCX_CRUDEOIL (BZ=F 15m — ADX trend-follow)")
    r4 = backtest_mcx_crudeoil(days=58)
    results["MCX_CRUDEOIL"] = r4
    if r4 and r4.get("trades", 0) > 0:
        print(f"      PF={r4['pf']:.2f}  WR={r4['wr_pct']:.1f}%  "
              f"DD={r4['dd_pct']:.2f}%  Trades={r4['trades']}  NetPnL=₹{r4['net_pnl']:,.0f}")
    else:
        print("      No trades generated")

    # ─── SUMMARY ─────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, r in results.items():
        if r and r.get("trades", 0) > 0:
            status = "✅ DEPLOY" if r["pf"] >= 1.5 and r["dd_pct"] < 10 else (
                     "⚠️  REVIEW" if r["pf"] >= 1.0 else "❌ PAUSE")
            print(f"  {name:30s} PF={r['pf']:.2f}  WR={r['wr_pct']:.1f}%  "
                  f"DD={r['dd_pct']:.2f}%  Trades={r['trades']}  {status}")
        else:
            print(f"  {name:30s} — No trades")

    # ─── JSON SAVE ───────────────────────────────────────────────────────────
    out = "/Users/mac/sksoopenalgo/openalgo/extended_backtest_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved → {out}")

    # ─── PASTE-READY ─────────────────────────────────────────────────────────
    print("\n--- active_strategies.json entries (copy-paste) ---")
    for name, r in results.items():
        if r and r.get("trades", 0) > 0:
            entry = {k: r[k] for k in ("pf","dd_pct","wr_pct","trades","window","run_date")}
            print(f'\n"{name}":')
            print(json.dumps(entry, indent=4))


if __name__ == "__main__":
    main()
