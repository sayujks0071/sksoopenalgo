"""
Strategy Parameter Injector
---------------------------
Dynamically injects parameters into strategy modules for backtesting optimization.
"""
import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ParamInjector")

def load_strategy_module(strategy_name: str):
    """
    Load a strategy module dynamically.
    
    Args:
        strategy_name: Name of strategy (e.g., 'natural_gas_clawdbot', 'crude_oil_enhanced')
    
    Returns:
        Strategy module object
    """
    script_dir = Path(__file__).parent.parent / 'scripts'

    # Map strategy names to file names
    strategy_files = {
        # Current live / dry-run strategies
        'mcx_atr_trend': 'mcx_atr_trend_strategy.py',
        'orb_equity':    'orb_equity_volume.py',
        'vwap_equity':   'vwap_rsi_equity.py',
        'ema_equity':    'ema_supertrend_equity.py',
        # Legacy entries (files may not exist; kept for backwards compatibility)
        'natural_gas_clawdbot': 'natural_gas_clawdbot_strategy.py',
        'crude_oil_enhanced':   'crude_oil_enhanced_strategy.py',
        'crude_oil_clawdbot':   'crude_oil_clawdbot_strategy.py',
        'mcx_clawdbot':         'mcx_clawdbot_strategy.py',
    }

    filename = strategy_files.get(strategy_name)
    if not filename:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    filepath = script_dir / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Strategy file not found: {filepath}")

    # Load module
    spec = importlib.util.spec_from_file_location(f"strategy_{strategy_name}", filepath)
    module = importlib.util.module_from_spec(spec)

    # Add to sys.modules to allow imports within the module
    sys.modules[f"strategy_{strategy_name}"] = module

    spec.loader.exec_module(module)

    return module

def inject_parameters(module, parameters: dict[str, Any]):
    """
    Inject parameters into a strategy module.
    
    Args:
        module: Strategy module object
        parameters: Dictionary of parameter name -> value mappings
    
    Returns:
        Modified module
    """
    # Inject simple parameters (constants)
    for param_name, param_value in parameters.items():
        if param_name.startswith('TIMEFRAME_') or param_name.startswith('TRENDING_') or param_name.startswith('RANGING_'):
            # Handle special cases for dictionaries
            continue
        setattr(module, param_name, param_value)

    # Handle TIMEFRAME_WEIGHTS
    if 'TIMEFRAME_WEIGHTS' in parameters:
        module.TIMEFRAME_WEIGHTS = parameters['TIMEFRAME_WEIGHTS'].copy()

    # Handle TRENDING_WEIGHTS
    if 'TRENDING_WEIGHTS' in parameters:
        module.TRENDING_WEIGHTS = parameters['TRENDING_WEIGHTS'].copy()

    # Handle RANGING_WEIGHTS
    if 'RANGING_WEIGHTS' in parameters:
        module.RANGING_WEIGHTS = parameters['RANGING_WEIGHTS'].copy()

    return module

