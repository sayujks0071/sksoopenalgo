# Iron Condor Strategy — Backtest Findings (2026-03-03)

## Conclusion: PAUSE IC trading until NIFTY returns to range-bound regime

---

## Test Period
- **Data**: NIFTY 50 weekly closes + INDIAVIX daily (yfinance)
- **Window**: Aug 2024 – Mar 2026 (≈80 weeks)
- **Market context**: NIFTY fell from ~25,000 to ~22,000 (−12% sustained downtrend)

---

## Results Summary

| Mode | Configs tested | Best PF | Best WR | Verdict |
|------|---------------|---------|---------|---------|
| MIS intraday (±100–350pt shorts) | 120 | 0.01 | 21% | NOT VIABLE |
| NRML weekly hold (Mon→Thu) | 96 | 0.01 | 8% | NOT VIABLE |

**Zero profitable configurations found across 216 parameter combinations.**

---

## Root Causes

### 1. Market regime mismatch
Iron Condor is a **range-bound strategy** (profits from theta decay when price stays between strikes).
NIFTY has been in a sustained downtrend since July 2024:
- Jul 2024: 25,000 → Mar 2026: 22,000 (−12%)
- Short PE strikes repeatedly breached as market drifts lower
- Weekly theta captured is insufficient to offset directional losses

### 2. Strike distance vs. daily volatility
At VIX=14%, daily NIFTY 1-sigma move ≈ **212 points**.
- Shorts at ±100pt: only 0.47σ from ATM → high breach probability every session
- Even shorts at ±350pt: 1.65σ → breached ~10% of sessions, too frequent for IC to profit

### 3. MIS intraday IC has negative structural edge
- Entry at 9:20 AM, forced close by 3:10 PM (MIS)
- Only ~6 hours to capture theta
- Daily sigma (~212pt) >> intraday time-decay captured
- The strategy relies on NIFTY staying put for the day — in a trending market, this fails systematically

---

## Bugs Fixed in ic_backtest.py (2026-03-03)

### Bug 1: Multi-day simulation (CRITICAL)
- **Before**: `simulate_week()` looped over all 4 days (Mon→Thu), simulating NRML hold
- **After**: Added `if not self.weekly_hold and sim_date.date() != entry_day.date(): break`
- **Impact**: Backtest now correctly simulates MIS (same-day) vs NRML (weekly) separately

### Bug 2: Per-step sigma (CRITICAL)
- **Before**: `sigma = max(intraday_vol, daily_sigma)` applied full-day vol to each 25-min step
- **After**: `step_sigma = daily_sigma / sqrt(n_steps)` — per-step sigma is ~3.5× smaller
- **Impact**: NIFTY was simulated moving 212pt per 25-min step instead of 61pt (correct)

Both bugs caused the backtest to *over-simulate* losses. After fixing, IC still shows 0% viable configs — confirming the strategic conclusion is market-driven, not a simulation artifact.

---

## Recommendation

| Action | Rationale |
|--------|-----------|
| **PAUSE IC trading** | 0/216 configs profitable in current regime |
| **Resume condition** | NIFTY India VIX > 13 AND NIFTY in 500pt range for 3+ weeks |
| **Focus capital on** | ORB_SBIN (PF=2.60), EMA_HDFCBANK (PF=2.76), MCX_SILVER (PF=2.98) |
| **Monitor** | INDIA VIX — if VIX spikes to 20+, IC becomes more viable (wider premium) |

---

## Strategy Performance Dashboard (All 6 Active Strategies)

| Strategy | PF | WR% | MaxDD% | Trades | Verdict |
|----------|-----|-----|--------|--------|---------|
| ORB_SBIN | 2.60 | 41.7 | 1.07 | 24 | ✅ RUN |
| VWAP_RELIANCE | 2.58 | 60.0 | 1.18 | 25 | ✅ RUN |
| EMA_HDFCBANK | 2.76 | 40.0 | 1.93 | 15 | ✅ RUN |
| MCX_SILVER | 2.98 | 60.9 | 1.66 | 23 | ✅ RUN |
| SuperTrend_NIFTY | 0.81 | 26.7 | 1.96 | 45 | ⚠️ REVIEW |
| AI_Hybrid_RELIANCE | 0.20 | 38.1 | 21.02 | 21 | ❌ PAUSE |
| IC_NIFTY (MIS) | <0.02 | <21 | n/a | — | ❌ PAUSE |
