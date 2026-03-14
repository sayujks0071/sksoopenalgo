#!/usr/bin/env python3
"""
Real-time Profit Metrics Tracker
==================================
Tracks P&L with brokerage deduction, rolling Sharpe ratio,
max drawdown guard, daily loss limits, and SQLite trade log.

Usage:
    from profit_metrics.tracker import ProfitTracker
    tracker = ProfitTracker(initial_capital=500000, segment="FNO_OPTIONS")
    tracker.record_trade(symbol="BANKNIFTY24100CE", side="BUY", qty=15,
                        entry_price=180, exit_price=240)
    print(tracker.get_dashboard())
"""

import os
import json
import math
import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Dict, List
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("ProfitTracker")


def calculate_charges(
    trade_value: float,
    is_options: bool = False,
    is_mcx: bool = False
) -> Dict[str, float]:
    brokerage = 40.0

    if is_options:
        stt = trade_value * 0.0000625
        exchange_charges = trade_value * 0.00050
    elif is_mcx:
        stt = 0.0
        exchange_charges = trade_value * 0.00026
    else:
        stt = trade_value * 0.001
        exchange_charges = trade_value * 0.0000345

    sebi_charges = trade_value * 0.000001
    stamp_duty = trade_value * 0.00003
    gst = (brokerage + exchange_charges) * 0.18

    total = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst

    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 4),
        "exchange_charges": round(exchange_charges, 4),
        "sebi_charges": round(sebi_charges, 4),
        "stamp_duty": round(stamp_duty, 4),
        "gst": round(gst, 4),
        "total_charges": round(total, 2),
    }


@dataclass
class TradeRecord:
    timestamp: str
    segment: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    charges: float
    net_pnl: float
    trade_value: float
    exit_reason: str
    order_id: str = ""
    notes: str = ""


