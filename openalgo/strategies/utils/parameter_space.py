"""
Parameter Space Definitions for Strategy Optimization
------------------------------------------------------
Defines parameter ranges and constraints for optimizing MCX strategies.
"""
from typing import Any, Dict, List, Tuple

import numpy as np

# Parameter space definitions for each strategy
PARAMETER_SPACES = {
    'natural_gas_clawdbot': {
        'indicator_periods': {
            'RSI_PERIOD': [10, 12, 14, 16, 18],
            'MACD_FAST': [10, 12, 14],
            'MACD_SLOW': [24, 26, 28],
            'MACD_SIGNAL': [7, 9, 11],
            'ADX_PERIOD': [12, 14, 16],
            'ATR_PERIOD': [12, 14, 16],
            'BB_PERIOD': [18, 20, 22],
            'BB_STD': [1.8, 2.0, 2.2],
            'EMA_FAST': [7, 9, 11],
            'EMA_SLOW': [19, 21, 23],
            'EMA_LONG': [45, 50, 55],
            'VWAP_PERIOD': [18, 20, 22]
        },
        'entry_thresholds': {
            'BASE_ENTRY_THRESHOLD': [50, 55, 60, 65, 70],
            'MIN_ENTRY_THRESHOLD': [45, 50, 55],
            'MAX_ENTRY_THRESHOLD': [70, 75, 80],
            'ADX_ADAPTIVE_FACTOR': [0.3, 0.4, 0.5],
            'AI_CONFIDENCE_MULTIPLIER': [0.15, 0.20, 0.25]
        },
        'risk_management': {
            'ATR_SL_MULTIPLIER': [2.0, 2.5, 3.0],
            'ATR_TP_MULTIPLIER': [3.5, 4.0, 4.5, 5.0],
            'TRAILING_STOP_ATR': [1.0, 1.5, 2.0],
            'BREAKEVEN_ATR': [1.0, 1.5, 2.0]
        },
        'timeframe_weights': {
            '5m': [0.20, 0.25, 0.30, 0.35],
            '15m': [0.40, 0.50, 0.60, 0.70],
            '1h': [0.10, 0.15, 0.20, 0.25]
        },
        'trending_weights': {
            'MACD': [0.20, 0.25, 0.30],
            'ADX': [0.20, 0.25, 0.30],
            'RSI': [0.10, 0.15, 0.20],
            'BOLLINGER': [0.10, 0.15, 0.20],
            'EMA_CROSS': [0.08, 0.10, 0.12],
            'VOLUME': [0.08, 0.10, 0.12],
            'VWAP': [0.00, 0.05]
        },
        'ranging_weights': {
            'RSI': [0.25, 0.30, 0.35],
            'BOLLINGER': [0.25, 0.30, 0.35],
            'VOLUME': [0.15, 0.20, 0.25],
            'VWAP': [0.08, 0.10, 0.12],
            'EMA_CROSS': [0.03, 0.05, 0.07],
            'MACD': [0.03, 0.05, 0.07]
        },
        'position_sizing': {
            'BASE_QUANTITY': [1],
            'MAX_POSITION_SIZE': [2],
            'RISK_PER_TRADE_PCT': [1.0, 1.5, 2.0]
        }
    },
    'crude_oil_enhanced': {
        'indicator_periods': {
            'RSI_PERIOD': [10, 12, 14, 16, 18],
            'MACD_FAST': [10, 12, 14],
            'MACD_SLOW': [24, 26, 28],
            'MACD_SIGNAL': [7, 9, 11],
            'ADX_PERIOD': [12, 14, 16],
            'ATR_PERIOD': [12, 14, 16],
            'BB_PERIOD': [18, 20, 22],
            'BB_STD': [1.8, 2.0, 2.2],
            'EMA_FAST': [7, 9, 11],
            'EMA_SLOW': [19, 21, 23],
            'EMA_LONG': [45, 50, 55],
            'VWAP_PERIOD': [18, 20, 22]
        },
        'entry_thresholds': {
            'BASE_ENTRY_THRESHOLD': [50, 55, 58, 60, 65],
            'MIN_ENTRY_THRESHOLD': [45, 48, 50],
            'MAX_ENTRY_THRESHOLD': [68, 72, 75],
            'ADX_ADAPTIVE_FACTOR': [0.30, 0.35, 0.40],
            'AI_CONFIDENCE_MULTIPLIER': [0.15, 0.18, 0.20]
        },
        'risk_management': {
            'ATR_SL_MULTIPLIER': [1.5, 1.8, 2.0, 2.5],
            'ATR_TP_MULTIPLIER': [2.5, 3.0, 3.5, 4.0],
            'TRAILING_STOP_ATR': [1.0, 1.2, 1.5],
            'BREAKEVEN_ATR': [1.0, 1.2, 1.5]
        },
        'timeframe_weights': {
            '5m': [0.15, 0.20, 0.25],
            '15m': [0.50, 0.60, 0.70],
            '1h': [0.10, 0.15, 0.20]
        },
        'trending_weights': {
            'MACD': [0.25, 0.30, 0.35],
            'ADX': [0.18, 0.20, 0.22],
            'RSI': [0.12, 0.15, 0.18],
            'BOLLINGER': [0.12, 0.15, 0.18],
            'EMA_CROSS': [0.10, 0.12, 0.14],
            'VOLUME': [0.06, 0.08, 0.10],
            'VWAP': [0.00]
        },
        'ranging_weights': {
            'RSI': [0.25, 0.30, 0.35],
            'BOLLINGER': [0.25, 0.30, 0.35],
            'VOLUME': [0.15, 0.20, 0.25],
            'VWAP': [0.08, 0.10, 0.12],
            'EMA_CROSS': [0.03, 0.05, 0.07],
            'MACD': [0.03, 0.05, 0.07]
        },
        'position_sizing': {
            'BASE_QUANTITY': [1],
            'MAX_POSITION_SIZE': [2],
            'RISK_PER_TRADE_PCT': [1.0, 1.5, 2.0]
        }
    }
}