def prepare_parameters_for_injection(params: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    """
    Prepare parameters dictionary for injection into strategy module.
    Handles normalization of weights and timeframe weights.
    
    Args:
        params: Raw parameters dictionary
        strategy_name: Strategy name
    
    Returns:
        Prepared parameters dictionary
    """
    try:
        from parameter_space import normalize_timeframe_weights, normalize_weights
    except ImportError:
        # Fallback normalization functions
        def normalize_weights(weights):
            total = sum(weights.values())
            return {k: v / total for k, v in weights.items()} if total > 0 else weights
        normalize_timeframe_weights = normalize_weights

    prepared = params.copy()

    # Normalize timeframe weights if provided
    if 'TIMEFRAME_15m' in params or 'TIMEFRAME_5m' in params or 'TIMEFRAME_1h' in params:
        tf_weights = {}
        if 'TIMEFRAME_15m' in params:
            tf_weights['15m'] = params['TIMEFRAME_15m']
        if 'TIMEFRAME_5m' in params:
            tf_weights['5m'] = params['TIMEFRAME_5m']
        if 'TIMEFRAME_1h' in params:
            tf_weights['1h'] = params['TIMEFRAME_1h']

        # Ensure they sum to 1.0
        total = sum(tf_weights.values())
        if total > 0:
            tf_weights = {k: v / total for k, v in tf_weights.items()}
        else:
            # Default weights
            tf_weights = {'5m': 0.25, '15m': 0.50, '1h': 0.25}

        prepared['TIMEFRAME_WEIGHTS'] = tf_weights

        # Remove individual timeframe params
        for key in list(prepared.keys()):
            if key.startswith('TIMEFRAME_'):
                del prepared[key]

    # Normalize trending weights if provided
    if any(k.startswith('TRENDING_') for k in params.keys()):
        trending = {}
        for key, value in params.items():
            if key.startswith('TRENDING_'):
                indicator = key.replace('TRENDING_', '')
                trending[indicator] = value

        if trending:
            # Get default structure from module to fill missing keys
            try:
                module = load_strategy_module(strategy_name)
                default_trending = getattr(module, 'TRENDING_WEIGHTS', {})
                for key in default_trending:
                    if key not in trending:
                        trending[key] = default_trending[key]
            except:
                pass

            prepared['TRENDING_WEIGHTS'] = normalize_weights(trending)

            # Remove individual trending params
            for key in list(prepared.keys()):
                if key.startswith('TRENDING_'):
                    del prepared[key]

    # Normalize ranging weights if provided
    if any(k.startswith('RANGING_') for k in params.keys()):
        ranging = {}
        for key, value in params.items():
            if key.startswith('RANGING_'):
                indicator = key.replace('RANGING_', '')
                ranging[indicator] = value

        if ranging:
            # Get default structure from module
            try:
                module = load_strategy_module(strategy_name)
                default_ranging = getattr(module, 'RANGING_WEIGHTS', {})
                for key in default_ranging:
                    if key not in ranging:
                        ranging[key] = default_ranging[key]
            except:
                pass

            prepared['RANGING_WEIGHTS'] = normalize_weights(ranging)

            # Remove individual ranging params
            for key in list(prepared.keys()):
                if key.startswith('RANGING_'):
                    del prepared[key]

    return prepared

def create_strategy_with_params(strategy_name: str, parameters: dict[str, Any]):
    """
    Create a strategy module instance with injected parameters.
    
    Args:
        strategy_name: Strategy name
        parameters: Parameters to inject
    
    Returns:
        Strategy module with parameters injected
    """
    # Load fresh module
    module = load_strategy_module(strategy_name)

    # Prepare parameters
    prepared_params = prepare_parameters_for_injection(parameters, strategy_name)

    # Inject parameters
    module = inject_parameters(module, prepared_params)

    return module

def get_strategy_symbol(strategy_name: str) -> str:
    """Get the default symbol for a strategy (MCX contracts updated 2026-03-09)."""
    symbol_map = {
        # Live MCX strategies — update before each monthly rollover
        'mcx_atr_trend':      'SILVERM30APR26FUT',   # default; override per instance
        # Live equity strategies
        'orb_equity':         'SBIN',
        'vwap_equity':        'RELIANCE',
        'ema_equity':         'HDFCBANK',
        # Legacy
        'natural_gas_clawdbot': 'NATURALGAS24FEB26FUT',
        'crude_oil_enhanced':   'CRUDEOIL19FEB26FUT',
        'crude_oil_clawdbot':   'CRUDEOIL19FEB26FUT',
        'mcx_clawdbot':         'GOLDM05FEB26FUT',
    }
    return symbol_map.get(strategy_name, 'UNKNOWN')


# ─── BACKTEST ADAPTERS ────────────────────────────────────────────────────────
# These classes provide a unified .run(params) → metrics_dict interface used by
# overnight_optimizer.py.  They translate UPPERCASE optimizer keys to the
# lowercase kwargs that each strategy's native backtest function expects.

class MCXATRTrendBacktestAdapter:
    """
    Wraps MCXATRTrendStrategy.backtest_signal() in a bar-by-bar simulation loop.

    Optimizer keys (UPPERCASE) → strategy constructor kwargs (lowercase):
        EMA_FAST → ema_fast, EMA_SLOW → ema_slow, RSI_BUY → rsi_buy,
        RSI_SELL → rsi_sell, ADX_THRESHOLD → adx_threshold,
        ATR_SL → atr_sl, ATR_TP → atr_tp, TRAIL_ATR → trail_atr

    Returns metrics dict: {sharpe, profit_factor, max_drawdown, win_rate,
                           num_trades, total_return}
    """

    PARAM_MAP: Dict[str, str] = {
        'EMA_FAST':      'ema_fast',
        'EMA_SLOW':      'ema_slow',
        'RSI_BUY':       'rsi_buy',
        'RSI_SELL':      'rsi_sell',
        'ADX_THRESHOLD': 'adx_threshold',
        'ATR_SL':        'atr_sl',
        'ATR_TP':        'atr_tp',
        'TRAIL_ATR':     'trail_atr',
    }

    # Rupees per price-point for each MCX product
    LOT_POINTS: Dict[str, int] = {
        'SILVER':     30,     # 30 kg lot
        'GOLD':       10,     # 10 gm lot (GOLDM mini)
        'CRUDEOIL':   100,    # 100 barrel lot
        'NATURALGAS': 1250,   # 1250 MMBTU lot
    }

    def __init__(self, symbol: str, exchange: str, api_key: str,
                 host: str, capital: float, lot_points: Optional[int] = None):
        self.symbol = symbol
        self.exchange = exchange
        self.api_key = api_key
        self.host = host
        self.capital = capital
        # Auto-detect lot size from symbol name if not provided
        if lot_points is None:
            sym_upper = symbol.upper()
            lot_points = next(
                (v for k, v in self.LOT_POINTS.items() if k in sym_upper), 30
            )
        self.lot_points = lot_points
        self._strategy_cls = None

    def _get_strategy_cls(self):
        if self._strategy_cls is None:
            module = load_strategy_module('mcx_atr_trend')
            self._strategy_cls = getattr(module, 'MCXATRTrendStrategy')
        return self._strategy_cls

    def _translate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {self.PARAM_MAP[k]: v for k, v in params.items() if k in self.PARAM_MAP}

    def _fetch_data(self, days: int = 90):
        """Fetch historical 5-minute bars from OpenAlgo API."""
        import requests
        import pandas as pd
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=days)
        payload = {
            "apikey": self.api_key,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "startdate": start.strftime("%Y-%m-%d"),
            "enddate":   end.strftime("%Y-%m-%d"),
            "interval":  "5m",
        }
        resp = requests.post(f"{self.host}/api/v1/history", json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "data" not in data or not data["data"]:
            raise ValueError(f"Empty history response for {self.symbol}")

        df = pd.DataFrame(data["data"])
        df.columns = [c.lower() for c in df.columns]
        df["datetime"] = pd.to_datetime(df.get("time", df.get("datetime")))
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def run(self, params: Dict[str, Any], days: int = 90) -> Dict[str, Any]:
        """
        Run bar-by-bar backtest and return normalised metrics dict.
        Minimum 5 trades required; otherwise returns zero-quality sentinel.
        """
        import numpy as np

        empty = {'sharpe': 0.0, 'profit_factor': 0.0,
                 'max_drawdown': 99.0, 'win_rate': 0.0, 'num_trades': 0}

        strategy_params = self._translate_params(params)
        cls = self._get_strategy_cls()

        try:
            df = self._fetch_data(days)
        except Exception as exc:
            logger.warning("MCX data fetch failed for %s: %s", self.symbol, exc)
            return empty

        position = None   # None | 'LONG'
        entry_price = 0.0
        trades: list[float] = []
        equity = [self.capital]
        min_bars = 50     # need enough history for indicators

        atr_sl = strategy_params.get('atr_sl', 1.5)
        atr_tp = strategy_params.get('atr_tp', 2.5)

        for i in range(min_bars, len(df)):
            bar_df = df.iloc[: i + 1].copy()
            try:
                signal, _confidence, details = cls.backtest_signal(bar_df, strategy_params)
            except Exception:
                continue

            close = float(df.iloc[i]['close'])

            if position is None and signal == 'BUY':
                position = 'LONG'
                entry_price = close

            elif position == 'LONG':
                atr_val = float(details.get('atr', close * 0.01))
                sl_level = entry_price - atr_sl * atr_val
                tp_level = entry_price + atr_tp * atr_val

                exit_price = None
                if close <= sl_level:
                    exit_price = sl_level
                elif close >= tp_level:
                    exit_price = tp_level
                elif signal == 'SELL':
                    exit_price = close

                if exit_price is not None:
                    pnl = (exit_price - entry_price) * self.lot_points
                    trades.append(pnl)
                    equity.append(equity[-1] + pnl)
                    position = None
                    entry_price = 0.0

        # Force-close any open position at last bar
        if position == 'LONG' and len(df) > 0:
            pnl = (float(df.iloc[-1]['close']) - entry_price) * self.lot_points
            trades.append(pnl)
            equity.append(equity[-1] + pnl)

        if len(trades) < 5:
            return {**empty, 'num_trades': len(trades)}

        arr = np.array(trades, dtype=float)
        wins   = arr[arr > 0]
        losses = arr[arr < 0]

        win_rate       = float(len(wins) / len(arr) * 100)
        gross_loss_abs = float(abs(losses.sum())) if len(losses) else 0.0
        profit_factor  = float(wins.sum() / gross_loss_abs) if gross_loss_abs > 0 else 99.0
        sharpe         = float((arr.mean() / arr.std()) * (252 ** 0.5)) if arr.std() > 0 else 0.0

        eq = np.array(equity, dtype=float)
        rolling_max = np.maximum.accumulate(eq)
        max_dd = float(((rolling_max - eq) / rolling_max * 100).max())

        total_ret = float((equity[-1] - self.capital) / self.capital * 100)

        return {
            'sharpe':         round(sharpe, 4),
            'profit_factor':  round(profit_factor, 4),
            'max_drawdown':   round(max_dd, 4),
            'win_rate':       round(win_rate, 4),
            'num_trades':     len(trades),
            'total_return':   round(total_ret, 4),
        }


class EquityEnvBacktestRunner:
    """
    Wraps each equity strategy's run_backtest() function for optimizer use.

    Translates UPPERCASE optimizer parameter keys to the kwargs expected by
    each equity strategy's run_backtest() signature, then normalises the
    returned dict to the standard metrics schema.

    Normalised output schema (same as MCXATRTrendBacktestAdapter):
        {sharpe, profit_factor, max_drawdown, win_rate, num_trades, total_return}
    """

    # Per-strategy translation maps: UPPERCASE optimizer key → run_backtest kwarg
    PARAM_MAPS: Dict[str, Dict[str, str]] = {
        'vwap_equity': {
            'VWAP_STD_MULT':   'vwap_std_mult',
            'RSI_PERIOD':      'rsi_period',
            'RSI_OVERSOLD':    'rsi_oversold',
            'RSI_OVERBOUGHT':  'rsi_overbought',
            'SL_PCT':          'sl_pct',
            'MAX_HOLD_MIN':    'max_hold_min',
            'MAX_ORDERS_DAY':  'max_orders_day',
            'RISK_PER_TRADE':  'risk_per_trade',
        },
        'orb_equity': {
            'ORB_MINUTES':       'orb_minutes',
            'ORB_BUFFER_PCT':    'buffer_pct',
            'SL_PCT':            'sl_pct',
            'TP_PCT':            'tp_pct',
            'VOLUME_MULTIPLIER': 'volume_mult',
            'VOLUME_LOOKBACK':   'vol_lookback',
            'MAX_ORDERS_DAY':    'max_orders_day',
            'RISK_PER_TRADE':    'risk_per_trade',
        },
        'ema_equity': {
            'FAST_EMA':          'fast_ema',
            'SLOW_EMA':          'slow_ema',
            'SUPERTREND_PERIOD': 'st_period',
            'SUPERTREND_MULT':   'st_mult',
            'ATR_PERIOD':        'atr_period',
            'ATR_SL_MULT':       'atr_sl_mult',
            'ATR_TP_MULT':       'atr_tp_mult',
            'ADX_MIN':           'adx_min',
            'MAX_ORDERS_DAY':    'max_orders_day',
            'RISK_PER_TRADE':    'risk_per_trade',
        },
    }

    def __init__(self, strategy_name: str, symbol: str, exchange: str,
                 api_key: str, host: str, capital: float, days: int = 90):
        if strategy_name not in self.PARAM_MAPS:
            raise ValueError(f"Unknown equity strategy: {strategy_name}")
        self.strategy_name = strategy_name
        self.symbol   = symbol
        self.exchange = exchange
        self.api_key  = api_key
        self.host     = host
        self.capital  = capital
        self.days     = days
        self._run_backtest_fn = None

    def _get_run_backtest(self):
        if self._run_backtest_fn is None:
            module = load_strategy_module(self.strategy_name)
            self._run_backtest_fn = getattr(module, 'run_backtest')
        return self._run_backtest_fn

    def _translate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        pmap = self.PARAM_MAPS[self.strategy_name]
        return {pmap[k]: v for k, v in params.items() if k in pmap}

    def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the native run_backtest() and normalise the result dict.
        Equity scripts return {win_rate, profit_factor, max_drawdown_pct, total_trades}.
        Sharpe is estimated via the Bernoulli approximation:
            sharpe ≈ 2 * (WR − 0.5) * sqrt(N)
        which is exact for binary win/loss outcomes and a good proxy otherwise.
        """
        import math

        empty = {'sharpe': 0.0, 'profit_factor': 0.0,
                 'max_drawdown': 99.0, 'win_rate': 0.0, 'num_trades': 0}

        fn = self._get_run_backtest()
        kwargs = self._translate_params(params)

        try:
            result = fn(
                symbol   = self.symbol,
                exchange = self.exchange,
                api_key  = self.api_key,
                host     = self.host,
                days     = self.days,
                capital  = self.capital,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("Equity backtest failed for %s: %s", self.strategy_name, exc)
            return empty

        status = result.get('status', 'error')
        if status != 'success':
            return {**empty, 'num_trades': result.get('total_trades', 0)}

        n         = result.get('total_trades', 0)
        win_rate  = float(result.get('win_rate', 0.0))
        pf        = float(result.get('profit_factor', 0.0))
        max_dd    = float(result.get('max_drawdown_pct', 99.0))
        net_pnl   = float(result.get('net_pnl', 0.0))

        # Bernoulli Sharpe approximation
        wr_frac = win_rate / 100.0
        sharpe = 2.0 * (wr_frac - 0.5) * math.sqrt(max(n, 1))

        total_ret = net_pnl / self.capital * 100.0 if self.capital > 0 else 0.0

        return {
            'sharpe':        round(sharpe, 4),
            'profit_factor': round(pf, 4),
            'max_drawdown':  round(max_dd, 4),
            'win_rate':      round(win_rate, 4),
            'num_trades':    n,
            'total_return':  round(total_ret, 4),
        }


def create_backtest_runner(
    strategy_name: str,
    symbol: str,
    exchange: str,
    api_key: str,
    host: str,
    capital: float,
    days: int = 90,
):
    """
    Factory: return the correct backtest runner for *strategy_name*.

    MCX ATR Trend  → MCXATRTrendBacktestAdapter
    Equity scripts → EquityEnvBacktestRunner

    Usage::

        runner = create_backtest_runner('vwap_equity', 'RELIANCE', 'NSE', ...)
        metrics = runner.run({'VWAP_STD_MULT': 1.5, 'RSI_PERIOD': 14, ...})
        # metrics = {sharpe, profit_factor, max_drawdown, win_rate, num_trades, ...}
    """
    if strategy_name == 'mcx_atr_trend':
        return MCXATRTrendBacktestAdapter(
            symbol=symbol, exchange=exchange,
            api_key=api_key, host=host, capital=capital,
        )
    if strategy_name in EquityEnvBacktestRunner.PARAM_MAPS:
        return EquityEnvBacktestRunner(
            strategy_name=strategy_name,
            symbol=symbol, exchange=exchange,
            api_key=api_key, host=host, capital=capital, days=days,
        )
    raise ValueError(
        f"No backtest runner registered for strategy '{strategy_name}'. "
        f"Known: mcx_atr_trend, {', '.join(EquityEnvBacktestRunner.PARAM_MAPS)}"
    )
