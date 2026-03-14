#!/usr/bin/env python3
"""
ALPHA GENIUS - FIXED VERSION (2026-03-13)
=========================================
BUGS FIXED:
  1. Fake sentiment analysis replaced with real indicator-based market bias
  2. Broken signal direction logic fixed (BUY/SELL based on net signal score)
  3. Fixed SuperTrend calculation (proper dynamic band)
  4. Fixed RSI to use Wilder's EMA (standard formula)
  5. Added ADX filter — only enter when trend is confirmed (ADX > 20)
  6. Added time filter — no entries before 9:30 AM or after 2:45 PM
  7. Added ATR volatility filter
  8. Added actual brokerage-aware P&L calculation
  9. Added trailing stop-loss execution (not just tracking)
  10. Added per-trade stop-loss exit signals
"""

import math
import logging
import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger("AlphaGenius")

# =========================================================================
# MARKET HOURS — IST
# =========================================================================
MARKET_OPEN_TIME = time(9, 30)     # FIXED: was 9:15, now avoid first 15 min
NO_ENTRY_AFTER = time(14, 45)       # No new entries after 2:45 PM
MARKET_CLOSE = time(15, 30)


def is_valid_trading_window() -> bool:
    """Check if current IST time is within the safe trading window."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata")).time()
    except Exception:
        now = datetime.now().time()
    return MARKET_OPEN_TIME <= now <= NO_ENTRY_AFTER


# =========================================================================
# BLACK-SCHOLES GREEKS (unchanged — was correct)
# =========================================================================

def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def norm_pdf(x):
    return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x**2)

def calculate_greeks(S, K, T, r=0.065, sigma=0.15, option_type='CE'):
    try:
        if T <= 0 or sigma <= 0:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == 'CE':
            delta = norm_cdf(d1)
            theta = (-(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
            rho = K * T * math.exp(-r * T) * norm_cdf(d2)
        else:
            delta = -norm_cdf(-d1)
            theta = (-(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm_cdf(-d2)) / 365
            rho = -K * T * math.exp(-r * T) * norm_cdf(-d2)
        gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
        vega = S * math.sqrt(T) * norm_pdf(d1) / 100
        return {
            "delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta": round(theta, 4), "vega": round(vega, 4), "rho": round(rho, 4)
        }
    except Exception:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}


# =========================================================================
# OI ANALYSIS (unchanged — was correct)
# =========================================================================

def calculate_pcr(chain_data: List[Dict]) -> float:
    total_ce_oi = sum(item.get('ce_oi', 0) for item in chain_data)
    total_pe_oi = sum(item.get('pe_oi', 0) for item in chain_data)
    return round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0

def calculate_max_pain(chain_data: List[Dict]) -> Optional[float]:
    try:
        strikes = sorted(set(item['strike'] for item in chain_data))
        total_loss = []
        for strike in strikes:
            loss = 0
            for item in chain_data:
                k = item['strike']
                ce_oi = item.get('ce_oi', 0)
                pe_oi = item.get('pe_oi', 0)
                if strike > k:
                    loss += (strike - k) * ce_oi
                if strike < k:
                    loss += (k - strike) * pe_oi
            total_loss.append(loss)
        return strikes[total_loss.index(min(total_loss))]
    except Exception:
        return None

def analyze_oi_change(chain_data: List[Dict]) -> Dict:
    try:
        max_ce_oi = max(chain_data, key=lambda x: x.get('ce_oi', 0))
        max_pe_oi = max(chain_data, key=lambda x: x.get('pe_oi', 0))
        return {
            "max_ce_strike": max_ce_oi.get('strike'),
            "max_ce_oi": max_ce_oi.get('ce_oi', 0),
            "max_pe_strike": max_pe_oi.get('strike'),
            "max_pe_oi": max_pe_oi.get('pe_oi', 0),
            "pcr": calculate_pcr(chain_data)
        }
    except Exception:
        return {"pcr": 1.0}


# =========================================================================
# FIXED TECHNICAL INDICATORS
# =========================================================================

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR — unchanged, was correct."""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    """
    FIXED: ADX calculation (Average Directional Index).
    Returns ADX value (0-100). > 20 = trending, > 25 = strong trend.
    """
    if len(df) < period + 1:
        return 0.0

    high, low, close = df['high'], df['low'], df['close']

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_smooth)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_smooth)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    return round(float(adx.iloc[-1]), 2)


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3) -> Tuple[str, float]:
    """
    FIXED SuperTrend calculation.
    Bug was: using lower_band.iloc[i-1] instead of proper dynamic supertrend line.
    """
    if len(df) < period + 1:
        return "NEUTRAL", 0.0

    high, low, close = df['high'], df['low'], df['close']

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    hl_avg = (high + low) / 2
    upper_band = hl_avg + (multiplier * atr)
    lower_band = hl_avg - (multiplier * atr)

    supertrend = [None] * len(close)
    direction = [True] * len(close)  # True = uptrend

    for i in range(1, len(close)):
        if pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
            supertrend[i] = supertrend[i-1]
            direction[i] = direction[i-1]
            continue

        prev_upper = supertrend[i-1] if (not direction[i-1]) else upper_band.iloc[i]
        prev_lower = supertrend[i-1] if direction[i-1] else lower_band.iloc[i]

        final_upper = upper_band.iloc[i] if (upper_band.iloc[i] < prev_upper or close.iloc[i-1] > prev_upper) else prev_upper
        final_lower = lower_band.iloc[i] if (lower_band.iloc[i] > prev_lower or close.iloc[i-1] < prev_lower) else prev_lower

        if direction[i-1]:
            if close.iloc[i] < final_lower:
                direction[i] = False
                supertrend[i] = final_upper
            else:
                direction[i] = True
                supertrend[i] = final_lower
        else:
            if close.iloc[i] > final_upper:
                direction[i] = True
                supertrend[i] = final_lower
            else:
                direction[i] = False
                supertrend[i] = final_upper

    current_trend = "UP" if direction[-1] else "DOWN"
    return current_trend, round(float(atr.iloc[-1]), 2)