# ─────────────────────────────────────────────────────────────
# Live strategy parameter spaces (as of 2026-03-09)
# ─────────────────────────────────────────────────────────────

# MCX ATR Trend — parameters map to argparse flags in mcx_atr_trend_strategy.py
# All env-var names are the long-flag names uppercased with hyphens → underscores
PARAMETER_SPACES['mcx_atr_trend'] = {
    'indicator_periods': {
        'EMA_FAST':  [7, 9, 11, 13],
        'EMA_SLOW':  [17, 21, 25, 30],
        'ADX_PERIOD': [12, 14, 16],      # ADX computed internally; threshold tunable
    },
    'entry_thresholds': {
        'RSI_BUY':       [50.0, 55.0, 60.0],
        'RSI_SELL':      [40.0, 45.0, 50.0],
        'ADX_THRESHOLD': [20.0, 25.0, 30.0, 35.0],
    },
    'risk_management': {
        'ATR_SL':        [1.0, 1.5, 2.0, 2.5],
        'ATR_TP':        [2.0, 2.5, 3.0, 3.5, 4.0],
        'TRAIL_ATR':     [0.0, 0.5, 1.0, 1.5],    # 0 = disabled
        'TRAIL_ATR_SHORT': [0.0, 0.5, 1.0],
    },
    'trade_management': {
        'COOLDOWN_MINUTES':    [3, 5, 8, 10],
        'MAX_TRADES_PER_DAY':  [4, 6, 8],
    },
}

