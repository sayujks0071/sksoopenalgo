#!/usr/bin/env python3
"""Shared analytics helpers for OpenAlgo backtest scripts."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _side_multiplier(trade: dict[str, Any]) -> float:
    side = str(
        trade.get("side")
        or trade.get("direction")
        or trade.get("action")
        or "BUY"
    ).upper()
    return -1.0 if side in {"SELL", "SHORT"} else 1.0


def _trade_gross_pnl(trade: dict[str, Any]) -> float:
    if trade.get("gross_pnl") is not None:
        return _safe_float(trade.get("gross_pnl"))
    if trade.get("pnl") is not None:
        return _safe_float(trade.get("pnl"))

    entry = _safe_float(trade.get("entry"))
    exit_price = _safe_float(trade.get("exit"))
    qty = max(0.0, _safe_float(trade.get("qty"), 1.0))
    multiplier = max(0.0, _safe_float(trade.get("multiplier"), 1.0))
    return (exit_price - entry) * qty * multiplier * _side_multiplier(trade)


def _trade_cost(
    trade: dict[str, Any],
    *,
    slippage_bps_per_side: float,
    brokerage_per_order: float,
    tax_bps_per_side: float,
) -> float:
    entry = _safe_float(trade.get("entry"))
    exit_price = _safe_float(trade.get("exit"))
    qty = max(0.0, _safe_float(trade.get("qty"), 0.0))
    multiplier = max(0.0, _safe_float(trade.get("multiplier"), 1.0))

    if entry <= 0 or exit_price <= 0 or qty <= 0:
        return 0.0

    entry_notional = entry * qty * multiplier
    exit_notional = exit_price * qty * multiplier
    traded_notional = entry_notional + exit_notional

    slippage = traded_notional * max(0.0, slippage_bps_per_side) / 10000.0
    taxes = traded_notional * max(0.0, tax_bps_per_side) / 10000.0
    brokerage = max(0.0, brokerage_per_order) * 2.0
    return slippage + taxes + brokerage


def _extract_trade_day(trade: dict[str, Any]) -> str | None:
    for key in ("date", "day", "entry_day", "trade_day"):
        value = trade.get(key)
        if value:
            return str(value)[:10]
    for key in ("timestamp", "entry_time", "time"):
        value = trade.get(key)
        if value:
            return str(value)[:10]
    return None


def _robustness_score(
    *,
    profit_factor: float,
    sharpe_like: float,
    max_drawdown_pct: float,
    win_rate_pct: float,
    trades: int,
    expectancy: float,
) -> float:
    pf_score = min(max(profit_factor, 0.0), 3.0) / 3.0
    sharpe_score = min(max(sharpe_like, 0.0), 2.5) / 2.5
    dd_score = 1.0 - min(abs(max_drawdown_pct) / 25.0, 1.0)
    win_score = min(max(win_rate_pct, 0.0), 70.0) / 70.0
    depth_score = min(max(trades, 0), 60) / 60.0
    expectancy_score = 0.0 if expectancy <= 0 else 1.0
    return round(
        100.0
        * (
            0.25 * pf_score
            + 0.2 * sharpe_score
            + 0.2 * dd_score
            + 0.15 * win_score
            + 0.15 * depth_score
            + 0.05 * expectancy_score
        ),
        1,
    )


def summarize_trades(
    trades: list[dict[str, Any]],
    *,
    initial_capital: float,
    slippage_bps_per_side: float = 0.0,
    brokerage_per_order: float = 0.0,
    tax_bps_per_side: float = 0.0,
    metadata: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a consistent metrics payload for ad hoc backtest scripts."""

    result: dict[str, Any] = {
        "initial_capital": round(float(initial_capital), 2),
        "final_capital": round(float(initial_capital), 2),
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "costs": 0.0,
        "profit_factor": 0.0,
        "pf": 0.0,
        "win_rate_pct": 0.0,
        "wr_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "dd_pct": 0.0,
        "max_drawdown_abs": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "payoff_ratio": 0.0,
        "expectancy": 0.0,
        "sharpe_like": 0.0,
        "calmar_like": 0.0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "best_day": 0.0,
        "worst_day": 0.0,
        "trades": len(trades),
        "trade_density_per_day": 0.0,
        "robustness_score": 0.0,
        "cost_model": {
            "slippage_bps_per_side": float(slippage_bps_per_side),
            "brokerage_per_order": float(brokerage_per_order),
            "tax_bps_per_side": float(tax_bps_per_side),
        },
        "quality": quality or {},
    }

    if metadata:
        result.update(metadata)

    if not trades:
        return result

    normalized: list[dict[str, Any]] = []
    daily_pnl: defaultdict[str, float] = defaultdict(float)

    for trade in trades:
        gross_pnl = _trade_gross_pnl(trade)
        costs = _trade_cost(
            trade,
            slippage_bps_per_side=slippage_bps_per_side,
            brokerage_per_order=brokerage_per_order,
            tax_bps_per_side=tax_bps_per_side,
        )
        net_pnl = gross_pnl - costs
        day_key = _extract_trade_day(trade)
        if day_key:
            daily_pnl[day_key] += net_pnl
        normalized.append(
            {
                **trade,
                "gross_pnl": round(gross_pnl, 2),
                "costs": round(costs, 2),
                "pnl": round(net_pnl, 2),
            }
        )

    pnls = pd.Series([row["pnl"] for row in normalized], dtype="float64")
    gross_pnls = pd.Series([row["gross_pnl"] for row in normalized], dtype="float64")
    equity = pd.Series(float(initial_capital), index=pnls.index, dtype="float64") + pnls.cumsum()
    roll_max = equity.cummax()
    drawdown_abs = roll_max - equity
    max_drawdown_abs = float(drawdown_abs.max()) if not drawdown_abs.empty else 0.0
    peak_capital = float(roll_max.max()) if not roll_max.empty else float(initial_capital)
    max_drawdown_pct = (
        (max_drawdown_abs / peak_capital) * 100.0 if peak_capital > 0 else 0.0
    )

    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_win = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    win_rate_pct = float((len(wins) / len(pnls)) * 100.0) if len(pnls) else 0.0
    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = float(losses.mean()) if not losses.empty else 0.0
    payoff_ratio = avg_win / abs(avg_loss) if avg_loss < 0 else 0.0
    expectancy = float(pnls.mean()) if len(pnls) else 0.0

    std = float(pnls.std(ddof=1)) if len(pnls) > 1 else 0.0
    sharpe_like = (
        float(pnls.mean() / std * math.sqrt(len(pnls))) if std > 0 and len(pnls) > 1 else 0.0
    )
    total_return_pct = (
        float((equity.iloc[-1] - float(initial_capital)) / float(initial_capital) * 100.0)
        if len(equity) and initial_capital
        else 0.0
    )
    calmar_like = total_return_pct / abs(max_drawdown_pct) if max_drawdown_pct > 0 else 0.0
    trade_days = max(len(daily_pnl), 1)

    result.update(
        {
            "final_capital": round(float(equity.iloc[-1]), 2),
            "gross_pnl": round(float(gross_pnls.sum()), 2),
            "net_pnl": round(float(pnls.sum()), 2),
            "costs": round(float(sum(row["costs"] for row in normalized)), 2),
            "profit_factor": round(float(profit_factor), 2),
            "pf": round(float(profit_factor), 2),
            "win_rate_pct": round(win_rate_pct, 1),
            "wr_pct": round(win_rate_pct, 1),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "dd_pct": round(max_drawdown_pct, 2),
            "max_drawdown_abs": round(max_drawdown_abs, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "expectancy": round(expectancy, 2),
            "sharpe_like": round(sharpe_like, 2),
            "calmar_like": round(calmar_like, 2),
            "best_trade": round(float(pnls.max()), 2),
            "worst_trade": round(float(pnls.min()), 2),
            "best_day": round(max(daily_pnl.values()), 2) if daily_pnl else 0.0,
            "worst_day": round(min(daily_pnl.values()), 2) if daily_pnl else 0.0,
            "trade_density_per_day": round(len(pnls) / trade_days, 2),
        }
    )
    result["robustness_score"] = _robustness_score(
        profit_factor=result["profit_factor"],
        sharpe_like=result["sharpe_like"],
        max_drawdown_pct=result["max_drawdown_pct"],
        win_rate_pct=result["win_rate_pct"],
        trades=result["trades"],
        expectancy=result["expectancy"],
    )
    result["sample_trades"] = normalized[-15:]
    return result