def calculate_macd(df: pd.DataFrame) -> Dict:
    """MACD — unchanged, was correct."""
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return {
        "macd": round(float(macd.iloc[-1]), 2),
        "signal": round(float(signal.iloc[-1]), 2),
        "histogram": round(float(histogram.iloc[-1]), 2),
        "trend": "BULLISH" if macd.iloc[-1] > signal.iloc[-1] else "BEARISH",
        "crossover": histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0,
        "crossunder": histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0,
    }


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """
    FIXED RSI using Wilder's EMA (not simple rolling mean).
    """
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def calculate_ema(df: pd.DataFrame, period: int) -> float:
    return round(float(df['close'].ewm(span=period, adjust=False).mean().iloc[-1]), 2)


def calculate_iv_percentile(historical_iv: List[float], current_iv: float) -> float:
    if not historical_iv:
        return 50
    sorted_iv = sorted(historical_iv)
    percentile = sum(1 for iv in sorted_iv if iv < current_iv) / len(sorted_iv) * 100
    return round(percentile, 1)


# =========================================================================
# MAIN STRATEGY CLASS — FIXED
# =========================================================================

@dataclass
class TradeSignal:
    symbol: str
    direction: str          # BUY or SELL
    entry_price: float
    stop_loss: float
    target: float
    confidence: float       # 0-100%
    reason: str
    greeks: Dict = field(default_factory=dict)
    oi_analysis: Dict = field(default_factory=dict)
    adx: float = 0.0
    atr: float = 0.0
    rsi: float = 50.0