# ORB Equity — parameters map to env-vars in orb_equity_volume.py
PARAMETER_SPACES['orb_equity'] = {
    'orb_params': {
        'ORB_MINUTES':    [15, 20, 30, 45],
        'ORB_BUFFER_PCT': [0.05, 0.10, 0.15, 0.20],
    },
    'risk_management': {
        'SL_PCT':   [0.3, 0.4, 0.5, 0.6, 0.7],
        'TP_PCT':   [1.0, 1.2, 1.5, 1.8, 2.0, 2.5],
        'MAX_HOLD_MIN': [60, 75, 90, 105, 120],
    },
    'volume_filter': {
        'VOLUME_MULTIPLIER': [1.3, 1.5, 1.7, 2.0, 2.5],
        'VOLUME_LOOKBACK':   [10, 15, 20, 25],
    },
    'gap_filter': {
        'GAP_THRESHOLD_PCT': [0.10, 0.15, 0.20, 0.25],
    },
}

# VWAP RSI Equity — parameters map to env-vars in vwap_rsi_equity.py
PARAMETER_SPACES['vwap_equity'] = {
    'indicator_periods': {
        'VWAP_STD_MULT':   [1.0, 1.25, 1.5, 1.75, 2.0],
        'VWAP_STD_WINDOW': [10, 15, 20, 25, 30],
        'RSI_PERIOD':      [10, 12, 14, 16, 20],
    },
    'entry_thresholds': {
        'RSI_OVERSOLD':    [25.0, 28.0, 30.0, 32.0, 35.0],
        'RSI_OVERBOUGHT':  [65.0, 68.0, 70.0, 72.0, 75.0],
    },
    'risk_management': {
        'SL_PCT':      [0.25, 0.30, 0.35, 0.40, 0.50],
        'MAX_HOLD_MIN': [45, 60, 75, 90],
    },
}

# EMA Supertrend Equity — parameters map to env-vars in ema_supertrend_equity.py
PARAMETER_SPACES['ema_equity'] = {
    'indicator_periods': {
        'FAST_EMA':         [3, 5, 7, 9],
        'SLOW_EMA':         [10, 13, 17, 21],
        'SUPERTREND_PERIOD': [7, 10, 14],
        'SUPERTREND_MULT':  [1.5, 2.0, 2.5, 3.0, 3.5],
        'ATR_PERIOD':       [10, 12, 14, 16],
    },
    'risk_management': {
        'ATR_SL_MULT': [1.0, 1.25, 1.5, 1.75, 2.0],
        'ATR_TP_MULT': [2.0, 2.5, 3.0, 3.5, 4.0],
        'ADX_MIN':     [0, 15.0, 20.0, 25.0],
    },
}