class ProfitTracker:
    def __init__(
        self,
        initial_capital: float = 500000,
        segment: str = "FNO_OPTIONS",
        max_daily_loss_pct: float = 1.0,
        daily_profit_target_pct: float = 3.0,
        max_drawdown_pct: float = 3.0,
        db_path: str = None,
    ):
        self.initial_capital = initial_capital
        self.segment = segment
        self.max_daily_loss = initial_capital * (max_daily_loss_pct / 100)
        self.daily_profit_target = initial_capital * (daily_profit_target_pct / 100)
        self.max_drawdown_limit = initial_capital * (max_drawdown_pct / 100)

        self.daily_gross_pnl = 0.0
        self.daily_net_pnl = 0.0
        self.daily_charges = 0.0
        self.daily_trades: List[TradeRecord] = []
        self.all_net_pnls: List[float] = []

        self.peak_capital = initial_capital
        self.current_capital = initial_capital
        self.max_drawdown_seen = 0.0

        self.trading_halted = False
        self.halt_reason = ""
        self.current_date = str(date.today())

        if db_path is None:
            db_path = str(Path(__file__).parent / "trades.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                trade_date TEXT,
                segment TEXT,
                symbol TEXT,
                side TEXT,
                quantity INTEGER,
                entry_price REAL,
                exit_price REAL,
                gross_pnl REAL,
                charges REAL,
                net_pnl REAL,
                trade_value REAL,
                exit_reason TEXT,
                order_id TEXT,
                notes TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT UNIQUE,
                segment TEXT,
                total_trades INTEGER,
                gross_pnl REAL,
                total_charges REAL,
                net_pnl REAL,
                win_rate REAL,
                sharpe_ratio REAL,
                max_drawdown REAL
            )
        """)
        conn.commit()
        conn.close()

    def _save_trade_to_db(self, trade: TradeRecord):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO trades (
                    timestamp, trade_date, segment, symbol, side, quantity,
                    entry_price, exit_price, gross_pnl, charges, net_pnl,
                    trade_value, exit_reason, order_id, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade.timestamp, self.current_date, trade.segment,
                trade.symbol, trade.side, trade.quantity,
                trade.entry_price, trade.exit_price,
                trade.gross_pnl, trade.charges, trade.net_pnl,
                trade.trade_value, trade.exit_reason,
                trade.order_id, trade.notes,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB write failed: {e}")

    def record_trade(
        self,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        exit_reason: str = "MANUAL",
        order_id: str = "",
        notes: str = "",
    ) -> TradeRecord:
        today = str(date.today())
        if today != self.current_date:
            self._save_daily_summary()
            self._reset_daily_state(today)

        if self.trading_halted:
            logger.error(f"Trading halted: {self.halt_reason}")
            return None

        is_options = self.segment == "FNO_OPTIONS"
        is_mcx = self.segment == "MCX"

        if side.upper() == "BUY":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity

        trade_value = entry_price * quantity
        charge_breakdown = calculate_charges(trade_value, is_options, is_mcx)
        charges = charge_breakdown["total_charges"]
        net_pnl = gross_pnl - charges

        trade = TradeRecord(
            timestamp=datetime.now().isoformat(),
            segment=self.segment,
            symbol=symbol,
            side=side.upper(),
            quantity=quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            gross_pnl=round(gross_pnl, 2),
            charges=round(charges, 2),
            net_pnl=round(net_pnl, 2),
            trade_value=round(trade_value, 2),
            exit_reason=exit_reason,
            order_id=order_id,
            notes=notes,
        )

        self.daily_trades.append(trade)
        self.daily_gross_pnl += gross_pnl
        self.daily_net_pnl += net_pnl
        self.daily_charges += charges
        self.all_net_pnls.append(net_pnl)
        if len(self.all_net_pnls) > 20:
            self.all_net_pnls = self.all_net_pnls[-20:]

        self.current_capital += net_pnl
        self.peak_capital = max(self.peak_capital, self.current_capital)
        current_dd = self.peak_capital - self.current_capital
        self.max_drawdown_seen = max(self.max_drawdown_seen, current_dd)

        self._save_trade_to_db(trade)
        self._check_risk_limits_after_trade()

        return trade

    def _check_risk_limits_after_trade(self):
        if self.daily_net_pnl <= -self.max_daily_loss:
            self._halt_trading(f"Daily loss limit hit: Rs.{self.daily_net_pnl:.2f}")
            return
        if self.max_drawdown_seen >= self.max_drawdown_limit:
            self._halt_trading(f"Max drawdown hit: Rs.{self.max_drawdown_seen:.2f}")
            return
        if self.daily_net_pnl >= self.daily_profit_target:
            self._halt_trading(f"Daily profit target reached: Rs.{self.daily_net_pnl:.2f}", is_profit=True)

    def _halt_trading(self, reason: str, is_profit: bool = False):
        self.trading_halted = True
        self.halt_reason = reason
        prefix = "TARGET" if is_profit else "HALT"
        logger.error(f"{prefix}: TRADING HALTED: {reason}")
        self._save_daily_summary()

    def can_trade(self) -> Dict:
        if self.trading_halted:
            return {"allowed": False, "reason": self.halt_reason}
        return {"allowed": True, "reason": "OK"}

    def get_rolling_sharpe(self, n: int = 20) -> float:
        pnls = self.all_net_pnls[-n:]
        if len(pnls) < 3:
            return 0.0
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl)**2 for p in pnls) / max(1, len(pnls) - 1)
        std_pnl = math.sqrt(variance)
        if std_pnl == 0:
            return 0.0
        sharpe = (mean_pnl / std_pnl) * math.sqrt(252)
        return round(sharpe, 2)

    def get_win_rate(self) -> float:
        if not self.daily_trades:
            return 0.0
        wins = sum(1 for t in self.daily_trades if t.net_pnl > 0)
        return round(wins / len(self.daily_trades) * 100, 1)

    def get_dashboard(self) -> Dict:
        can_trade_status = self.can_trade()
        sharpe = self.get_rolling_sharpe()
        win_rate = self.get_win_rate()
        best = max(self.daily_trades, key=lambda t: t.net_pnl) if self.daily_trades else None
        worst = min(self.daily_trades, key=lambda t: t.net_pnl) if self.daily_trades else None

        return {
            "date": self.current_date,
            "segment": self.segment,
            "can_trade": can_trade_status["allowed"],
            "halt_reason": can_trade_status.get("reason", "") if not can_trade_status["allowed"] else "",
            "gross_pnl": round(self.daily_gross_pnl, 2),
            "total_charges": round(self.daily_charges, 2),
            "net_pnl": round(self.daily_net_pnl, 2),
            "net_pnl_pct": round((self.daily_net_pnl / self.initial_capital) * 100, 3),
            "max_daily_loss_limit": -round(self.max_daily_loss, 2),
            "daily_profit_target": round(self.daily_profit_target, 2),
            "current_drawdown": round(self.peak_capital - self.current_capital, 2),
            "max_drawdown_limit": round(self.max_drawdown_limit, 2),
            "max_drawdown_seen": round(self.max_drawdown_seen, 2),
            "total_trades": len(self.daily_trades),
            "win_rate_pct": win_rate,
            "rolling_sharpe": sharpe,
            "avg_net_pnl_per_trade": round(self.daily_net_pnl / max(1, len(self.daily_trades)), 2),
            "best_trade": round(best.net_pnl, 2) if best else 0,
            "worst_trade": round(worst.net_pnl, 2) if worst else 0,
            "initial_capital": self.initial_capital,
            "current_capital": round(self.current_capital, 2),
            "peak_capital": round(self.peak_capital, 2),
        }

    def print_dashboard(self):
        d = self.get_dashboard()
        status = "ACTIVE" if d["can_trade"] else f"HALTED: {d['halt_reason']}"
        print(f"\n{'='*55}")
        print(f"  P&L DASHBOARD — {d['date']} — {d['segment']}")
        print(f"  Status: {status}")
        print(f"{'='*55}")
        print(f"  Gross P&L:     Rs.{d['gross_pnl']:>12,.2f}")
        print(f"  Charges:       Rs.{d['total_charges']:>12,.2f}")
        print(f"  Net P&L:       Rs.{d['net_pnl']:>12,.2f}  ({d['net_pnl_pct']:+.2f}%)")
        print(f"  Daily Limit:   Rs.{d['max_daily_loss_limit']:>12,.2f}")
        print(f"  Daily Target:  Rs.{d['daily_profit_target']:>12,.2f}")
        print(f"  Drawdown:      Rs.{d['current_drawdown']:>12,.2f}  (limit: Rs.{d['max_drawdown_limit']:,.0f})")
        print(f"  Trades:        {d['total_trades']:>13}")
        print(f"  Win Rate:      {d['win_rate_pct']:>12.1f}%")
        print(f"  Sharpe (20T):  {d['rolling_sharpe']:>12.2f}")
        print(f"  Capital:       Rs.{d['current_capital']:>12,.2f}")
        print(f"{'='*55}\n")

    def _save_daily_summary(self):
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO daily_summary
                (trade_date, segment, total_trades, gross_pnl, total_charges,
                 net_pnl, win_rate, sharpe_ratio, max_drawdown)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                self.current_date, self.segment,
                len(self.daily_trades),
                round(self.daily_gross_pnl, 2),
                round(self.daily_charges, 2),
                round(self.daily_net_pnl, 2),
                self.get_win_rate(),
                self.get_rolling_sharpe(),
                round(self.max_drawdown_seen, 2),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Daily summary save failed: {e}")

    def _reset_daily_state(self, new_date: str):
        self.current_date = new_date
        self.daily_gross_pnl = 0.0
        self.daily_net_pnl = 0.0
        self.daily_charges = 0.0
        self.daily_trades = []
        self.trading_halted = False
        self.halt_reason = ""

    def get_historical_summary(self, days: int = 30):
        try:
            import pandas as pd
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query(
                "SELECT * FROM daily_summary ORDER BY trade_date DESC LIMIT ?",
                conn, params=(days,),
            )
            conn.close()
            return df
        except Exception as e:
            logger.error(f"History read failed: {e}")
            return None


if __name__ == "__main__":
    print("Testing ProfitTracker...")
    tracker = ProfitTracker(initial_capital=500000, segment="FNO_OPTIONS")
    trades = [
        ("BANKNIFTY24100CE", "BUY", 15, 180, 230, "TARGET"),
        ("BANKNIFTY24100PE", "BUY", 15, 120, 75,  "STOP_LOSS"),
        ("NIFTY24100CE",    "BUY", 75, 85,  130, "TARGET"),
        ("BANKNIFTY24100CE", "BUY", 15, 200, 155, "STOP_LOSS"),
        ("NIFTY24100CE",    "BUY", 75, 90,  110, "TARGET"),
    ]
    for symbol, side, qty, entry, exit_, reason in trades:
        t = tracker.record_trade(symbol, side, qty, entry, exit_, reason)
        if t:
            print(f"  {side} {symbol}: Net P&L = Rs.{t.net_pnl:.2f}")
    tracker.print_dashboard()
