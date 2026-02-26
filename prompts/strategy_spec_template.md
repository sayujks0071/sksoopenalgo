# Strategy Specification (GSD Style)

**Goal**: Create a robust, implementable trading strategy for OpenAlgo.

## 1. Core Concept

* **Strategy Name**: (e.g., `SuperTrend_Pullback`)
* **Instrument**: (e.g., `NSE:NIFTY`, `MCX:GOLD`)
* **Timeframe**: (e.g., `5m`, `15m`, `1h`)
* **Direction**: (Long Only / Short Only / Both)

## 2. Technical Logic (The "What")

### Indicators

* [ ] List all indicators with parameters (e.g., `RSI(14)`, `EMA(200)`)
* [ ] Library to use: `pandas_ta` (Preferred) or custom calculation?

### Entry Conditions

* **Long Entry**:
  * Condition A: (e.g., `Close > EMA(200)`)
  * Condition B: (e.g., `RSI < 30`)
* **Short Entry**:
  * Condition A:
  * Condition B:

### Exit Conditions

* **Take Profit**: (e.g., `1.5%` or `RSI > 70`)
* **Stop Loss**: (e.g., `0.5%` or `Low of last 3 candles`)
* **Time Exit**: (e.g., `Intraday square off at 15:15`)

## 3. Execution & Risk (The "How")

* **Order Type**: Limit / Market / Stop-Limit?
* **Quantity Calculation**:
  * Fixed Qty: (e.g., `50`)
  * Risk-Based: (e.g., `Risk 1% of capital per trade`)
* **Max Trades Per Day**: (e.g., `3`)

## 4. Edge Cases & Safety (The "What If")

* [ ] What if API fails during order placement? -> *Retry 3 times then alert.*
* [ ] What if data feed stops? -> *Check `last_trade_time`, exit if stale > 5 mins.*
* [ ] What if open position exists on restart? -> *Resume management or close immediately?*

## 5. Implementation Plan

* [ ] Dependencies: `strategies/utils/trading_utils.py`
* [ ] Config path: `strategies/strategy_configs.json`
* [ ] Logging: Use standard `logger` from `openalgo`.

---
*Generated using OpenAlgo GSD Template*