class AlphaGeniusStrategy:
    """
    FIXED Advanced intraday strategy using multi-factor analysis.
    """

    def __init__(self, segment: str = "BANKNIFTY"):
        self.segment = segment
        self.segment_config = {
            "BANKNIFTY": {"lot_size": 15, "strike_step": 100, "expiry": "weekly"},
            "NIFTY":     {"lot_size": 75, "strike_step": 50,  "expiry": "weekly"},
            "FINNIFTY":  {"lot_size": 40, "strike_step": 50,  "expiry": "weekly"}
        }
        self.max_daily_loss = 5000
        self.daily_profit_target = 15000
        self.max_position_size = 25000
        self.daily_pnl = 0.0
        self.net_daily_pnl = 0.0
        self.trades_today = 0
        self.positions = []
        self.total_brokerage = 0.0

    def _get_market_bias_from_indicators(
        self, trend: str, macd: Dict, rsi: float,
        oi_analysis: Dict, adx: float
    ) -> Dict:
        """
        FIXED: Replace fake time-based sentiment with real indicator-based bias.
        """
        bullish_score = 0
        bearish_score = 0
        reasons = []

        if trend == "UP":
            bullish_score += 30
            reasons.append("SuperTrend UP")
        elif trend == "DOWN":
            bearish_score += 30
            reasons.append("SuperTrend DOWN")

        if macd["trend"] == "BULLISH":
            bullish_score += 20
            if macd.get("crossover"):
                bullish_score += 10
                reasons.append("MACD Bull Crossover")
            else:
                reasons.append("MACD Bullish")
        elif macd["trend"] == "BEARISH":
            bearish_score += 20
            if macd.get("crossunder"):
                bearish_score += 10
                reasons.append("MACD Bear Crossunder")
            else:
                reasons.append("MACD Bearish")

        if rsi < 35:
            bullish_score += 15
            reasons.append(f"RSI Oversold ({rsi})")
        elif rsi > 65:
            bearish_score += 15
            reasons.append(f"RSI Overbought ({rsi})")

        pcr = oi_analysis.get("pcr", 1.0)
        if pcr < 0.7:
            bullish_score += 10
            reasons.append(f"Low PCR ({pcr}) = Bullish")
        elif pcr > 1.5:
            bearish_score += 10
            reasons.append(f"High PCR ({pcr}) = Bearish")

        net_score = bullish_score - bearish_score

        if net_score >= 30:
            bias = "BUY"
        elif net_score <= -30:
            bias = "SELL"
        else:
            bias = "NO_TRADE"

        return {
            "bias": bias,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "net_score": net_score,
            "reasons": reasons,
            "adx_confirmed": adx >= 20,
        }

    def analyze_market(
        self,
        spot_price: float,
        chain_data: List[Dict],
        historical_data: pd.DataFrame
    ) -> Optional[TradeSignal]:
        """
        FIXED Main analysis function.
        """
        if not is_valid_trading_window():
            logger.info("Skipping signal: outside safe trading window (09:30-14:45 IST)")
            return None

        if len(historical_data) < 30:
            logger.warning("Insufficient data for signal generation")
            return None

        adx = calculate_adx(historical_data)
        if adx < 20:
            logger.info(f"Skipping signal: ADX={adx:.1f} < 20 (market too choppy)")
            return None

        atr = calculate_atr(historical_data)
        atr_pct = (atr / spot_price) * 100
        if atr_pct < 0.30:
            logger.info(f"Skipping signal: ATR={atr_pct:.2f}% < 0.30% (too quiet)")
            return None
        if atr_pct > 4.0:
            logger.info(f"Skipping signal: ATR={atr_pct:.2f}% > 4.0% (too volatile)")
            return None

        trend, _ = calculate_supertrend(historical_data)
        macd = calculate_macd(historical_data)
        rsi = calculate_rsi(historical_data)
        oi_analysis = analyze_oi_change(chain_data) if chain_data else {"pcr": 1.0}

        bias_result = self._get_market_bias_from_indicators(trend, macd, rsi, oi_analysis, adx)

        if bias_result["bias"] == "NO_TRADE":
            logger.info(f"No clear directional bias (net_score={bias_result['net_score']})")
            return None

        if not bias_result["adx_confirmed"]:
            logger.info(f"ADX too low ({adx}), skipping")
            return None

        direction = bias_result["bias"]
        confidence = abs(bias_result["net_score"])

        T = max(1/365, 3/365)
        atm_strike = round(spot_price / 50) * 50
        greeks = calculate_greeks(spot_price, atm_strike, T)

        atr_sl_multiplier = 1.5
        atr_tp_multiplier = 2.5

        if direction == "BUY":
            stop_loss = spot_price - (atr * atr_sl_multiplier)
            target = spot_price + (atr * atr_tp_multiplier)
        else:
            stop_loss = spot_price + (atr * atr_sl_multiplier)
            target = spot_price - (atr * atr_tp_multiplier)

        return TradeSignal(
            symbol=self.segment,
            direction=direction,
            entry_price=round(spot_price, 2),
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            confidence=min(confidence, 90),
            reason=" | ".join(bias_result["reasons"]),
            greeks=greeks,
            oi_analysis=oi_analysis,
            adx=adx,
            atr=round(atr, 2),
            rsi=rsi,
        )

    def check_exit_signals(
        self, position: Dict, current_price: float
    ) -> Optional[str]:
        """
        FIXED: Check if current trade should be exited.
        Returns 'STOP_LOSS', 'TARGET', 'TRAILING_STOP', or None.
        """
        entry = position["entry_price"]
        sl = position.get("stop_loss", 0)
        target = position.get("target", float("inf"))
        trade_type = position.get("type", "BUY")
        quantity = position.get("quantity", 1)

        if "peak_pnl" not in position:
            position["peak_pnl"] = 0.0

        if trade_type == "BUY":
            current_pnl = (current_price - entry) * quantity
            r_size = entry - sl if sl > 0 else entry * 0.02
            if current_pnl > r_size:
                new_sl = current_price - r_size
                if new_sl > sl:
                    position["stop_loss"] = new_sl
                    sl = new_sl

            if current_price <= sl:
                return "STOP_LOSS"
            if current_price >= target:
                return "TARGET"
        else:
            current_pnl = (entry - current_price) * quantity
            r_size = sl - entry if sl > entry else entry * 0.02
            if current_pnl > r_size:
                new_sl = current_price + r_size
                if new_sl < sl:
                    position["stop_loss"] = new_sl
                    sl = new_sl

            if current_price >= sl:
                return "STOP_LOSS"
            if current_price <= target:
                return "TARGET"

        return None

    def calculate_net_pnl(self, gross_pnl: float, trade_value: float) -> float:
        brokerage = 40
        stt = trade_value * 0.0000625
        exchange_charges = trade_value * 0.00002
        gst = (brokerage + exchange_charges) * 0.18
        total_charges = brokerage + stt + exchange_charges + gst
        return gross_pnl - total_charges

    def check_risk_limits(self) -> bool:
        if self.daily_pnl <= -self.max_daily_loss:
            logger.error(f"MAX LOSS HIT: Rs.{self.daily_pnl:.2f}")
            return False
        if self.daily_pnl >= self.daily_profit_target:
            logger.info(f"TARGET REACHED: Rs.{self.daily_pnl:.2f}")
            return False
        return True

    def get_status(self) -> Dict:
        return {
            "strategy": "AlphaGenius (FIXED)",
            "segment": self.segment,
            "daily_pnl": round(self.daily_pnl, 2),
            "net_daily_pnl": round(self.net_daily_pnl, 2),
            "total_brokerage_paid": round(self.total_brokerage, 2),
            "trades": self.trades_today,
            "positions": len(self.positions),
            "can_trade": self.check_risk_limits(),
            "trading_window_open": is_valid_trading_window(),
        }


