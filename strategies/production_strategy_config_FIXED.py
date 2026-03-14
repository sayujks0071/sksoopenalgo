#!/usr/bin/env python3
"""
OpenAlgo Strategy Manager - FIXED Production Configuration
===========================================================
FIXES APPLIED (2026-03-13):
  - Correct BANKNIFTY lot size: 30 → 15 (NSE change Nov 2024)
  - Correct NIFTY lot size: 65 → 75 (NSE change Jul 2024)
  - MOMENTUM_ENTRY_PERCENT: 0.03 → 0.20 (reduce overtrading)
  - AVOID_OPENING_HOUR: False → True (avoid first 15 min whipsaw)
  - MAX trades FNO: 40 → 10 (reduce brokerage bleed)
  - MAX trades EQUITY: 20 → 8
  - BLIND_ENTRY_FALLBACK_PRICE: 250.0 → 0 (disable blind trades)
  - ALLOW_BLIND_START_ENTRIES: True → False
  - MCX stop loss fixed: 0.20% → 2.0%
  - Added ADX_PERIOD, ADX_MIN_THRESHOLD for trend filter
  - Added MIN_ATR_PCT for volatility filter
"""

import os
import json
from datetime import datetime

# =============================================================================
# RISK MANAGEMENT CONFIGURATION
# =============================================================================

RISK_CONFIG = {
    # Daily Limits — realistic, not aspirational
    "MAX_DAILY_LOSS": 5000,             # FIXED: was 10000 but that's too loose
    "DAILY_PROFIT_TARGET": 15000,       # FIXED: was 50000 (unrealistic ₹50k/day)
    # Position Sizing — conservative
    "MAX_POSITION_SIZE_PER_TRADE": 25000,  # FIXED: was 50000
    "DEFAULT_POSITION_SIZE": 15000,        # FIXED: was 25000
    # Stop Loss Configuration
    "EQUITY_STOP_LOSS_PERCENT": 1.0,    # Tight: was 1.5
    "OPTIONS_STOP_LOSS_PERCENT": 40,    # FIXED: was 50% (too loose for weekly options)
    "MCX_STOP_LOSS_PERCENT": 2.0,       # FIXED: was 0.20 (caused near-zero SL)
    # Profit Taking
    "TAKE_PROFIT_PERCENT": 2.0,         # FIXED: was 3.0
    "OPTIONS_TAKE_PROFIT_PERCENT": 80,  # FIXED: was 100% (greedy; take profits earlier)
    "MCX_TAKE_PROFIT_PERCENT": 3.0,     # was 4.0
    # Trailing Stop
    "USE_TRAILING_STOP": True,
    "TRAILING_STOP_PERCENT": 0.75,      # FIXED: was 1.0 (tighter trail)
    # Time-based Exit
    "SQUARE_OFF_TIME": "15:10",
    "ALLOW_TODAY_TRADES_AFTER": "09:30",  # FIXED: was 09:15 — avoid first 15 min
    "AVOID_TRADES_BEFORE": "14:45",       # No new entries after 2:45 PM
    # Brokerage (for net P&L calculation)
    "BROKERAGE_PER_ORDER": 20,          # ₹20 per order (Dhan flat fee)
    "STT_FNO_SELL_PCT": 0.0625,         # 0.0625% STT on F&O sell side
    "EXCHANGE_CHARGES_PCT": 0.002,      # NSE exchange charges
    "SEBI_CHARGES_PCT": 0.0001,         # SEBI turnover fee
    "STAMP_DUTY_PCT": 0.003,            # Stamp duty on buy side
}

# =============================================================================
# SEGMENT-SPECIFIC CONFIGURATION
# =============================================================================

