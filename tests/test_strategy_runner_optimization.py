import sys
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest


repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "openalgo"))
strategy_runner_path = repo_root / "strategies" / "strategy_runner.py"
spec = importlib.util.spec_from_file_location("strategy_runner_under_test", strategy_runner_path)
strategy_runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(strategy_runner)
TradingSession = strategy_runner.TradingSession


def build_session(segment="FNO_OPTIONS"):
    session = TradingSession.__new__(TradingSession)
    session.segment = segment
    session.client = MagicMock()
    session.dhan_data = None
    session.direct_quotes_only = False
    session._openalgo_quote_skip_until = 0.0
    session._openalgo_quote_failures = 0
    session._dhan_fallback_logged = set()
    session.last_symbol_prices = {}
    session.broker_snapshot_ttl_sec = 60.0
    session._positionbook_cache = None
    session._positionbook_cache_ts = 0.0
    session._orderbook_cache = None
    session._orderbook_cache_ts = 0.0
    session.daily_pnl = 0.0
    return session


def test_update_pnl_from_broker_positions_uses_batch_quotes():
    session = build_session()
    session.client.positionbook.return_value = {
        "data": [
            {"symbol": "BANKNIFTY123CE", "exchange": "NFO", "quantity": 1, "average_price": 100},
            {"symbol": "BANKNIFTY123PE", "exchange": "NFO", "quantity": -1, "average_price": 80},
        ]
    }
    session.client.get_batch_quotes.return_value = {
        "BANKNIFTY123CE": {"ltp": 112},
        "BANKNIFTY123PE": {"ltp": 70},
    }
    session.update_pnl_from_dhan_raw_positions = MagicMock(return_value=None)

    pnl = TradingSession.update_pnl_from_broker_positions(session)

    assert pnl == pytest.approx(22.0)
    assert session.client.positionbook.call_count == 1
    session.client.get_batch_quotes.assert_called_once_with(
        ["BANKNIFTY123CE", "BANKNIFTY123PE"], exchange="NFO"
    )


def test_positionbook_cache_reused_within_ttl():
    session = build_session()
    session.client.positionbook.return_value = {
        "data": [
            {"symbol": "CRUDEOILM26", "exchange": "MCX", "quantity": 2},
        ]
    }

    qty = TradingSession.get_broker_position_qty(session, "CRUDEOILM26")
    has_position = TradingSession.has_broker_open_position(session, "CRUDEOILM26")

    assert qty == 2
    assert has_position is True
    assert session.client.positionbook.call_count == 1


def test_batch_quote_normalization_accepts_exchange_prefixed_keys():
    session = build_session(segment="MCX")
    session.client.get_batch_quotes.return_value = {
        "MCX:CRUDEOILM26": {"ltp": 6201.5},
    }

    quote_map = TradingSession.get_quotes_batch_with_fallback(
        session,
        [{"symbol": "CRUDEOILM26", "exchange": "MCX"}],
        max_retries=0,
    )

    assert quote_map == {"MCX:CRUDEOILM26": {"ltp": 6201.5}}