# =========================================================================
# FIXED BACKTEST ENGINE
# =========================================================================

class BacktestEngine:
    def __init__(self, initial_capital: float = 500000):
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.trades = []
        self.equity_curve = []
        self.brokerage_total = 0.0

    def run_backtest(
        self,
        historical_data: pd.DataFrame,
        chain_data: List[Dict],
        segment: str = "BANKNIFTY",
        lot_size: int = 15,
    ) -> Dict:
        BROKERAGE_PER_TRADE = 40
        strategy = AlphaGeniusStrategy(segment)
        results = []
        equity = self.initial_capital

        if len(historical_data) < 60:
            return {"error": "Insufficient data (need 60+ bars)"}

        for i in range(50, len(historical_data)):
            df = historical_data.iloc[:i+1].copy()
            if len(df) < 50:
                continue

            spot = float(df['close'].iloc[-1])
            signal = strategy.analyze_market(spot, chain_data, df)

            if not signal or not strategy.check_risk_limits():
                continue

            entry_price = spot
            sl = signal.stop_loss
            target = signal.target
            direction = signal.direction

            exit_price = entry_price
            exit_reason = "EOD"

            for j in range(i+1, min(i+16, len(historical_data))):
                bar = historical_data.iloc[j]
                if direction == "BUY":
                    if bar['low'] <= sl:
                        exit_price = sl
                        exit_reason = "STOP_LOSS"
                        break
                    elif bar['high'] >= target:
                        exit_price = target
                        exit_reason = "TARGET"
                        break
                else:
                    if bar['high'] >= sl:
                        exit_price = sl
                        exit_reason = "STOP_LOSS"
                        break
                    elif bar['low'] <= target:
                        exit_price = target
                        exit_reason = "TARGET"
                        break
            else:
                exit_price = float(historical_data.iloc[min(i+15, len(historical_data)-1)]['close'])

            if direction == "BUY":
                gross_pnl = (exit_price - entry_price) * lot_size
            else:
                gross_pnl = (entry_price - exit_price) * lot_size

            trade_value = entry_price * lot_size
            stt = trade_value * 0.0000625
            charges = BROKERAGE_PER_TRADE + stt
            net_pnl = gross_pnl - charges

            equity += net_pnl
            self.equity_curve.append(equity)

            results.append({
                "bar": i,
                "direction": direction,
                "entry": round(entry_price, 2),
                "exit": round(exit_price, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "net_pnl": round(net_pnl, 2),
                "exit_reason": exit_reason,
                "confidence": signal.confidence,
                "adx": signal.adx,
                "rsi": signal.rsi,
                "reason": signal.reason,
            })

            strategy.daily_pnl += net_pnl
            strategy.trades_today += 1

        if not results:
            return {"error": "No trades generated", "total_trades": 0}

        winning_trades = [r for r in results if r['net_pnl'] > 0]
        losing_trades = [r for r in results if r['net_pnl'] <= 0]
        sl_hits = [r for r in results if r['exit_reason'] == 'STOP_LOSS']
        target_hits = [r for r in results if r['exit_reason'] == 'TARGET']

        total_net_pnl = sum(r['net_pnl'] for r in results)
        total_gross_pnl = sum(r['gross_pnl'] for r in results)
        total_charges = sum(r['charges'] for r in results)
        win_rate = len(winning_trades) / len(results) * 100

        avg_win = np.mean([r['net_pnl'] for r in winning_trades]) if winning_trades else 0
        avg_loss = abs(np.mean([r['net_pnl'] for r in losing_trades])) if losing_trades else 0
        profit_factor = (avg_win * len(winning_trades)) / (avg_loss * len(losing_trades) + 1e-9)

        peak = self.initial_capital
        max_dd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = peak - eq
            max_dd = max(max_dd, dd)

        pnls = [r['net_pnl'] for r in results]
        if len(pnls) > 1:
            sharpe = (np.mean(pnls) / (np.std(pnls) + 1e-9)) * np.sqrt(len(pnls))
        else:
            sharpe = 0.0

        return_over_dd = total_net_pnl / (max_dd + 1e-9)

        return {
            "segment": segment,
            "total_trades": len(results),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "sl_hits": len(sl_hits),
            "target_hits": len(target_hits),
            "win_rate_pct": round(win_rate, 1),
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_charges": round(total_charges, 2),
            "total_net_pnl": round(total_net_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(-avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "return_over_max_dd": round(return_over_dd, 2),
            "final_capital": round(self.initial_capital + total_net_pnl, 2),
            "return_pct": round((total_net_pnl / self.initial_capital) * 100, 2),
            "trades": results,
        }
