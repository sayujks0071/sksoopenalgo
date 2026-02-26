#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import vectorbt as vbt
from dotenv import load_dotenv


@dataclass
class BacktestResult:
    symbol: str
    exchange: str
    interval: str
    fast_ema: int
    slow_ema: int
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    trades: int
    net_profit: float
    rejected: bool
    reject_reason: str


def _history(
    host: str,
    api_key: str,
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    url = f"{host.rstrip('/')}/api/v1/history"
    payload = {
        "apikey": api_key,
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "start_date": start_date,
        "end_date": end_date,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"history failed for {symbol}: {data}")
    rows = data.get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    else:
        df["datetime"] = pd.to_datetime(df.index, errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").set_index("datetime")
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"])


def _resolve_symbol(host: str, api_key: str, query: str, exchange: str) -> str:
    url = f"{host.rstrip('/')}/api/v1/search"
    payload = {"apikey": api_key, "query": query, "exchange": exchange}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code != 200:
            return query
        data = resp.json()
        rows = data.get("data", [])
        if not rows:
            return query
        # Prefer exact, else first.
        for row in rows:
            if str(row.get("symbol", "")).upper() == query.upper():
                return str(row.get("symbol"))
        return str(rows[0].get("symbol") or query)
    except Exception:
        return query


def _run_one(
    df: pd.DataFrame,
    fast_ema: int,
    slow_ema: int,
    init_cash: float,
    fees: float,
    freq: str,
) -> dict[str, Any]:
    close = df["close"]
    fast = vbt.MA.run(close, fast_ema, ewm=True)
    slow = vbt.MA.run(close, slow_ema, ewm=True)
    entries = fast.ma_crossed_above(slow)
    exits = fast.ma_crossed_below(slow)

    pf = vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        direction="longonly",
        init_cash=init_cash,
        fees=fees,
        size=1.0,
        size_type="percent",
        freq=freq,
    )
    total_return = float(pf.total_return())
    max_dd = float(pf.max_drawdown())
    sharpe = float(pf.sharpe_ratio()) if np.isfinite(float(pf.sharpe_ratio())) else 0.0
    trades = int(pf.trades.count())
    net_profit = float(init_cash * total_return)
    return {
        "total_return_pct": total_return * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "trades": trades,
        "net_profit": net_profit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VectorBT multi-symbol backtest for OpenAlgo.")
    parser.add_argument("--host", default="http://127.0.0.1:5002")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--intervals", default="")
    parser.add_argument("--init-cash", type=float, default=100000.0)
    parser.add_argument("--fees", type=float, default=0.0011)
    parser.add_argument("--max-loss", type=float, default=10000.0)
    parser.add_argument("--target-profit", type=float, default=50000.0)
    parser.add_argument("--out", default="/Users/mac/openalgo/log/vectorbt_backtest_report.json")
    args = parser.parse_args()

    load_dotenv("/Users/mac/openalgo/openalgo/.env", override=False)
    api_key = args.api_key or os.getenv("OPENALGO_API_KEY") or os.getenv("OPENALGO_APIKEY")
    if not api_key:
        raise SystemExit("Missing API key: set OPENALGO_API_KEY or pass --api-key")

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    universe = [
        ("CRUDEOIL", "MCX"),
        ("GOLD", "MCX"),
        ("SILVER", "MCX"),
        ("NATURALGAS", "MCX"),
        ("NIFTY", "NSE_INDEX"),
        ("BANKNIFTY", "NSE_INDEX"),
        ("RELIANCE", "NSE"),
        ("SBIN", "NSE"),
        ("HDFCBANK", "NSE"),
        ("ICICIBANK", "NSE"),
    ]
    ema_grid = [(8, 21), (10, 20), (12, 26), (14, 30)]
    freq_map = {
        "1m": "1min",
        "3m": "3min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "1h",
        "1h": "1h",
        "D": "1D",
        "1d": "1D",
    }
    interval_list = [x.strip() for x in (args.intervals or "").split(",") if x.strip()] or [args.interval]
    all_results: list[BacktestResult] = []

    for interval in interval_list:
        bt_freq = freq_map.get(interval, "15min")
        for symbol, exchange in universe:
            resolved = _resolve_symbol(args.host, api_key, symbol, exchange)
            try:
                df = _history(args.host, api_key, resolved, exchange, interval, start_date, end_date)
            except Exception:
                # Retry with raw symbol in case resolver picked incompatible contract.
                try:
                    df = _history(args.host, api_key, symbol, exchange, interval, start_date, end_date)
                except Exception as exc:
                    all_results.append(
                        BacktestResult(
                            symbol=symbol,
                            exchange=exchange,
                            interval=interval,
                            fast_ema=0,
                            slow_ema=0,
                            total_return_pct=0.0,
                            max_drawdown_pct=0.0,
                            sharpe=0.0,
                            trades=0,
                            net_profit=0.0,
                            rejected=True,
                            reject_reason=f"history_error:{type(exc).__name__}",
                        )
                    )
                    continue
            if df.empty or len(df) < 80:
                all_results.append(
                    BacktestResult(
                        symbol=symbol,
                        exchange=exchange,
                        interval=interval,
                        fast_ema=0,
                        slow_ema=0,
                        total_return_pct=0.0,
                        max_drawdown_pct=0.0,
                        sharpe=0.0,
                        trades=0,
                        net_profit=0.0,
                        rejected=True,
                        reject_reason="insufficient_data",
                    )
                )
                continue

            best: BacktestResult | None = None
            for fast, slow in ema_grid:
                if fast >= slow:
                    continue
                metrics = _run_one(df, fast, slow, args.init_cash, args.fees, bt_freq)
                max_dd_abs_pct = abs(float(metrics["max_drawdown_pct"]))
                rejected = max_dd_abs_pct > (args.max_loss / args.init_cash) * 100.0
                row = BacktestResult(
                    symbol=symbol,
                    exchange=exchange,
                    interval=interval,
                    fast_ema=fast,
                    slow_ema=slow,
                    total_return_pct=metrics["total_return_pct"],
                    max_drawdown_pct=max_dd_abs_pct,
                    sharpe=metrics["sharpe"],
                    trades=metrics["trades"],
                    net_profit=metrics["net_profit"],
                    rejected=rejected,
                    reject_reason="max_loss_breach" if rejected else "",
                )
                if best is None:
                    best = row
                else:
                    if row.rejected != best.rejected:
                        if not row.rejected:
                            best = row
                    elif row.net_profit > best.net_profit:
                        best = row
            if best:
                all_results.append(best)

    ranked = sorted(all_results, key=lambda x: (x.rejected, -x.net_profit))
    selected = []
    used_symbols = set()
    for row in ranked:
        if row.rejected:
            continue
        if row.symbol in used_symbols:
            continue
        selected.append(row)
        used_symbols.add(row.symbol)
        if len(selected) >= 3:
            break
    projected = float(sum(r.net_profit for r in selected))

    report = {
        "generated_at": datetime.now().isoformat(),
        "host": args.host,
        "interval": args.interval,
        "start_date": start_date,
        "end_date": end_date,
        "target_profit": args.target_profit,
        "max_loss": args.max_loss,
        "init_cash_per_strategy": args.init_cash,
        "top_selected": [asdict(x) for x in selected],
        "projected_profit_top3": projected,
        "all_results": [asdict(x) for x in ranked],
        "note": (
            "Backtest is historical and does not guarantee tomorrow profit. "
            "Loss cap in live trading remains enforced by runtime risk config."
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "report": str(out), "projected_profit_top3": projected}, indent=2))


if __name__ == "__main__":
    main()