SEGMENT_CONFIGS = {
    "EQUITY": {
        "enabled": True,
        "instruments": [
            "RELIANCE",
            "TCS",
            "INFY",
            "HDFCBANK",
            "ICICIBANK",
            "SBIN",
        ],
        "max_trades_per_day": 8,        # FIXED: was 20 (overtrading)
        "position_size": 30000,         # FIXED: was 60000 (too aggressive)
        "stop_loss_percent": 1.0,
        "take_profit_percent": 2.0,
        "timeframe": "15min",
        "api_interval": "1minute",
    },
    "FNO_OPTIONS": {
        "enabled": True,
        "instruments": {
            "BANKNIFTY": {
                "strike_range": 5,          # ±5 strikes from ATM (was 10)
                "expiry": "weekly",
                "option_type": "CE",
                "lot_size": 15,             # FIXED: was 30. Correct size from Nov 2024
                "max_order_quantity": 30,   # 2 lots max (was 120 = 8 lots!)
            },
            "NIFTY": {
                "strike_range": 5,
                "expiry": "weekly",
                "option_type": "CE",
                "lot_size": 75,             # FIXED: was 65. Correct size from Jul 2024
                "max_order_quantity": 75,   # 1 lot max (was 130!)
            },
        },
        "max_trades_per_day": 10,       # FIXED: was 40 (₹800 brokerage/day guaranteed)
        "position_size": 50000,         # was 140000 (insane concentration)
        "max_order_quantity": 75,       # hard cap
        "stop_loss_percent": 40,        # 40% of premium
        "take_profit_percent": 80,      # 80% (1.8x) profit target (was 100%)
        "api_interval": "1minute",
    },
    "MCX": {
        "enabled": True,
        "instruments": {
            "CRUDEOIL": {
                "exchange": "MCX",
                "lot_size": 100,
                "tick_size": 1,
            },
            "GOLD": {
                "exchange": "MCX",
                "lot_size": 1,
                "tick_size": 1,
            },
        },
        "max_trades_per_day": 6,        # FIXED: was 12
        "position_size": 40000,         # FIXED: was 70000
        "stop_loss_percent": 2.0,       # FIXED: was 0.20 (near-zero stop!)
        "take_profit_percent": 3.0,
        "api_interval": "1minute",
    },
}

# =============================================================================
# STRATEGY PARAMETERS — FIXED
# =============================================================================

STRATEGY_PARAMS = {
    # FIXED: 0.03% momentum was too hair-trigger → 0.20% minimum move required
    "MOMENTUM_ENTRY_PERCENT": 0.20,
    # DISABLED: blind startup trades cause losses when quote unavailable
    "AGGRESSIVE_BOOTSTRAP_TRADES": 0,       # FIXED: was 2
    "FNO_ACCEPTED_ONLY": True,
    "AGGRESSIVE_FORCE_START_LOOPS": 0,      # FIXED: was 4 (forced entries without signal)
    "ALLOW_BLIND_START_ENTRIES": False,     # FIXED: was True — DANGEROUS
    "BLIND_ENTRY_FALLBACK_PRICE": 0.0,      # FIXED: was 250.0 — orders at fake price
    # Trend Following Parameters
    "EMA_FAST": 9,
    "EMA_SLOW": 21,
    "RSI_PERIOD": 14,
    "RSI_OVERBOUGHT": 70,
    "RSI_OVERSOLD": 30,
    "ATR_PERIOD": 14,
    "ATR_MULTIPLIER": 2.0,
    # NEW: ADX filter — only trade when trending
    "USE_ADX_FILTER": True,
    "ADX_PERIOD": 14,
    "ADX_MIN_THRESHOLD": 20,               # Min ADX to allow entry (avoid choppy)
    # NEW: ATR volatility filter — avoid low-volatility traps
    "MIN_ATR_PCT": 0.30,                   # Min ATR as % of price
    "MAX_ATR_PCT": 4.0,                    # Max ATR (avoid extreme volatility)
    # Time filters (IST)
    "NO_ENTRY_BEFORE": "09:30",            # FIXED: was 09:15 (avoid opening whipsaw)
    "NO_ENTRY_AFTER": "14:45",             # No new positions after 2:45 PM
    # Confirmation Indicators
    "USE_MACD": True,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "USE_SUPERTREND": True,
    "SUPERTREND_PERIOD": 10,
    "SUPERTREND_MULTIPLIER": 3,
    # Volume Confirmation
    "MIN_VOLUME_MULTIPLIER": 1.5,
    # Market Hours (IST)
    "MARKET_OPEN": "09:15",
    "MARKET_CLOSE": "15:30",
}

# =============================================================================
# TRADING SESSION CONFIGURATION
# =============================================================================