# Key parameters for grid search (reduced search space)
GRID_SEARCH_PARAMS = {
    'natural_gas_clawdbot': {
        'BASE_ENTRY_THRESHOLD': [50, 55, 60, 65, 70],
        'MIN_ENTRY_THRESHOLD': [45, 50, 55],
        'ATR_SL_MULTIPLIER': [2.0, 2.5, 3.0],
        'ATR_TP_MULTIPLIER': [3.5, 4.0, 4.5, 5.0],
        'TIMEFRAME_15m': [0.40, 0.50, 0.60, 0.70],
        'ADX_ADAPTIVE_FACTOR': [0.3, 0.4, 0.5]
    },
    'crude_oil_enhanced': {
        'BASE_ENTRY_THRESHOLD': [50, 55, 58, 60, 65],
        'MIN_ENTRY_THRESHOLD': [45, 48, 50],
        'ATR_SL_MULTIPLIER': [1.5, 1.8, 2.0, 2.5],
        'ATR_TP_MULTIPLIER': [2.5, 3.0, 3.5, 4.0],
        'TIMEFRAME_15m': [0.50, 0.60, 0.70],
        'ADX_ADAPTIVE_FACTOR': [0.30, 0.35, 0.40]
    },
    # ── Live strategy grid params (high-impact subset for ≤120 evaluations) ──
    'mcx_atr_trend': {
        # Trend filter — most sensitivity here
        'ADX_THRESHOLD': [20.0, 25.0, 30.0],
        # Risk/reward ratio drives PF most
        'ATR_SL': [1.0, 1.5, 2.0],
        'ATR_TP': [2.5, 3.0, 3.5, 4.0],
        # EMA crossover speed
        'EMA_FAST': [7, 9, 11],
        'EMA_SLOW': [19, 21, 25],
    },
    'orb_equity': {
        # ORB window width has huge effect on signal quality
        'ORB_MINUTES': [15, 20, 30],
        'ORB_BUFFER_PCT': [0.05, 0.10, 0.15],
        # Risk/reward
        'SL_PCT': [0.3, 0.5, 0.7],
        'TP_PCT': [1.0, 1.5, 2.0],
        # Volume filter quality
        'VOLUME_MULTIPLIER': [1.5, 1.7, 2.0],
    },
    'vwap_equity': {
        # VWAP band width drives entry selectivity
        'VWAP_STD_MULT': [1.0, 1.5, 2.0],
        # RSI filter tightness
        'RSI_OVERSOLD': [25.0, 30.0, 35.0],
        'RSI_OVERBOUGHT': [65.0, 70.0, 75.0],
        # Stop loss
        'SL_PCT': [0.25, 0.35, 0.50],
        # Max hold (mean-reversion: shorter = tighter)
        'MAX_HOLD_MIN': [45, 60, 90],
    },
    'ema_equity': {
        # EMA crossover speeds
        'FAST_EMA': [3, 5, 7],
        'SLOW_EMA': [10, 13, 17],
        # SuperTrend multiplier (lower = more signals, higher = more selective)
        'SUPERTREND_MULT': [1.5, 2.0, 2.5, 3.0],
        # Risk/reward via ATR
        'ATR_SL_MULT': [1.0, 1.5, 2.0],
        'ATR_TP_MULT': [2.5, 3.0, 3.5],
        # ADX filter (0 = disabled)
        'ADX_MIN': [0, 20.0, 25.0],
    },
}

def get_parameter_ranges(strategy_name: str) -> dict[str, dict[str, list]]:
    """Get parameter ranges for a strategy"""
    return PARAMETER_SPACES.get(strategy_name, {})

def get_grid_search_params(strategy_name: str) -> dict[str, list]:
    """Get key parameters for grid search"""
    return GRID_SEARCH_PARAMS.get(strategy_name, {})

