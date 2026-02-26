# Premium Strategies Report – VectorBT Backtest

**Goal:** 10 premium strategies with potential to support a **₹1,00,000/day** profit target.  
**Tool:** [VectorBT](https://github.com/polakowo/vectorbt) (lightning-fast backtesting).  
**Context:** [antidhan](https://github.com/sayujks0071/antidhan) / OpenAlgo strategies; backtest with VectorBT to keep good ones and add open-source strategies where needed.

---

## 1. How It Works

1. **Backtest runner**  
   `scripts/vectorbt_premium_strategies.py` runs multiple strategies (EMA crossover, SMA crossover, RSI reversal, MACD crossover, Bollinger mean reversion) across NSE/MCX symbols using VectorBT.

2. **Data**  
   - Prefer **OpenAlgo history API** (`--host`, API key) for 15m/intraday.  
   - Optional **yfinance** fallback (`--use-yf`) for NSE equities (daily only).

3. **Premium criteria** (all must pass)  
   - Sharpe ratio ≥ 0.5  
   - Max drawdown ≤ 20%  
   - Min 5 trades  
   - Net profit > 0  

4. **Selection**  
   Strategies are scored (Sharpe, return, drawdown, trade count). Top 10 **unique (strategy + symbol)** are chosen as “premium”.

5. **₹1L/day**  
   - Backtest gives **average daily PnL** over the test window.  
   - “Potential for 1L/day” = scaling (capital + leverage) so that **sum of top 10 strategies’ projected daily PnL** reaches ₹1,00,000.  
   - This is an **extrapolation from backtest**, not a guarantee of future results.

---

## 2. Running the Backtest

```bash
# From repo root. Use a virtual environment (recommended):
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r scripts/requirements-backtest.txt

# With OpenAlgo API (best: 15m data)
export OPENALGO_API_KEY=your_key
python scripts/vectorbt_premium_strategies.py --host http://127.0.0.1:5002 --days 90 --top 10

# Without API: use yfinance for NSE daily data only
python scripts/vectorbt_premium_strategies.py --use-yf --days 90 --top 10

# Output: log/vectorbt_premium_strategies_report.json
```

Optional:

- `--use-yf` – use yfinance for NSE (daily data).
- `--init-cash 100000` – capital per run (default 1L).
- `--out path/to/report.json` – custom report path.
- `--top 10` – number of premium strategies to keep (default 10).

---

## 3. Strategies Included (VectorBT + Open Source Style)

| Strategy           | Type        | Logic (short)                          | Source / style        |
|--------------------|------------|----------------------------------------|------------------------|
| EMA_Crossover      | Trend      | Fast EMA crosses above Slow EMA        | VectorBT MA.run        |
| SMA_Crossover      | Trend      | Fast SMA above Slow SMA                | VectorBT MA.run        |
| RSI_Reversal       | Mean rev   | Buy oversold (RSI &lt; 30), sell overbought (70) | VectorBT RSI.run       |
| MACD_Crossover     | Momentum   | MACD crosses above signal line         | VectorBT MACD.run      |
| Bollinger_MeanRev  | Mean rev   | Buy at lower band, sell at upper       | VectorBT BBANDS.run    |

Existing **antidhan/OpenAlgo** strategies (e.g. SuperTrend VWAP, MCX momentum, AI hybrid) are in the codebase; the VectorBT runner adds **these** indicator-based strategies so you get a single ranking and can keep or replace by comparing results.

---

## 4. Path to ₹1,00,000/Day (Conceptual)

- Backtest reports **total_daily_profit_avg_projectation** = sum of average daily PnL of the top 10 (strategy + symbol) over the test period.  
- To approach **₹1,00,000/day**:
  - Increase **capital** (e.g. higher `--init-cash` or multiple lots).  
  - Run more **symbols** and/or **timeframes** (e.g. 15m + 1h).  
  - Add more **strategies** (from open source or your own) and re-run the same script.  
- **Important:** Past backtest performance does not guarantee future results. Slippage, costs, and regime change can reduce live PnL. Use strict risk limits (e.g. max daily loss, position caps) in production.

---

## 5. Report JSON (Summary)

- `top_premium_strategies`: list of `{ strategy_name, symbol, exchange, params, total_return_pct, max_drawdown_pct, sharpe, trades, net_profit, daily_profit_avg, ... }`.  
- `total_daily_profit_avg_projectation`: sum of `daily_profit_avg` of top strategies.  
- `target_daily_profit_inr`: 100000.  
- `premium_criteria`: min Sharpe, max drawdown %, min trades.

Use this file to:
- See which (strategy, symbol) combos are “premium”.  
- Compare with existing antidhan strategies and decide what to keep or replace.  
- Scale capital/leverage for a 1L/day target with full awareness of risk.

---

## 6. Adding More Strategies (Open Source / Custom)

To add another strategy:

1. In `vectorbt_premium_strategies.py`, implement a function that takes `close` (and optional params) and returns `(entries, exits)` (boolean Series).  
2. Register it in `STRATEGY_REGISTRY` with a name and default param list.  
3. Re-run the script; the new strategy will be included in ranking and can enter the top 10.

Examples you can encode similarly (conceptually from open-source/VectorBT style):

- Donchian breakout (e.g. close &gt; rolling max).  
- Keltner + ADX trend filter.  
- Stochastic + MACD.  
- More MA/RSI/MACD/BB parameter sets.

---

## 7. Disclaimer

**This software is for educational and research purposes. Trading involves risk. Do not risk capital you cannot afford to lose. Backtest results do not guarantee future performance.** The “₹1,00,000/day” figure is a target based on backtest extrapolation; actual results will depend on markets, execution, and risk management.
