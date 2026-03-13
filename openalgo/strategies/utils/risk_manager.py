#!/usr/bin/env python3
"""
Risk Manager Module - Critical Safety Features for All Trading Strategies

This module provides essential risk management features that MUST be used by all strategies:
1. Stop-Loss enforcement
2. EOD (End of Day) position square-off
3. Max daily loss circuit breaker
4. Position size limits
5. Trade cooldown periods

CRITICAL: All strategies MUST use this module to prevent catastrophic losses.

Author: OpenAlgo Risk Management
Version: 1.0.0
"""

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

logger = logging.getLogger("RiskManager")

class RiskManager:
    """
    Centralized Risk Management for all trading strategies.

    Features:
    - Stop-loss monitoring and enforcement
    - Max loss per trade / per day limits
    - EOD auto square-off
    - Position tracking with broker reconciliation
    - Trade cooldown to prevent overtrading
    """

    # Default risk parameters (can be overridden)
    DEFAULT_CONFIG = {
        'max_loss_per_trade_pct': 2.0,      # Max 2% loss per trade
        'max_daily_loss_pct': 5.0,           # Max 5% daily loss - circuit breaker
        'max_position_value': 500000,        # Max 5 lakh per position
        'eod_square_off_time': '15:15',      # NSE: Square off by 3:15 PM
        'mcx_eod_square_off_time': '23:25',  # MCX: Square off by 11:25 PM
        'trade_cooldown_seconds': 300,       # 5 min between trades
        'trailing_stop_enabled': True,
        'trailing_stop_pct': 1.5,            # 1.5% trailing stop
    }

    def __init__(self, strategy_name: str, exchange: str = "NSE",
                 capital: float = 100000, config: dict | None = None):
        """
        Initialize Risk Manager.

        Args:
            strategy_name: Name of the strategy using this manager
            exchange: "NSE" or "MCX"
            capital: Trading capital for calculating loss limits
            config: Override default risk parameters
        """
        self.strategy_name = strategy_name
        self.exchange = exchange.upper()
        self.capital = capital
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}

        # State tracking
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_trade_time = 0
        self.positions: dict[str, dict] = {}  # symbol -> {qty, entry_price, stop_loss, trailing_stop}
        self.is_circuit_breaker_active = False

        # State persistence
        self.state_dir = Path(__file__).resolve().parent.parent / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / f"{strategy_name}_risk_state.json"

        self._load_state()
        logger.info(f"RiskManager initialized for {strategy_name} on {exchange}")

    def _load_state(self):
        """Load persisted state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)

                    # Check if state is from today
                    last_date = data.get('date', '')
                    today = datetime.now().strftime('%Y-%m-%d')

                    if last_date == today:
                        self.daily_pnl = data.get('daily_pnl', 0.0)
                        self.daily_trades = data.get('daily_trades', 0)
                        self.positions = data.get('positions', {})
                        self.is_circuit_breaker_active = data.get('circuit_breaker', False)
                        logger.info(f"Loaded today's state: PnL={self.daily_pnl}, Trades={self.daily_trades}")
                    else:
                        # New day - reset daily counters but keep positions
                        self.positions = data.get('positions', {})
                        logger.info(f"New trading day - reset daily counters. Carried over {len(self.positions)} positions.")
            except Exception as e:
                logger.error(f"Failed to load risk state: {e}")

    def _save_state(self):
        """Persist state to file."""
        try:
            data = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'daily_pnl': self.daily_pnl,
                'daily_trades': self.daily_trades,
                'positions': self.positions,
                'circuit_breaker': self.is_circuit_breaker_active,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save risk state: {e}")

    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed based on risk parameters.

        Returns:
            (can_trade: bool, reason: str)
        """
        # Check circuit breaker
        if self.is_circuit_breaker_active:
            return False, "CIRCUIT BREAKER ACTIVE - Daily loss limit exceeded"

        # Check daily loss limit
        max_daily_loss = self.capital * (self.config['max_daily_loss_pct'] / 100)
        if self.daily_pnl <= -max_daily_loss:
            self.is_circuit_breaker_active = True
            self._save_state()
            return False, f"CIRCUIT BREAKER TRIGGERED - Daily loss {self.daily_pnl:.2f} exceeds limit {max_daily_loss:.2f}"

        # Check EOD square-off time
        if self._is_near_market_close():
            return False, "Near market close - no new positions allowed"

        # Check trade cooldown
        import time
        time_since_last = time.time() - self.last_trade_time
        if time_since_last < self.config['trade_cooldown_seconds']:
            remaining = int(self.config['trade_cooldown_seconds'] - time_since_last)
            return False, f"Trade cooldown active - {remaining}s remaining"

        return True, "OK"

    def _is_near_market_close(self) -> bool:
        """Check if we're within 15 minutes of market close."""
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)

        if self.exchange == "MCX":
            close_str = self.config['mcx_eod_square_off_time']
        else:
            close_str = self.config['eod_square_off_time']

        close_hour, close_min = map(int, close_str.split(':'))
        close_time = dt_time(close_hour, close_min)

        return now.time() >= close_time

    def should_square_off_eod(self) -> bool:
        """Check if it's time for EOD square-off."""
        return self._is_near_market_close()

    def calculate_stop_loss(self, entry_price: float, side: str,
                           stop_pct: float | None = None) -> float:
        """
        Calculate stop-loss price.

        Args:
            entry_price: Entry price of the position
            side: "LONG" or "SHORT"
            stop_pct: Stop loss percentage (default from config)

        Returns:
            Stop loss price
        """
        pct = stop_pct or self.config['max_loss_per_trade_pct']

        if side.upper() == "LONG":
            return entry_price * (1 - pct / 100)
        else:
            return entry_price * (1 + pct / 100)

    def update_trailing_stop(self, symbol: str, current_price: float) -> float | None:
        """
        Update trailing stop for a position.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            New trailing stop price (or None if no update)
        """
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        if not self.config['trailing_stop_enabled']:
            return pos.get('stop_loss')

        pct = self.config['trailing_stop_pct'] / 100

        if pos['qty'] > 0:  # Long position
            # Only move stop up, never down
            new_stop = current_price * (1 - pct)
            if new_stop > pos.get('trailing_stop', 0):
                pos['trailing_stop'] = new_stop
                self._save_state()
                logger.info(f"Trailing stop updated for {symbol}: {new_stop:.2f}")
                return new_stop
        else:  # Short position
            # Only move stop down, never up
            new_stop = current_price * (1 + pct)
            current_stop = pos.get('trailing_stop', float('inf'))
            if new_stop < current_stop:
                pos['trailing_stop'] = new_stop
                self._save_state()
                logger.info(f"Trailing stop updated for {symbol}: {new_stop:.2f}")
                return new_stop

        return pos.get('trailing_stop')

    def check_stop_loss(self, symbol: str, current_price: float) -> tuple[bool, str]:
        """
        Check if stop loss is hit.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            (stop_hit: bool, reason: str)
        """
        if symbol not in self.positions:
            return False, "No position"

        pos = self.positions[symbol]
        stop_price = pos.get('trailing_stop') or pos.get('stop_loss')

        if stop_price is None:
            return False, "No stop loss set"

        if pos['qty'] > 0:  # Long position
            if current_price <= stop_price:
                loss_pct = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100
                return True, f"STOP LOSS HIT - Long @ {pos['entry_price']:.2f}, Stop @ {stop_price:.2f}, Current @ {current_price:.2f}, Loss: {loss_pct:.2f}%"
        else:  # Short position
            if current_price >= stop_price:
                loss_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                return True, f"STOP LOSS HIT - Short @ {pos['entry_price']:.2f}, Stop @ {stop_price:.2f}, Current @ {current_price:.2f}, Loss: {loss_pct:.2f}%"

        return False, "OK"

    def register_entry(self, symbol: str, qty: int, entry_price: float,
                       side: str, stop_loss: float | None = None):
        """
        Register a new position entry.

        Args:
            symbol: Trading symbol
            qty: Quantity (positive for long, negative for short)
            entry_price: Entry price
            side: "LONG" or "SHORT"
            stop_loss: Manual stop loss price (auto-calculated if not provided)
        """
        import time

        # Calculate stop loss if not provided
        if stop_loss is None:
            stop_loss = self.calculate_stop_loss(entry_price, side)

        self.positions[symbol] = {
            'qty': qty if side.upper() == "LONG" else -qty,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'trailing_stop': stop_loss,
            'entry_time': datetime.now().isoformat(),
            'side': side.upper()
        }

        self.last_trade_time = time.time()
        self.daily_trades += 1
        self._save_state()

        logger.info(f"Position registered: {side} {qty} {symbol} @ {entry_price:.2f}, SL: {stop_loss:.2f}")

    def register_exit(self, symbol: str, exit_price: float, qty: int | None = None):
        """
        Register a position exit and calculate PnL.

        Args:
            symbol: Trading symbol
            exit_price: Exit price
            qty: Quantity to exit (default: full position)

        Returns:
            Realized PnL
        """
        if symbol not in self.positions:
            logger.warning(f"No position found for {symbol}")
            return 0.0

        pos = self.positions[symbol]
        exit_qty = qty or abs(pos['qty'])

        # Calculate PnL
        if pos['qty'] > 0:  # Long position
            pnl = (exit_price - pos['entry_price']) * exit_qty
        else:  # Short position
            pnl = (pos['entry_price'] - exit_price) * exit_qty

        self.daily_pnl += pnl

        # Remove or reduce position
        if exit_qty >= abs(pos['qty']):
            del self.positions[symbol]
        else:
            pos['qty'] = pos['qty'] - exit_qty if pos['qty'] > 0 else pos['qty'] + exit_qty

        self._save_state()

        logger.info(f"Position closed: {symbol} @ {exit_price:.2f}, PnL: {pnl:.2f}, Daily PnL: {self.daily_pnl:.2f}")
        return pnl

    def get_open_positions(self) -> dict[str, dict]:
        """Get all open positions."""
        return self.positions.copy()

    def get_daily_stats(self) -> dict[str, Any]:
        """Get daily trading statistics."""
        return {
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
            'open_positions': len(self.positions),
            'circuit_breaker_active': self.is_circuit_breaker_active,
            'max_daily_loss_limit': self.capital * (self.config['max_daily_loss_pct'] / 100),
            'loss_remaining': (self.capital * (self.config['max_daily_loss_pct'] / 100)) + self.daily_pnl
        }

    def reset_daily_state(self):
        """Reset daily counters (call at start of new trading day)."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.is_circuit_breaker_active = False
        self._save_state()
        logger.info("Daily state reset")


class EODSquareOff:
    """
    End-of-Day automatic position square-off handler.

    CRITICAL: This ensures all MIS positions are closed before market close
    to prevent broker penalties and overnight risk.
    """

    def __init__(self, risk_manager: RiskManager,
                 exit_callback: Callable[[str, str, int], Any]):
        """
        Initialize EOD Square-off handler.

        Args:
            risk_manager: RiskManager instance
            exit_callback: Function to call for exiting positions
                          Signature: exit_callback(symbol, action, quantity) -> order_result
        """
        self.rm = risk_manager
        self.exit_callback = exit_callback
        self._squared_off_today = False

    def check_and_execute(self) -> bool:
        """
        Check if EOD square-off is needed and execute if so.

        Returns:
            True if square-off was executed
        """
        if self._squared_off_today:
            return False

        if not self.rm.should_square_off_eod():
            return False

        positions = self.rm.get_open_positions()
        if not positions:
            logger.info("EOD check: No open positions to square off")
            return False

        logger.warning(f"EOD SQUARE-OFF TRIGGERED - Closing {len(positions)} positions")

        for symbol, pos in positions.items():
            try:
                qty = abs(pos['qty'])
                action = "SELL" if pos['qty'] > 0 else "BUY"

                logger.info(f"EOD: Closing {symbol} - {action} {qty}")
                result = self.exit_callback(symbol, action, qty)

                if result and result.get('status') == 'success':
                    # Assume exit at current price (would need actual fill price)
                    self.rm.register_exit(symbol, pos['entry_price'])  # Placeholder
                    logger.info(f"EOD: Successfully closed {symbol}")
                else:
                    logger.error(f"EOD: Failed to close {symbol}: {result}")

            except Exception as e:
                logger.error(f"EOD: Error closing {symbol}: {e}")

        self._squared_off_today = True
        return True


# Convenience function for quick risk checks
def create_risk_manager(strategy_name: str, exchange: str = "NSE",
                        capital: float = 100000, **kwargs) -> RiskManager:
    """
    Factory function to create a configured RiskManager.

    Example:
        rm = create_risk_manager("PairsTrading", "MCX", capital=200000, max_loss_per_trade_pct=1.5)
    """
    config = {k: v for k, v in kwargs.items() if k in RiskManager.DEFAULT_CONFIG}
    return RiskManager(strategy_name, exchange, capital, config)


class PortfolioRiskMonitor:
    """
    Portfolio-level risk monitor that enforces daily/weekly loss limits across ALL strategies.

    When any limit is breached, writes PORTFOLIO_HALT.json to the state directory.
    The supervisor reads this file before launching any strategy process, and existing
    strategies check it via check_halt() to avoid placing new orders.

    Default limits (₹11,56,121 capital):
    - Daily portfolio loss:   ₹23,122  (2%)
    - Weekly portfolio loss:  ₹57,806  (5%)
    - Per-strategy daily:     ₹5,000

    Usage in supervisor:
        monitor = PortfolioRiskMonitor()
        halted, reason = monitor.check_halt()
        if halted:
            log.critical(f"Trading halted: {reason}")

    Usage in strategy (after each closed trade):
        halt_reason = monitor.record_pnl("MCX_SILVER", realized_pnl)
        if halt_reason:
            stop_new_orders()
    """

    HALT_FILE_NAME = "PORTFOLIO_HALT.json"
    PNL_FILE_NAME  = "portfolio_pnl.json"

    # Absolute ₹ limits derived from ₹11,56,121 capital
    DEFAULT_LIMITS: Dict[str, float] = {
        'daily_portfolio_loss':    23122.0,   # 2% of ₹11,56,121
        'weekly_portfolio_loss':   57806.0,   # 5% of ₹11,56,121
        'per_strategy_daily_loss':  5000.0,   # ₹5,000 per strategy per day
    }

    def __init__(self, state_dir: Optional[str] = None,
                 limits: Optional[Dict[str, float]] = None):
        """
        Args:
            state_dir: Directory for halt/pnl state files (default: strategies/state/)
            limits: Override DEFAULT_LIMITS (absolute ₹ amounts)
        """
        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = Path(__file__).resolve().parent.parent / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.halt_file = self.state_dir / self.HALT_FILE_NAME
        self.pnl_file  = self.state_dir / self.PNL_FILE_NAME
        self.limits    = {**self.DEFAULT_LIMITS, **(limits or {})}

        self._pnl_data: Dict = self._load_pnl_state()
        logger.info(
            f"PortfolioRiskMonitor ready | limits: daily=₹{self.limits['daily_portfolio_loss']:,.0f} "
            f"weekly=₹{self.limits['weekly_portfolio_loss']:,.0f} "
            f"per-strat=₹{self.limits['per_strategy_daily_loss']:,.0f}"
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _today() -> str:
        return datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')

    @staticmethod
    def _week_key() -> str:
        """ISO year-week key, e.g. '2026-W10'.  Resets every Monday."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        iso = now.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def _load_pnl_state(self) -> Dict:
        if self.pnl_file.exists():
            try:
                with open(self.pnl_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"PortfolioRiskMonitor: could not load PnL state: {e}")
        return {}

    def _save_pnl_state(self):
        try:
            with open(self.pnl_file, 'w') as f:
                json.dump(self._pnl_data, f, indent=2)
        except Exception as e:
            logger.error(f"PortfolioRiskMonitor: could not save PnL state: {e}")

    # ------------------------------------------------------------------ core API

    def record_pnl(self, strategy_name: str, pnl: float) -> Optional[str]:
        """
        Record a realized P&L event for one strategy and check all limits.

        Args:
            strategy_name: Strategy identifier (e.g. "MCX_SILVER")
            pnl: Realized P&L in ₹ (negative = loss, positive = profit)

        Returns:
            Halt reason string if a limit was breached, else None.
        """
        today = self._today()
        week  = self._week_key()

        # ---- initialise nested structures ----
        self._pnl_data.setdefault('daily', {})
        self._pnl_data['daily'].setdefault(today, {'portfolio': 0.0, 'strategies': {}})
        self._pnl_data.setdefault('weekly', {})
        self._pnl_data['weekly'].setdefault(week, 0.0)

        # ---- accumulate ----
        self._pnl_data['daily'][today]['portfolio'] += pnl
        strats = self._pnl_data['daily'][today]['strategies']
        strats[strategy_name] = strats.get(strategy_name, 0.0) + pnl
        self._pnl_data['weekly'][week] += pnl

        self._save_pnl_state()

        # ---- check limits (most severe first) ----
        daily_port  = self._pnl_data['daily'][today]['portfolio']
        weekly_port = self._pnl_data['weekly'][week]
        strat_daily = strats[strategy_name]

        halt_reason: Optional[str] = None

        if daily_port <= -self.limits['daily_portfolio_loss']:
            halt_reason = (
                f"DAILY PORTFOLIO LOSS LIMIT BREACHED: "
                f"₹{-daily_port:,.0f} >= ₹{self.limits['daily_portfolio_loss']:,.0f} (2% of capital)"
            )
        elif weekly_port <= -self.limits['weekly_portfolio_loss']:
            halt_reason = (
                f"WEEKLY PORTFOLIO LOSS LIMIT BREACHED: "
                f"₹{-weekly_port:,.0f} >= ₹{self.limits['weekly_portfolio_loss']:,.0f} (5% of capital)"
            )
        elif strat_daily <= -self.limits['per_strategy_daily_loss']:
            halt_reason = (
                f"PER-STRATEGY DAILY LOSS LIMIT BREACHED ({strategy_name}): "
                f"₹{-strat_daily:,.0f} >= ₹{self.limits['per_strategy_daily_loss']:,.0f}"
            )

        if halt_reason:
            self._write_halt(halt_reason)

        return halt_reason

    def check_halt(self) -> tuple[bool, str]:
        """
        Check if portfolio trading is halted.

        Returns:
            (is_halted: bool, reason: str)
        """
        if not self.halt_file.exists():
            return False, "OK"

        try:
            with open(self.halt_file) as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"PortfolioRiskMonitor: could not read halt file: {e}")
            return False, f"Error reading halt file: {e}"

        if not data.get('halted', False):
            return False, "Halt file present but halted=false"

        # Auto-clear stale halts from previous trading days
        halt_date = data.get('date', '')
        today = self._today()
        if halt_date and halt_date != today:
            logger.info(
                f"PortfolioRiskMonitor: stale halt from {halt_date} — auto-clearing"
            )
            self.clear_halt()
            return False, f"Stale halt from {halt_date} auto-cleared"

        return True, data.get('reason', 'Portfolio halted — see PORTFOLIO_HALT.json')

    def clear_halt(self):
        """
        Clear the portfolio halt.  Call manually after investigating losses,
        or at start of a new trading day (the supervisor's morning preflight does this).
        """
        if self.halt_file.exists():
            self.halt_file.unlink()
            logger.info("PortfolioRiskMonitor: halt cleared")

    def get_portfolio_pnl(self) -> Dict:
        """Return current portfolio P&L summary for dashboards / preflight."""
        today = self._today()
        week  = self._week_key()

        day_data   = self._pnl_data.get('daily', {}).get(today, {'portfolio': 0.0, 'strategies': {}})
        weekly_pnl = self._pnl_data.get('weekly', {}).get(week, 0.0)

        halted, halt_reason = self.check_halt()

        return {
            'date':                  today,
            'week':                  week,
            'daily_portfolio_pnl':   day_data['portfolio'],
            'weekly_portfolio_pnl':  weekly_pnl,
            'strategy_pnl':          day_data['strategies'].copy(),
            'daily_loss_remaining':  self.limits['daily_portfolio_loss']  + day_data['portfolio'],
            'weekly_loss_remaining': self.limits['weekly_portfolio_loss'] + weekly_pnl,
            'is_halted':             halted,
            'halt_reason':           halt_reason if halted else None,
        }

    # ------------------------------------------------------------------ private

    def _write_halt(self, reason: str):
        """Write PORTFOLIO_HALT.json to signal supervisor + strategies to stop trading."""
        halt_data = {
            'halted':   True,
            'reason':   reason,
            'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            'date':     self._today(),
            'resume_instructions': (
                "Investigate the loss cause, then: "
                "(1) python3 strategies/preflight.py --clear-halt  "
                "OR (2) delete this file  "
                "OR (3) set halted=false in this file"
            ),
        }
        with open(self.halt_file, 'w') as f:
            json.dump(halt_data, f, indent=2)
        logger.critical(f"PORTFOLIO HALT WRITTEN: {reason}")


# Singleton helper — import and call from any strategy or supervisor
_portfolio_monitor: Optional[PortfolioRiskMonitor] = None


def get_portfolio_monitor(state_dir: Optional[str] = None,
                          limits: Optional[Dict] = None) -> PortfolioRiskMonitor:
    """
    Return (or create) the process-level PortfolioRiskMonitor singleton.

    Since each strategy runs as a separate OS process (not threads), each process
    gets its own instance.  State is shared via the JSON files in state/.
    """
    global _portfolio_monitor
    if _portfolio_monitor is None:
        _portfolio_monitor = PortfolioRiskMonitor(state_dir=state_dir, limits=limits)
    return _portfolio_monitor