def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalize weights to sum to 1.0"""
    total = sum(weights.values())
    if total == 0:
        return weights
    return {k: v / total for k, v in weights.items()}

def normalize_timeframe_weights(weights: dict[str, float]) -> dict[str, float]:
    """Normalize timeframe weights to sum to 1.0"""
    return normalize_weights(weights)

def get_continuous_ranges(strategy_name: str) -> dict[str, tuple[float, float]]:
    """Get continuous parameter ranges for Bayesian optimization"""
    spaces = {
        'natural_gas_clawdbot': {
            'RSI_PERIOD': (10, 18),
            'MACD_FAST': (10, 14),
            'MACD_SLOW': (24, 28),
            'ADX_PERIOD': (12, 16),
            'BASE_ENTRY_THRESHOLD': (50, 70),
            'MIN_ENTRY_THRESHOLD': (45, 55),
            'MAX_ENTRY_THRESHOLD': (70, 80),
            'ADX_ADAPTIVE_FACTOR': (0.3, 0.5),
            'ATR_SL_MULTIPLIER': (2.0, 3.0),
            'ATR_TP_MULTIPLIER': (3.5, 5.0),
            'TIMEFRAME_15m': (0.40, 0.70),
            'TIMEFRAME_5m': (0.20, 0.40),
            'TIMEFRAME_1h': (0.10, 0.30),
            'TRENDING_MACD': (0.20, 0.30),
            'TRENDING_ADX': (0.20, 0.30),
            'TRENDING_RSI': (0.10, 0.20)
        },
        'crude_oil_enhanced': {
            'RSI_PERIOD': (10, 18),
            'MACD_FAST': (10, 14),
            'MACD_SLOW': (24, 28),
            'ADX_PERIOD': (12, 16),
            'BASE_ENTRY_THRESHOLD': (50, 65),
            'MIN_ENTRY_THRESHOLD': (45, 50),
            'MAX_ENTRY_THRESHOLD': (68, 75),
            'ADX_ADAPTIVE_FACTOR': (0.30, 0.40),
            'ATR_SL_MULTIPLIER': (1.5, 2.5),
            'ATR_TP_MULTIPLIER': (2.5, 4.0),
            'TIMEFRAME_15m': (0.50, 0.70),
            'TIMEFRAME_5m': (0.15, 0.25),
            'TIMEFRAME_1h': (0.10, 0.20),
            'TRENDING_MACD': (0.25, 0.35),
            'TRENDING_ADX': (0.18, 0.22),
            'TRENDING_RSI': (0.12, 0.18)
        },
        # ── Live strategies (Bayesian uses continuous ranges) ─────────────
        # MCX ATR Trend — argparse flags; int params cast to int at inject time
        'mcx_atr_trend': {
            'EMA_FAST':       (7.0, 13.0),    # → int
            'EMA_SLOW':       (17.0, 30.0),   # → int; constrained EMA_SLOW > EMA_FAST+6
            'RSI_BUY':        (50.0, 65.0),
            'RSI_SELL':       (35.0, 50.0),
            'ADX_THRESHOLD':  (18.0, 35.0),
            'ATR_SL':         (0.8, 2.5),
            'ATR_TP':         (2.0, 4.5),     # constrained ATR_TP > ATR_SL*1.5
            'TRAIL_ATR':      (0.0, 2.0),      # 0 = disabled
            'COOLDOWN_MINUTES': (3.0, 12.0),  # → int
            'MAX_TRADES_PER_DAY': (4.0, 8.0), # → int
        },
        # ORB Equity — env-var names
        'orb_equity': {
            'ORB_MINUTES':      (10.0, 45.0),  # → int
            'ORB_BUFFER_PCT':   (0.05, 0.25),
            'SL_PCT':           (0.25, 0.80),
            'TP_PCT':           (0.80, 2.50),  # constrained TP_PCT > SL_PCT*2
            'MAX_HOLD_MIN':     (45.0, 120.0), # → int
            'VOLUME_MULTIPLIER': (1.2, 2.8),
            'VOLUME_LOOKBACK':  (10.0, 25.0),  # → int
            'GAP_THRESHOLD_PCT': (0.08, 0.25),
        },
        # VWAP RSI Equity — env-var names
        'vwap_equity': {
            'VWAP_STD_MULT':   (0.8, 2.5),
            'VWAP_STD_WINDOW': (10.0, 30.0),  # → int
            'RSI_PERIOD':      (10.0, 20.0),  # → int
            'RSI_OVERSOLD':    (20.0, 38.0),
            'RSI_OVERBOUGHT':  (62.0, 80.0),  # constrained > 100-RSI_OVERSOLD
            'SL_PCT':          (0.20, 0.60),
            'MAX_HOLD_MIN':    (30.0, 90.0),  # → int
        },
        # EMA SuperTrend Equity — env-var names
        'ema_equity': {
            'FAST_EMA':         (3.0, 9.0),    # → int
            'SLOW_EMA':         (9.0, 25.0),   # → int; constrained > FAST_EMA+4
            'SUPERTREND_PERIOD': (7.0, 16.0),  # → int
            'SUPERTREND_MULT':  (1.2, 4.0),
            'ATR_PERIOD':       (10.0, 18.0),  # → int
            'ATR_SL_MULT':      (0.8, 2.2),
            'ATR_TP_MULT':      (1.8, 4.5),    # constrained > ATR_SL_MULT*1.5
            'ADX_MIN':          (0.0, 30.0),   # 0-10 effectively = disabled
        },
    }
    return spaces.get(strategy_name, {})
