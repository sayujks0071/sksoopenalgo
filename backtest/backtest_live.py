#!/usr/bin/env python3
"""
Backtest Runner — NIFTY / BANKNIFTY Historical Backtest
=======================================================
Uses yfinance to fetch 6 months of 5-minute data and runs
the FIXED Alpha Genius strategy against it.

Usage:
    python backtest_live.py
    python backtest_live.py --segment BANKNIFTY --period 6mo

Requirements:
    pip install yfinance pandas numpy
"""

import sys
import json
import argparse
import logging
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

sys.path.insert(0, "..")
sys.path.insert(0, "../strategies")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("Backtest")


def fetch_historical_data(symbol: str, period: str = "6mo", interval: str = "5m") -> pd.DataFrame:
    """Fetch data from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("Installing yfinance...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
        import yfinance as yf

    ticker_map = {
        "BANKNIFTY": "^NSEBANK",
        "NIFTY":     "^NSEI",
        "NIFTY50":   "^NSEI",
        "FINNIFTY":  "NIFTY_FIN_SERVICE.NS",
        "CRUDEOIL":  "CL=F",
        "GOLD":      "GC=F",
    }
    ticker = ticker_map.get(symbol.upper(), symbol)
    print(f"Fetching {symbol} ({ticker}) | Period: {period} | Interval: {interval}")

    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df is None or df.empty:
        print(f"No data for {symbol}")
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index)

    if df.index.tz is not None:
        import pytz
        ist = pytz.timezone("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)

    print(f"Got {len(df)} bars for {symbol}")
    return df


def run_backtest_for_segment(
    segment: str,
    period: str = "6mo",
    interval: str = "5m",
    initial_capital: float = 500000,
    lot_size: int = None,
) -> dict:
    default_lot_sizes = {
        "BANKNIFTY": 15,
        "NIFTY": 75,
        "NIFTY50": 75,
        "FINNIFTY": 40,
        "CRUDEOIL": 100,
        "GOLD": 1,
    }
    if lot_size is None:
        lot_size = default_lot_sizes.get(segment.upper(), 1)

    df = fetch_historical_data(segment, period, interval)
    if df.empty:
        return {"error": f"No data for {segment}", "segment": segment}

    try:
        from alpha_genius_strategy_FIXED import BacktestEngine
    except ImportError:
        try:
            sys.path.insert(0, "../strategies")
            from alpha_genius_strategy_FIXED import BacktestEngine
        except ImportError:
            print("Could not import BacktestEngine")
            return {"error": "Import failed"}

    engine = BacktestEngine(initial_capital=initial_capital)
    print(f"\nRunning backtest for {segment} with lot_size={lot_size}...")
    result = engine.run_backtest(df, chain_data=[], segment=segment, lot_size=lot_size)
    return result


def print_results(result: dict, segment: str):
    if "error" in result:
        print(f"\n{segment}: {result['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS: {segment}")
    print(f"{'='*60}")
    print(f"  Total Trades       : {result['total_trades']}")
    print(f"  Win Rate           : {result['win_rate_pct']}%")
    print(f"  Winning Trades     : {result['winning_trades']}")
    print(f"  Losing Trades      : {result['losing_trades']}")
    print(f"  Stop Loss Hits     : {result['sl_hits']}")
    print(f"  Target Hits        : {result['target_hits']}")
    print(f"  Gross P&L          : Rs.{result['total_gross_pnl']:,.2f}")
    print(f"  Total Charges      : Rs.{result['total_charges']:,.2f}")
    print(f"  Net P&L            : Rs.{result['total_net_pnl']:,.2f}")
    print(f"  Avg Winning Trade  : Rs.{result['avg_win']:,.2f}")
    print(f"  Avg Losing Trade   : Rs.{result['avg_loss']:,.2f}")
    print(f"  Profit Factor      : {result['profit_factor']}")
    print(f"  Sharpe Ratio       : {result['sharpe_ratio']}")
    print(f"  Max Drawdown       : Rs.{result['max_drawdown']:,.2f}")
    print(f"  Return/MaxDD       : {result['return_over_max_dd']:.2f}")
    print(f"  Initial Capital    : Rs.500,000")
    print(f"  Final Capital      : Rs.{result['final_capital']:,.2f}")
    print(f"  Return             : {result['return_pct']}%")
    print(f"{'='*60}")

    if result.get("trades"):
        trade_df = pd.DataFrame(result["trades"])
        if "adx" in trade_df.columns:
            print(f"\n  ADX Distribution:")
            print(f"    Mean ADX: {trade_df['adx'].mean():.1f}")
            print(f"    Min ADX:  {trade_df['adx'].min():.1f}")
            print(f"    Max ADX:  {trade_df['adx'].max():.1f}")


def main():
    parser = argparse.ArgumentParser(description="Backtest OpenAlgo Strategies")
    parser.add_argument("--segment", default="BANKNIFTY", help="BANKNIFTY, NIFTY, CRUDEOIL")
    parser.add_argument("--period", default="3mo", help="1mo, 3mo, 6mo, 1y")
    parser.add_argument("--interval", default="5m", help="1m, 5m, 15m")
    parser.add_argument("--capital", default=500000, type=float)
    parser.add_argument("--all", action="store_true", help="Run all segments")
    parser.add_argument("--output", help="Save results to JSON file")
    args = parser.parse_args()

    if args.all:
        segments = ["BANKNIFTY", "NIFTY"]
    else:
        segments = [args.segment]

    all_results = {}
    for seg in segments:
        result = run_backtest_for_segment(
            segment=seg,
            period=args.period,
            interval=args.interval,
            initial_capital=args.capital,
        )
        all_results[seg] = result
        print_results(result, seg)

    if args.output:
        clean_results = {}
        for seg, res in all_results.items():
            clean = {k: v for k, v in res.items() if k != "trades"}
            clean_results[seg] = clean
        with open(args.output, "w") as f:
            json.dump(clean_results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    return all_results


if __name__ == "__main__":
    main()
