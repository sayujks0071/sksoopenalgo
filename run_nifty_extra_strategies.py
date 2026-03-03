#!/usr/bin/env python3
"""
Nifty Options — 2 New Strategies (Strategies 4 & 5)
====================================================
Strategy 4: Trend-Biased Iron Condor
  - Enters when market is TRENDING (complement to S3 which is sideways-only)
  - In uptrend: sell call side far, put side near (bullish bias IC)
  - In downtrend: sell put side far, call side near (bearish bias IC)
  - VIX 12–22 filter

Strategy 5: Post-Spike Mean-Reversion IC
  - Enters week after a HIGH-VOLATILITY week (range > 3%)
  - High VIX after spike = fat premiums; next week often consolidates
  - Sell wide strangle (±200pt), buy wings (±400pt)
  - VIX > 16 at entry (ensures enough premium from spike)

Both are complementary to S3 (sideways IC):
  S3 — Sideways (EMA5 ≈ EMA20 ±1%), VIX 12–22 → standard IC ±150/±350
  S4 — Trending (EMA5 diverges from EMA20 > 1%), VIX 12–22 → biased IC
  S5 — Post big-move week (range > 3%), any trend → mean-reversion IC ±200/±400

NIFTY lot = 75 | Capital = ₹5,00,000 per strategy (for DD% calc)
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json, itertools

# ── B-S helpers ─────────────────────────────────────────────────────────────
def bs(S, K, T, r, sigma, opt="C"):
    if T <= 0: return max(0, S-K) if opt=="C" else max(0, K-S)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def round_strike(s, step=50):
    return int(round(s/step)*step)

R   = 0.065
LOT = 75
CAP = 500_000

# ── Fetch data ───────────────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=400)

print("Fetching NIFTY + VIX (daily)…")
nifty = yf.download("^NSEI",     start=START.strftime("%Y-%m-%d"),
                    end=END.strftime("%Y-%m-%d"), interval="1d",
                    auto_adjust=True, progress=False)
vix   = yf.download("^INDIAVIX", start=START.strftime("%Y-%m-%d"),
                    end=END.strftime("%Y-%m-%d"), interval="1d",
                    auto_adjust=True, progress=False)

nifty.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in nifty.columns]
vix.columns   = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in vix.columns]
nifty = nifty[["open","high","low","close"]].dropna()
vix   = vix[["close"]].rename(columns={"close":"vix"}).dropna()
df    = nifty.join(vix, how="inner")
df.index = pd.to_datetime(df.index).tz_localize(None)
df["dow"]   = df.index.dayofweek
df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
df["ema5"]  = df["close"].ewm(span=5,  adjust=False).mean()

# Weekly metrics (look-back 5 bars for prior-week range)
df["wk_high"]     = df["high"].rolling(5).max()
df["wk_low"]      = df["low"].rolling(5).min()
df["wk_range_pct"] = (df["wk_high"] - df["wk_low"]) / df["close"] * 100

rows = df.reset_index()
print(f"  Days: {len(df)}  |  VIX: {df['vix'].min():.1f}–{df['vix'].max():.1f}")

def calc_stats(pnls, label=""):
    if not pnls: return None
    wins = [p for p in pnls if p > 0]
    loss = [p for p in pnls if p < 0]
    pf   = sum(wins) / max(abs(sum(loss)), 1)
    wr   = len(wins) / len(pnls) * 100
    eq = 0; peak = 0; max_dd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq)
        dd = (peak - eq) / CAP * 100
        max_dd = max(max_dd, dd)
    return dict(pf=round(pf,2), wr=round(wr,1), dd=round(max_dd,1),
                trades=len(pnls), net_pnl=round(sum(pnls), 0))

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 4 — Trend-Biased Iron Condor
#
# Entry: Monday; EMA5 diverges from EMA20 by > TREND_PCT (trending market)
#   BULL (EMA5 > EMA20 * (1+TREND_PCT/100)):
#     Sell ATM + CALL_OTM call  + ATM - PUT_OTM put   ← asymmetric strangle
#     Buy  ATM + (CALL_OTM+WING) call + ATM - (PUT_OTM+WING) put  ← wings
#     Logic: market trending up → upside risk lower, put protection lighter
#   BEAR (EMA5 < EMA20 * (1-TREND_PCT/100)):
#     Mirror: sell ATM - PUT_OTM put + ATM + CALL_OTM call  (bearish bias)
# VIX: 12–22 (same as S3 to ensure adequate premium)
# Exit: Thursday close OR SL = 2× net premium
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("STRATEGY 4 — Trend-Biased Iron Condor")
print("="*60)

def run_s4(trend_pct, call_otm_bull, put_otm_bull, wing_width,
           vix_lo, vix_hi, sl_mult):
    """
    trend_pct    : min EMA5/EMA20 divergence % to count as trending
    call_otm_bull: in bull trend, sell call this many pts OTM
    put_otm_bull : in bull trend, sell put this many pts below ATM (OTM)
    wing_width   : protection wing width on each side
    """
    trades = []; i = 0
    while i < len(rows):
        row = rows.iloc[i]
        if row["dow"] != 0: i += 1; continue

        vix0 = float(row["vix"])
        if not (vix_lo <= vix0 <= vix_hi): i += 5; continue

        e5  = float(row["ema5"])
        e20 = float(row["ema20"])
        div_pct = (e5 - e20) / e20 * 100  # positive = bull, negative = bear

        if abs(div_pct) < trend_pct: i += 5; continue  # not trending enough

        S = float(row["open"]); sig = vix0/100; T0 = 4/252

        if div_pct > 0:  # BULL trend
            # Sell call OTM (farther), put less OTM (tighter near money)
            K_ce_s = round_strike(S + call_otm_bull)
            K_ce_b = round_strike(S + call_otm_bull + wing_width)
            K_pe_s = round_strike(S - put_otm_bull)
            K_pe_b = round_strike(S - put_otm_bull - wing_width)
        else:  # BEAR trend (mirror)
            K_ce_s = round_strike(S + put_otm_bull)
            K_ce_b = round_strike(S + put_otm_bull + wing_width)
            K_pe_s = round_strike(S - call_otm_bull)
            K_pe_b = round_strike(S - call_otm_bull - wing_width)

        ce_s = bs(S, K_ce_s, T0, R, sig, "C"); ce_b = bs(S, K_ce_b, T0, R, sig, "C")
        pe_s = bs(S, K_pe_s, T0, R, sig, "P"); pe_b = bs(S, K_pe_b, T0, R, sig, "P")
        net_prem = (ce_s - ce_b) + (pe_s - pe_b)
        if net_prem <= 5: i += 5; continue

        sl_trigger = sl_mult * net_prem

        exit_pnl = None
        for j in range(i+1, min(i+5, len(rows))):
            r2 = rows.iloc[j]
            S2 = float(r2["close"]); v2 = float(r2["vix"])/100
            T2 = max((3 - r2["dow"])/252, 1/252)
            ce2_s = bs(S2,K_ce_s,T2,R,v2,"C"); ce2_b = bs(S2,K_ce_b,T2,R,v2,"C")
            pe2_s = bs(S2,K_pe_s,T2,R,v2,"P"); pe2_b = bs(S2,K_pe_b,T2,R,v2,"P")
            curr_cost = (ce2_s - ce2_b) + (pe2_s - pe2_b)
            pnl_unit  = net_prem - curr_cost
            if curr_cost >= sl_trigger:
                exit_pnl = pnl_unit * LOT; break
            if r2["dow"] == 3:
                exit_pnl = pnl_unit * LOT; break

        if exit_pnl is not None:
            trades.append(exit_pnl)
        i += 5
    return trades

# Parameter sweep for S4
print("  Running parameter sweep…")
TREND_PCTS    = [0.5, 1.0, 1.5, 2.0]
CALL_OTM_BULL = [150, 200, 250, 300]  # call OTM in bull market
PUT_OTM_BULL  = [50,  100, 150]        # put OTM in bull market
WING_WIDTHS   = [200, 250]
VIX_RANGES    = [(12,22), (14,22), (12,18)]
SL_MULTS      = [1.5, 2.0, 2.5]

best_s4 = []; tested_s4 = 0
for trend, c_otm, p_otm, wing, (vlo,vhi), sl in itertools.product(
        TREND_PCTS, CALL_OTM_BULL, PUT_OTM_BULL, WING_WIDTHS, VIX_RANGES, SL_MULTS):
    if c_otm <= p_otm: continue   # call must be farther out in bull (that's the asymmetry)
    tested_s4 += 1
    t = run_s4(trend, c_otm, p_otm, wing, vlo, vhi, sl)
    if not t or len(t) < 10: continue
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 5.0:
        best_s4.append(dict(trend_pct=trend, call_otm=c_otm, put_otm=p_otm,
                            wing=wing, vix_lo=vlo, vix_hi=vhi, sl=sl, **s))

best_s4.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Tested: {tested_s4:,}  |  Passed PF≥2.0 & DD≤5%: {len(best_s4)}")

# Pick best config
if best_s4:
    cfg4 = best_s4[0]
    t4 = run_s4(cfg4["trend_pct"], cfg4["call_otm"], cfg4["put_otm"],
                cfg4["wing"], cfg4["vix_lo"], cfg4["vix_hi"], cfg4["sl"])
    s4 = calc_stats(t4)
    print(f"\n  BEST S4 config: trend≥{cfg4['trend_pct']}% | call_OTM={cfg4['call_otm']} | "
          f"put_OTM={cfg4['put_otm']} | wing={cfg4['wing']} | VIX {cfg4['vix_lo']}–{cfg4['vix_hi']} | SL×{cfg4['sl']}")
    print(f"  Trades: {s4['trades']}  Wins: {int(s4['wr']*s4['trades']//100)}  WR={s4['wr']}%")
    print(f"  PF={s4['pf']}  MaxDD={s4['dd']}%  NetP&L=₹{s4['net_pnl']:+,.0f}")
else:
    print("  ⚠  No config passed PF≥2.0 & DD≤5%")
    # Fallback: show best we found
    all_s4 = []
    for trend, c_otm, p_otm, wing, (vlo,vhi), sl in itertools.product(
            TREND_PCTS, CALL_OTM_BULL, PUT_OTM_BULL, WING_WIDTHS, VIX_RANGES, SL_MULTS):
        if c_otm <= p_otm: continue
        t = run_s4(trend, c_otm, p_otm, wing, vlo, vhi, sl)
        if t and len(t) >= 8:
            s = calc_stats(t)
            if s: all_s4.append(dict(trend_pct=trend, call_otm=c_otm, put_otm=p_otm,
                                     wing=wing, vix_lo=vlo, vix_hi=vhi, sl=sl, **s))
    all_s4.sort(key=lambda x: (-x["pf"], x["dd"]))
    if all_s4:
        cfg4 = all_s4[0]
        t4 = run_s4(cfg4["trend_pct"], cfg4["call_otm"], cfg4["put_otm"],
                    cfg4["wing"], cfg4["vix_lo"], cfg4["vix_hi"], cfg4["sl"])
        s4 = calc_stats(t4)
        print(f"  Best found: trend≥{cfg4['trend_pct']}% | call_OTM={cfg4['call_otm']} | "
              f"put_OTM={cfg4['put_otm']} | VIX {cfg4['vix_lo']}–{cfg4['vix_hi']}")
        print(f"  Trades:{s4['trades']} WR={s4['wr']}% PF={s4['pf']} DD={s4['dd']}%")
    else:
        cfg4 = None; t4 = []; s4 = None

# ════════════════════════════════════════════════════════════════════════════
# STRATEGY 5 — Post-Spike Mean-Reversion IC
#
# Entry: Monday AFTER a week with NIFTY range > WK_SPIKE% (big move week)
# Rationale: High-vol week inflates VIX → fat premiums next week; market
#            tends to consolidate after big moves → IC decays profitably
# Structure: Sell ATM±SELL_OTM strangle, buy ATM±(SELL_OTM+WING) wings
# Filter: VIX at entry > VIX_MIN (confirming elevated premium post-spike)
# Exit: Thursday close OR SL = SL_MULT × net premium
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("STRATEGY 5 — Post-Spike Mean-Reversion IC")
print("="*60)

def run_s5(wk_spike_pct, sell_otm, wing_width, vix_min, sl_mult):
    trades = []; i = 0
    while i < len(rows):
        row = rows.iloc[i]
        if row["dow"] != 0: i += 1; continue

        # Prior week range (wk_range_pct is computed with 5-bar rolling on the
        # same row, so it covers roughly the prior 5 trading days including today)
        if i < 5: i += 5; continue
        # Compute prior week's range from actual data
        prior_week = rows.iloc[max(0,i-5):i]
        if len(prior_week) < 3: i += 5; continue
        prior_range = (prior_week["high"].max() - prior_week["low"].min()) / float(row["close"]) * 100

        if prior_range < wk_spike_pct: i += 5; continue

        vix0 = float(row["vix"])
        if vix0 < vix_min: i += 5; continue   # need elevated premium post-spike

        S = float(row["open"]); sig = vix0/100; T0 = 4/252

        K_ce_s = round_strike(S + sell_otm);          K_ce_b = round_strike(S + sell_otm + wing_width)
        K_pe_s = round_strike(S - sell_otm);          K_pe_b = round_strike(S - sell_otm - wing_width)

        ce_s = bs(S, K_ce_s, T0, R, sig, "C"); ce_b = bs(S, K_ce_b, T0, R, sig, "C")
        pe_s = bs(S, K_pe_s, T0, R, sig, "P"); pe_b = bs(S, K_pe_b, T0, R, sig, "P")
        net_prem = (ce_s - ce_b) + (pe_s - pe_b)
        if net_prem <= 5: i += 5; continue

        sl_trigger = sl_mult * net_prem

        exit_pnl = None
        for j in range(i+1, min(i+5, len(rows))):
            r2 = rows.iloc[j]
            S2 = float(r2["close"]); v2 = float(r2["vix"])/100
            T2 = max((3 - r2["dow"])/252, 1/252)
            ce2_s = bs(S2,K_ce_s,T2,R,v2,"C"); ce2_b = bs(S2,K_ce_b,T2,R,v2,"C")
            pe2_s = bs(S2,K_pe_s,T2,R,v2,"P"); pe2_b = bs(S2,K_pe_b,T2,R,v2,"P")
            curr_cost = (ce2_s - ce2_b) + (pe2_s - pe2_b)
            pnl_unit  = net_prem - curr_cost
            if curr_cost >= sl_trigger:
                exit_pnl = pnl_unit * LOT; break
            if r2["dow"] == 3:
                exit_pnl = pnl_unit * LOT; break

        if exit_pnl is not None:
            trades.append(exit_pnl)
        i += 5
    return trades

# Parameter sweep for S5
print("  Running parameter sweep…")
WK_SPIKES = [2.5, 3.0, 3.5, 4.0]
SELL_OTMS  = [100, 150, 200, 250]
WING_WIDTHS5 = [150, 200, 250]
VIX_MINS   = [14, 16, 18, 20]
SL_MULTS5  = [1.5, 2.0, 2.5]

best_s5 = []; tested_s5 = 0
for spike, sotm, wing, vmin, sl in itertools.product(
        WK_SPIKES, SELL_OTMS, WING_WIDTHS5, VIX_MINS, SL_MULTS5):
    tested_s5 += 1
    t = run_s5(spike, sotm, wing, vmin, sl)
    if not t or len(t) < 8: continue
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 5.0:
        best_s5.append(dict(wk_spike=spike, sell_otm=sotm, wing=wing,
                            vix_min=vmin, sl=sl, **s))

best_s5.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Tested: {tested_s5:,}  |  Passed PF≥2.0 & DD≤5%: {len(best_s5)}")

if best_s5:
    cfg5 = best_s5[0]
    t5 = run_s5(cfg5["wk_spike"], cfg5["sell_otm"], cfg5["wing"],
                cfg5["vix_min"], cfg5["sl"])
    s5 = calc_stats(t5)
    print(f"\n  BEST S5 config: spike>{cfg5['wk_spike']}% | sell_OTM={cfg5['sell_otm']} | "
          f"wing={cfg5['wing']} | VIX_min={cfg5['vix_min']} | SL×{cfg5['sl']}")
    print(f"  Trades: {s5['trades']}  Wins: {int(s5['wr']*s5['trades']//100)}  WR={s5['wr']}%")
    print(f"  PF={s5['pf']}  MaxDD={s5['dd']}%  NetP&L=₹{s5['net_pnl']:+,.0f}")
else:
    print("  ⚠  No config passed PF≥2.0 & DD≤5% — showing best found")
    all_s5 = []
    for spike, sotm, wing, vmin, sl in itertools.product(
            WK_SPIKES, SELL_OTMS, WING_WIDTHS5, VIX_MINS, SL_MULTS5):
        t = run_s5(spike, sotm, wing, vmin, sl)
        if t and len(t) >= 6:
            s = calc_stats(t)
            if s: all_s5.append(dict(wk_spike=spike, sell_otm=sotm, wing=wing,
                                     vix_min=vmin, sl=sl, **s))
    all_s5.sort(key=lambda x: (-x["pf"], x["dd"]))
    if all_s5:
        cfg5 = all_s5[0]
        t5 = run_s5(cfg5["wk_spike"], cfg5["sell_otm"], cfg5["wing"],
                    cfg5["vix_min"], cfg5["sl"])
        s5 = calc_stats(t5)
        print(f"  Best: spike>{cfg5['wk_spike']}% | sell_OTM={cfg5['sell_otm']} | "
              f"VIX_min={cfg5['vix_min']} | SL×{cfg5['sl']}")
        print(f"  Trades:{s5['trades']} WR={s5['wr']}% PF={s5['pf']} DD={s5['dd']}%")
    else:
        cfg5 = None; t5 = []; s5 = None

# ── Combined Summary ──────────────────────────────────────────────────────────
print("\n" + "="*60)
print("NIFTY OPTIONS S4 + S5 — SUMMARY  (capital base ₹5L each)")
print("="*60)
print(f"  {'Strategy':<35} {'PF':>5} {'DD%':>5} {'WR%':>5} {'#T':>4} {'NetP&L':>12}")
print("  " + "-"*66)

results_extra = {}
for name, pnls, s in [
    ("Trend-Biased IC (S4)",          t4 if 't4' in dir() else [], s4),
    ("Post-Spike Mean-Reversion (S5)", t5 if 't5' in dir() else [], s5),
]:
    if not pnls or not s:
        print(f"  ⚠  {name:<35} — no trades / no result")
        continue
    flag = "✅" if s["pf"] >= 2.0 and s["dd"] <= 5.0 else "⚠ "
    print(f"{flag} {name:<35} {s['pf']:>5.2f} {s['dd']:>5.1f} {s['wr']:>5.1f} "
          f"{s['trades']:>4} ₹{s['net_pnl']:>11,.0f}")
    results_extra[name] = {**(cfg4 if name.startswith("Trend") and cfg4 else
                              cfg5 if cfg5 else {}), **s}

# Save combined results
try:
    with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json") as f:
        existing = json.load(f)
except Exception:
    existing = {}

existing.update(results_extra)
with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json","w") as f:
    json.dump(existing, f, indent=2)
print("\n✅ Results appended to nifty_options_backtest.json")