SESSION_CONFIG = {
    "session_type": "live",
    "broker": "dhan",
    "api_host": os.getenv("HOST_SERVER", "https://algo.endoscopicspinehyderabad.in"),
    "api_key": os.getenv("OPENALGO_API_KEY", os.getenv("BROKER_API_KEY", "490de1b5")),
    "use_websocket": True,
    "websocket_reconnect": True,
    "ORDER_TYPE": "MARKET",
    "PRODUCT_TYPE": "MIS",
    "VALIDITY": "DAY",
    "max_order_retries": 3,
    "retry_delay_seconds": 1,           # FIXED: was 2 seconds (too slow for momentum)
}

# =============================================================================
# FILTERS AND CONDITIONS — FIXED
# =============================================================================

FILTER_CONFIG = {
    "MIN_VOLUME": 500000,
    "MIN_PRICE": 50,
    "MAX_PRICE": 5000,
    "MAX_ATR_PERCENT": 4.0,
    "MIN_ATR_PERCENT": 0.30,
    # FIXED time filters
    "AVOID_OPENING_HOUR": True,         # FIXED: was False — now blocks first 15 min
    "AVOID_CLOSING_HOUR": True,
    "AVOID_OPENING_MINUTES": 15,        # Skip first 15 minutes (9:15–9:30)
    "BEST_TRADING_HOURS": ["09:30-12:00", "14:00-14:45"],  # FIXED: removed late hour
    "MAX_GAP_PERCENT": 2.0,             # FIXED: was 3.0
}

# =============================================================================
# BROKERAGE CALCULATOR
# =============================================================================

def calculate_net_pnl(gross_pnl: float, trade_value: float, segment: str, is_options: bool = False) -> dict:
    """
    Calculate net P&L after all charges.
    Returns breakdown of charges and net P&L.
    """
    brokerage = RISK_CONFIG["BROKERAGE_PER_ORDER"] * 2  # buy + sell

    if is_options or segment == "FNO_OPTIONS":
        stt = trade_value * (RISK_CONFIG["STT_FNO_SELL_PCT"] / 100)
    else:
        stt = 0.0

    exchange_charges = trade_value * (RISK_CONFIG["EXCHANGE_CHARGES_PCT"] / 100)
    sebi_charges = trade_value * (RISK_CONFIG["SEBI_CHARGES_PCT"] / 100)
    stamp_duty = trade_value * (RISK_CONFIG["STAMP_DUTY_PCT"] / 100)

    gst = (brokerage + exchange_charges) * 0.18  # 18% GST on brokerage+exchange

    total_charges = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst
    net_pnl = gross_pnl - total_charges

    return {
        "gross_pnl": round(gross_pnl, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_charges": round(exchange_charges, 2),
        "sebi_charges": round(sebi_charges, 4),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total_charges": round(total_charges, 2),
        "net_pnl": round(net_pnl, 2),
    }


def get_config_summary():
    return {
        "target_profit": f"₹{RISK_CONFIG['DAILY_PROFIT_TARGET']:,}",
        "max_loss": f"₹{RISK_CONFIG['MAX_DAILY_LOSS']:,}",
        "risk_reward_ratio": RISK_CONFIG["DAILY_PROFIT_TARGET"] / RISK_CONFIG["MAX_DAILY_LOSS"],
        "segments": list(SEGMENT_CONFIGS.keys()),
        "broker": SESSION_CONFIG["broker"],
        "mode": SESSION_CONFIG["session_type"],
        "changes_from_original": [
            "BANKNIFTY lot_size: 30 → 15 (NSE Nov 2024)",
            "NIFTY lot_size: 65 → 75 (NSE Jul 2024)",
            "MOMENTUM_ENTRY_PERCENT: 0.03 → 0.20 (reduce overtrading)",
            "AVOID_OPENING_HOUR: False → True (no first-15-min trades)",
            "FNO max_trades: 40 → 10 (reduce brokerage bleed)",
            "Blind entries DISABLED (was causing bad fills)",
            "MCX stop loss: 0.20 → 2.0 (was near-zero)",
            "Added ADX filter (only trade trending markets)",
            "Added brokerage-aware net P&L calculator",
        ],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("OpenAlgo Strategy Configuration (FIXED)")
    print("=" * 60)
    config = get_config_summary()
    print(f"\nTarget Profit: {config['target_profit']}")
    print(f"Max Daily Loss: {config['max_loss']}")
    print(f"Risk:Reward: 1:{config['risk_reward_ratio']:.1f}")
    print(f"\nChanges Applied:")
    for change in config["changes_from_original"]:
        print(f"   - {change}")
    print("\n" + "=" * 60)
