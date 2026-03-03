#!/usr/bin/env python3
"""
Nifty Options Strategies — Redesigned Backtest (1-year daily)
=============================================================
Key fixes vs v1:
  - All strategies use DEFINED RISK (spreads) to cap max loss
  - DD% calculated vs fixed initial capital (₹5,00,000)
  - Better entry filters

Strategies:
  1. Weekly Bull-Put Credit Spread   — sell OTM put spread in uptrend weeks
  2. Weekly Bear-Call Credit Spread  — sell OTM call spread in downtrend weeks
     (combined directional credit spread, one side per week)
  3. Long Straddle on Breakout Week  — buy ATM straddle after high-vol week
  4. Short Strangle with Wing Hedge  — modified Iron Condor (wider wings)

NIFTY lot = 75 | Capital assumed = ₹5,00,000 per strategy
Black-Scholes pricing from NIFTY spot + India VIX
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json

# ── B-S helpers ─────────────────────────────────────────────────────────
def bs(S, K, T, r, sigma, opt="C"):
    if T <= 0: return max(0, S-K) if opt=="C" else max(0, K-S)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T)/(sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def round_strike(s, step=50):
    return int(round(s/step)*step)

R   = 0.065
LOT = 75
CAP = 500_000   # ₹5L per strategy for DD% calc

# ── Data ─────────────────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=400)   # ~400 days → ~270 trading days

print("Fetching NIFTY + VIX (daily)…")
nifty = yf.download("^NSEI",    start=START.strftime("%Y-%m-%d"),
                    end=END.strftime("%Y-%m-%d"), interval="1d",
                    auto_adjust=True, progress=False)
vix   = yf.download("^INDIAVIX",start=START.strftime("%Y-%m-%d"),
                    end=END.strftime("%Y-%m-%d"), interval="1d",
                    auto_adjust=True, progress=False)

nifty.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in nifty.columns]
vix.columns   = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in vix.columns]
nifty = nifty[["open","high","low","close"]].dropna()
vix   = vix[["close"]].rename(columns={"close":"vix"}).dropna()
df    = nifty.join(vix, how="inner")
df.index = pd.to_datetime(df.index).tz_localize(None)
df["dow"] = df.index.dayofweek

# EMAs for trend filter
df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
df["ema5"]  = df["close"].ewm(span=5,  adjust=False).mean()

# Weekly high/low
df["wk_high"] = df["high"].rolling(5).max()
df["wk_low"]  = df["low"].rolling(5).min()
df["wk_range_pct"] = (df["wk_high"]-df["wk_low"])/df["close"]*100

rows = df.reset_index()
print(f"  Days: {len(df)}  |  VIX: {df['vix'].min():.1f}–{df['vix'].max():.1f}")

def calc_stats(pnls, label):
    if not pnls:
        print(f"  {label}: No trades")
        return
    wins  = [p for p in pnls if p>0]
    loss  = [p for p in pnls if p<0]
    pf    = sum(wins)/max(abs(sum(loss)),1)
    wr    = len(wins)/len(pnls)*100
    # DD vs capital
    eq=0; peak=0; max_dd=0
    for p in pnls:
        eq+=p; peak=max(peak,eq)
        dd=(peak-eq)/CAP*100
        max_dd=max(max_dd,dd)
    print(f"  Trades: {len(pnls):3d}  Wins:{len(wins):3d}  Losses:{len(loss):3d}")
    print(f"  PF={pf:.2f}  WR={wr:.1f}%  MaxDD={max_dd:.1f}%  NetP&L=₹{sum(pnls):+,.0f}")
    return dict(pf=round(pf,2), wr=round(wr,1), dd=round(max_dd,1),
                trades=len(pnls), net_pnl=round(sum(pnls),0))

# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 1 — Directional Weekly Credit Spread
#   Every Monday:
#     • NIFTY > EMA20 (uptrend)  → Sell Bull Put Spread
#         sell ATM-100pt put, buy ATM-300pt put  (200-pt spread)
#     • NIFTY < EMA20 (downtrend) → Sell Bear Call Spread
#         sell ATM+100pt call, buy ATM+300pt call  (200-pt spread)
#   Max profit : net premium × 75
#   Max loss   : (200 - premium) × 75   ← DEFINED RISK
#   Exit       : Thursday close
#   SL         : current spread value ≥ 1.5× initial max-loss → close early
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "="*58)
print("STRATEGY 1 — Directional Weekly Credit Spread (Defined Risk)")
print("="*58)

trades1 = []; i=0
SPREAD = 200   # spread width in NIFTY points

while i < len(rows):
    row = rows.iloc[i]
    if row["dow"] != 0: i+=1; continue    # Monday only

    S    = float(row["open"])
    atm  = round_strike(S)
    sig  = float(row["vix"])/100
    T0   = 4/252
    bull = float(row["close"]) > float(row["ema20"])

    if bull:
        # Bull Put Spread: sell (ATM-100) put, buy (ATM-300) put
        K_sell = round_strike(S - 100)
        K_buy  = round_strike(S - 300)
        p_sell = bs(S, K_sell, T0, R, sig, "P")
        p_buy  = bs(S, K_buy,  T0, R, sig, "P")
        net_prem = p_sell - p_buy          # credit received
        max_loss = SPREAD - net_prem       # per unit
        opt_type = "PUT_SPREAD_BULL"
    else:
        # Bear Call Spread: sell (ATM+100) call, buy (ATM+300) call
        K_sell = round_strike(S + 100)
        K_buy  = round_strike(S + 300)
        p_sell = bs(S, K_sell, T0, R, sig, "C")
        p_buy  = bs(S, K_buy,  T0, R, sig, "C")
        net_prem = p_sell - p_buy
        max_loss = SPREAD - net_prem
        opt_type = "CALL_SPREAD_BEAR"

    if net_prem <= 5: i+=5; continue    # skip if too little premium

    exit_pnl = None
    for j in range(i+1, min(i+5, len(rows))):
        r2  = rows.iloc[j]
        S2  = float(r2["close"])
        T2  = max((3 - r2["dow"])/252, 1/252)
        v2  = float(r2["vix"])/100

        if bull:
            p2_sell = bs(S2, K_sell, T2, R, v2, "P")
            p2_buy  = bs(S2, K_buy,  T2, R, v2, "P")
        else:
            p2_sell = bs(S2, K_sell, T2, R, v2, "C")
            p2_buy  = bs(S2, K_buy,  T2, R, v2, "C")

        curr_spread = p2_sell - p2_buy   # what we'd pay to close
        pnl_unit    = net_prem - curr_spread    # profit = sold-high buy-low
        # SL: if spread widened 1.5× max_loss
        if curr_spread > net_prem + 1.5*max_loss:
            exit_pnl = pnl_unit * LOT; break
        # Thursday exit
        if r2["dow"] == 3:
            exit_pnl = pnl_unit * LOT; break

    if exit_pnl is not None:
        trades1.append(exit_pnl)
    i += 5

s1 = calc_stats(trades1, "S1")

# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 2 — Long Straddle on Breakout Continuation
#   Condition : Last week's NIFTY range > 2.5% AND Monday gap > 0.5%
#   Entry      : Monday open — buy ATM straddle
#   TP         : 60% gain on total premium → close
#   SL         : 35% loss on total premium → close
#   Else        : Close Thursday
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "="*58)
print("STRATEGY 2 — Long ATM Straddle (Post-Breakout Continuation)")
print("="*58)

trades2 = []; i=0
WK_RANGE_MIN = 2.5   # % weekly range to qualify
GAP_MIN      = 0.3   # % Monday gap from prior close

while i < len(rows):
    row = rows.iloc[i]
    if row["dow"] != 0: i+=1; continue

    # Check prior-week range (using last 5 days before this Monday)
    wk_rng = float(row["wk_range_pct"]) if not pd.isna(row["wk_range_pct"]) else 0
    if wk_rng < WK_RANGE_MIN:
        i += 5; continue

    # Monday gap
    if i > 0:
        prev_close = float(rows.iloc[i-1]["close"])
        mon_open   = float(row["open"])
        gap_pct    = abs(mon_open - prev_close)/prev_close*100
        if gap_pct < GAP_MIN:
            i += 5; continue

    S    = float(row["open"])
    K    = round_strike(S)
    sig  = float(row["vix"])/100
    T0   = 4/252
    ce0  = bs(S, K, T0, R, sig, "C")
    pe0  = bs(S, K, T0, R, sig, "P")
    tot0 = ce0 + pe0
    if tot0 < 30: i+=5; continue    # too little premium

    exit_pnl = None
    for j in range(i+1, min(i+5, len(rows))):
        r2  = rows.iloc[j]
        S2  = float(r2["close"])
        T2  = max((3 - r2["dow"])/252, 1/252)
        v2  = float(r2["vix"])/100
        ce2 = bs(S2, K, T2, R, v2, "C")
        pe2 = bs(S2, K, T2, R, v2, "P")
        tot2 = ce2 + pe2
        pnl_unit = tot2 - tot0
        if tot2 >= tot0 * 1.60:          # TP: +60%
            exit_pnl = pnl_unit * LOT; break
        if tot2 <= tot0 * 0.65:          # SL: -35%
            exit_pnl = pnl_unit * LOT; break
        if r2["dow"] == 3:
            exit_pnl = pnl_unit * LOT; break

    if exit_pnl is not None:
        trades2.append(exit_pnl)
    i += 5

s2 = calc_stats(trades2, "S2")

# ══════════════════════════════════════════════════════════════════════════
# STRATEGY 3 — Modified Iron Condor (Wide Wings, VIX + EMA filter)
#   Entry  : Monday; EMA5 within 0.5% of EMA20 (sideways) AND VIX 14–22
#   Sell   : ATM + 150pt Call  +  ATM − 150pt Put   (strangle)
#   Hedge  : Buy  ATM + 350pt Call  +  ATM − 350pt Put   (wings)
#   Net spread = 200pt per side  → max loss defined
#   Exit   : Thursday close OR SL = 2× net premium collected
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "="*58)
print("STRATEGY 3 — Wide Iron Condor (Sideways + VIX filter)")
print("="*58)

trades3 = []; i=0
VIX_LOW=12; VIX_HIGH=22
FLAT_PCT=1.0    # EMA5 within ±1% of EMA20 = "sideways"

while i < len(rows):
    row = rows.iloc[i]
    if row["dow"] != 0: i+=1; continue

    vix0 = float(row["vix"])
    if not (VIX_LOW <= vix0 <= VIX_HIGH):
        i += 5; continue

    # Flat/sideways filter
    e5 = float(row["ema5"]); e20 = float(row["ema20"])
    flat_pct = abs(e5-e20)/e20*100
    if flat_pct > FLAT_PCT:
        i += 5; continue

    S    = float(row["open"])
    K_ce_s = round_strike(S + 150); K_ce_b = round_strike(S + 350)
    K_pe_s = round_strike(S - 150); K_pe_b = round_strike(S - 350)
    sig  = vix0/100; T0 = 4/252

    ce_s = bs(S, K_ce_s, T0, R, sig, "C"); ce_b = bs(S, K_ce_b, T0, R, sig, "C")
    pe_s = bs(S, K_pe_s, T0, R, sig, "P"); pe_b = bs(S, K_pe_b, T0, R, sig, "P")
    net_prem = (ce_s - ce_b) + (pe_s - pe_b)   # net credit
    if net_prem <= 8: i+=5; continue

    sl_trigger = 2 * net_prem   # SL: if we'd pay 2× what we received

    exit_pnl = None
    for j in range(i+1, min(i+5, len(rows))):
        r2 = rows.iloc[j]
        S2 = float(r2["close"]); v2 = float(r2["vix"])/100
        T2 = max((3-r2["dow"])/252, 1/252)
        ce2_s=bs(S2,K_ce_s,T2,R,v2,"C"); ce2_b=bs(S2,K_ce_b,T2,R,v2,"C")
        pe2_s=bs(S2,K_pe_s,T2,R,v2,"P"); pe2_b=bs(S2,K_pe_b,T2,R,v2,"P")
        curr_cost = (ce2_s-ce2_b)+(pe2_s-pe2_b)   # current spread (to close)
        pnl_unit  = net_prem - curr_cost
        if curr_cost >= sl_trigger:
            exit_pnl = pnl_unit * LOT; break
        if r2["dow"] == 3:
            exit_pnl = pnl_unit * LOT; break

    if exit_pnl is not None:
        trades3.append(exit_pnl)
    i += 5

s3 = calc_stats(trades3, "S3")

# ── Final Summary ─────────────────────────────────────────────────────────
print("\n" + "="*58)
print("NIFTY OPTIONS — FINAL SUMMARY  (capital base ₹5L)")
print("="*58)
strats = [
    ("Directional Credit Spread", trades1, s1),
    ("Long Straddle (Breakout)",  trades2, s2),
    ("Wide Iron Condor",          trades3, s3),
]
print(f"  {'Strategy':<30} {'PF':>5} {'DD%':>5} {'WR%':>5} {'#T':>4} {'NetP&L':>10}")
print("  " + "-"*62)
results = {}
for name, pnls, s in strats:
    if not pnls or not s:
        print(f"  ⚠  {name:<30} — no trades")
        continue
    flag = "✅" if s["pf"]>=2.0 and s["dd"]<=5.0 else "⚠ "
    print(f"{flag} {name:<30} {s['pf']:>5.2f} {s['dd']:>5.1f} {s['wr']:>5.1f} {s['trades']:>4} ₹{s['net_pnl']:>9,.0f}")
    results[name] = s

with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json","w") as f:
    json.dump(results, f, indent=2)
print("\n✅ Results saved to nifty_options_backtest.json")
