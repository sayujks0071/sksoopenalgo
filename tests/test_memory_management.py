import asyncio
import json
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "openalgo"))

from openalgo.utils import health_monitor, memory_utils


def test_cognee_manager_local_fallback_persists_and_limits_results(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_utils, "_MAX_LOCAL_ENTRIES", 3)
    monkeypatch.setattr(memory_utils, "_MAX_RESULTS", 2)

    manager = memory_utils.CogneeManager(
        user_id="trader-a", storage_path=str(tmp_path / "trade_memory.jsonl")
    )
    manager.enabled = False

    async def scenario():
        await manager.add_memory("Bought NIFTY because RSI was oversold and breadth improved.")
        await manager.add_memory("Sold BANKNIFTY after VWAP rejection.")
        await manager.add_memory("Added FINNIFTY trade on MACD crossover.")
        await manager.add_memory("Trimmed NIFTY risk when RSI normalized.")

        results = await manager.search_memory("NIFTY RSI")
        context = await manager.get_trading_context("NIFTY", {"RSI": 28, "Trend": "up"})
        return results, context

    results, context = asyncio.run(scenario())

    with open(manager.storage_path) as handle:
        stored_lines = [line for line in handle if line.strip()]

    assert len(stored_lines) == 3
    assert len(results) <= 2
    assert all(result["source"] == "local" for result in results)
    assert "Relevant past notes:" in context
    assert "NIFTY" in context


def test_get_memory_metrics_includes_system_pressure(monkeypatch):
    class FakeProcess:
        def memory_info(self):
            return SimpleNamespace(rss=600 * 1024 * 1024, vms=900 * 1024 * 1024)

        def memory_percent(self):
            return 12.5

    alerts = []

    monkeypatch.setattr(health_monitor.psutil, "Process", lambda pid: FakeProcess())
    monkeypatch.setattr(
        health_monitor.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024**3, available=700 * 1024 * 1024),
    )
    monkeypatch.setattr(
        health_monitor.psutil,
        "swap_memory",
        lambda: SimpleNamespace(used=128 * 1024 * 1024),
    )
    monkeypatch.setattr(health_monitor, "_read_cgroup_memory_limit_mb", lambda: 700.0)
    monkeypatch.setattr(
        health_monitor.HealthAlert,
        "create_alert",
        lambda **kwargs: alerts.append(kwargs),
    )
    monkeypatch.setattr(
        health_monitor.HealthAlert,
        "auto_resolve_alerts",
        lambda *args, **kwargs: None,
    )

    metrics = health_monitor.get_memory_metrics()

    assert metrics["status"] == "fail"
    assert metrics["limit_mb"] == 700.0
    assert metrics["limit_percent"] > 80
    assert any("system available memory" in reason for reason in metrics["reasons"])
    assert alerts and alerts[0]["severity"] == "fail"
