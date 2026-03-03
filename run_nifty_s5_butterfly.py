#!/usr/bin/env python3
"""
Nifty Strategy 5 — Short Iron Butterfly (Ultra-Sideways filter)
================================================================
Rationale:
  IC (S3) enters when EMA5 ≈ EMA20 within ±1% (sideways) → wide strangle, smaller credit
  Iron Butterfly (S5) enters when EMA5 ≈ EMA20 within ±0.5% (very flat/coiling)
    → Sell ATM straddle (maximum theta), protect with OTM wings
    → More premium collected vs IC, but break-even range is tighter
    → Ultra-tight sideways filter = very high confidence in range-bound week

Also tests variant: Broken-Wing Butterfly (asymmetric protection, credit > standard wing)

Capital = ₹5L per strategy for DD% calc
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json, itertools

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
df["ema5"]  = df["close"].ewm(span=5,  adjust=False).mean()
df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
rows = df.reset_index()
print(f"  Days: {len(df)}  |  VIX: {df['vix'].min():.1f}–{df['vix'].max():.1f}")

def calc_stats(pnls):
    if not pnls or len(pnls) < 6: return None
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
# Variant A: Short Iron Butterfly
# Sell ATM call + ATM put (straddle)
# Buy ATM+WING call + ATM-WING put (wings)
# Entry: EMA5 within FLAT_PCT of EMA20, VIX vlo–vhi
# ════════════════════════════════════════════════════════════════════════════
def run_iron_butterfly(flat_pct, wing, vlo, vhi, sl_mult):
    trades = []; i = 0
    while i < len(rows):
        row = rows.iloc[i]
        if row["dow"] != 0: i += 1; continue

        vix0 = float(row["vix"])
        if not (vlo <= vix0 <= vhi): i += 5; continue

        e5 = float(row["ema5"]); e20 = float(row["ema20"])
        if abs(e5-e20)/e20*100 > flat_pct: i += 5; continue

        S = float(row["open"]); K = round_strike(S)
        sig = vix0/100; T0 = 4/252

        K_ce_b = round_strike(S + wing)
        K_pe_b = round_strike(S - wing)

        ce_s = bs(S, K,     T0, R, sig, "C")   # sell ATM call
        pe_s = bs(S, K,     T0, R, sig, "P")   # sell ATM put
        ce_b = bs(S, K_ce_b, T0, R, sig, "C")  # buy OTM call wing
        pe_b = bs(S, K_pe_b, T0, R, sig, "P")  # buy OTM put wing
        net_prem = (ce_s - ce_b) + (pe_s - pe_b)
        if net_prem <= 10: i += 5; continue

        sl_trigger = sl_mult * net_prem

        exit_pnl = None
        for j in range(i+1, min(i+5, len(rows))):
            r2 = rows.iloc[j]
            S2 = float(r2["close"]); v2 = float(r2["vix"])/100
            T2 = max((3 - r2["dow"])/252, 1/252)
            ce2_s = bs(S2,K,     T2,R,v2,"C"); ce2_b = bs(S2,K_ce_b,T2,R,v2,"C")
            pe2_s = bs(S2,K,     T2,R,v2,"P"); pe2_b = bs(S2,K_pe_b,T2,R,v2,"P")
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

# ════════════════════════════════════════════════════════════════════════════
# Variant B: Broken-Wing Butterfly (Bullish bias — wider put wing, tighter call wing)
# Sell ATM call + ATM put
# Buy ATM+CALL_WING call (close) + ATM-PUT_WING put (far = cheaper, less protection)
# Net credit > Iron Butterfly; call wing closer = less risk on call side
# Enter in sideways-to-bullish: flat AND EMA20 > EMA50 (long-term bull)
# ════════════════════════════════════════════════════════════════════════════
def run_bwb(flat_pct, call_wing, put_wing, vlo, vhi, sl_mult):
    """Broken-wing: call wing = call_wing, put wing = put_wing (can differ)"""
    trades = []; i = 0
    while i < len(rows):
        row = rows.iloc[i]
        if row["dow"] != 0: i += 1; continue

        vix0 = float(row["vix"])
        if not (vlo <= vix0 <= vhi): i += 5; continue

        e5 = float(row["ema5"]); e20 = float(row["ema20"])
        if abs(e5-e20)/e20*100 > flat_pct: i += 5; continue

        # Long-term bull filter for broken-wing (asymmetric protection)
        if float(row["ema20"]) <= float(row["ema50"]): i += 5; continue

        S = float(row["open"]); K = round_strike(S)
        sig = vix0/100; T0 = 4/252

        K_ce_b = round_strike(S + call_wing)
        K_pe_b = round_strike(S - put_wing)

        ce_s = bs(S, K,     T0, R, sig, "C")
        pe_s = bs(S, K,     T0, R, sig, "P")
        ce_b = bs(S, K_ce_b, T0, R, sig, "C")
        pe_b = bs(S, K_pe_b, T0, R, sig, "P")
        net_prem = (ce_s - ce_b) + (pe_s - pe_b)
        if net_prem <= 10: i += 5; continue

        sl_trigger = sl_mult * net_prem

        exit_pnl = None
        for j in range(i+1, min(i+5, len(rows))):
            r2 = rows.iloc[j]
            S2 = float(r2["close"]); v2 = float(r2["vix"])/100
            T2 = max((3 - r2["dow"])/252, 1/252)
            ce2_s = bs(S2,K,     T2,R,v2,"C"); ce2_b = bs(S2,K_ce_b,T2,R,v2,"C")
            pe2_s = bs(S2,K,     T2,R,v2,"P"); pe2_b = bs(S2,K_pe_b,T2,R,v2,"P")
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

# ════════════════════════════════════════════════════════════════════════════
# SWEEP — Iron Butterfly
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("Sweeping Iron Butterfly configurations…")
FLAT_PCTS  = [0.3, 0.5, 0.7, 1.0]
WINGS      = [150, 200, 250, 300, 350]
VIX_RANGES = [(12,22),(12,18),(14,22),(12,20)]
SL_MULTS   = [1.5, 2.0, 2.5]

best_ib = []; tested_ib = 0
for flat, wing, (vlo,vhi), sl in itertools.product(FLAT_PCTS, WINGS, VIX_RANGES, SL_MULTS):
    tested_ib += 1
    t = run_iron_butterfly(flat, wing, vlo, vhi, sl)
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 5.0:
        best_ib.append(dict(flat_pct=flat, wing=wing, vix_lo=vlo, vix_hi=vhi,
                            sl=sl, variant="IronBfly", **s))
best_ib.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Iron Butterfly — tested: {tested_ib} | passed: {len(best_ib)}")

# ════════════════════════════════════════════════════════════════════════════
# SWEEP — Broken-Wing Butterfly
# ════════════════════════════════════════════════════════════════════════════
print("Sweeping Broken-Wing Butterfly configurations…")
FLAT_PCTS2 = [0.5, 1.0, 1.5]
CALL_WINGS = [150, 200, 250]
PUT_WINGS  = [300, 350, 400]   # wider put protection (bull bias = less put risk)
VIX_RANGES2 = [(12,22),(14,22),(12,18)]
SL_MULTS2   = [1.5, 2.0, 2.5]

best_bwb = []; tested_bwb = 0
for flat, cw, pw, (vlo,vhi), sl in itertools.product(
        FLAT_PCTS2, CALL_WINGS, PUT_WINGS, VIX_RANGES2, SL_MULTS2):
    tested_bwb += 1
    t = run_bwb(flat, cw, pw, vlo, vhi, sl)
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 5.0:
        best_bwb.append(dict(flat_pct=flat, call_wing=cw, put_wing=pw,
                             vix_lo=vlo, vix_hi=vhi, sl=sl, variant="BWBfly", **s))
best_bwb.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Broken-Wing Butterfly — tested: {tested_bwb} | passed: {len(best_bwb)}")

# ── Pick best overall for Strategy 5 ─────────────────────────────────────
all_candidates = best_ib + best_bwb
all_candidates.sort(key=lambda x: (-x["pf"], x["dd"]))

print("\n" + "="*60)
print("STRATEGY 5 — Best Configuration")
print("="*60)

if all_candidates:
    cfg5 = all_candidates[0]
    variant = cfg5["variant"]
    if variant == "IronBfly":
        t5_final = run_iron_butterfly(cfg5["flat_pct"], cfg5["wing"],
                                       cfg5["vix_lo"], cfg5["vix_hi"], cfg5["sl"])
        print(f"  Type: Iron Butterfly | flat≤{cfg5['flat_pct']}% | wing={cfg5['wing']}pt | "
              f"VIX {cfg5['vix_lo']}–{cfg5['vix_hi']} | SL×{cfg5['sl']}")
    else:
        t5_final = run_bwb(cfg5["flat_pct"], cfg5["call_wing"], cfg5["put_wing"],
                            cfg5["vix_lo"], cfg5["vix_hi"], cfg5["sl"])
        print(f"  Type: Broken-Wing Butterfly | flat≤{cfg5['flat_pct']}% | "
              f"call_wing={cfg5['call_wing']}pt put_wing={cfg5['put_wing']}pt | "
              f"VIX {cfg5['vix_lo']}–{cfg5['vix_hi']} | SL×{cfg5['sl']}")

    s5_final = calc_stats(t5_final)
    if s5_final:
        flag = "✅" if s5_final["pf"] >= 2.0 and s5_final["dd"] <= 5.0 else "⚠ "
        print(f"  {flag}  Trades:{s5_final['trades']}  Wins:{int(s5_final['wr']*s5_final['trades']//100)}  "
              f"WR={s5_final['wr']}%")
        print(f"      PF={s5_final['pf']}  MaxDD={s5_final['dd']}%  NetP&L=₹{s5_final['net_pnl']:+,.0f}")

    # Show top 5
    print("\n  Top configs:")
    print(f"  {'Variant':<10} {'flat%':>6} {'wing':>6} {'VIX':>8} {'SL×':>4} | "
          f"{'PF':>5} {'DD%':>5} {'WR%':>5} {'#T':>4}")
    print("  " + "-"*60)
    for c in all_candidates[:10]:
        vname = c.get('variant','')
        wstr  = f"{c.get('wing','-')}" if vname=="IronBfly" else f"c{c.get('call_wing','-')}/p{c.get('put_wing','-')}"
        vix_s = f"{c.get('vix_lo',12)}–{c.get('vix_hi',22)}"
        print(f"  {vname:<10} {c.get('flat_pct',0):>6.1f} {wstr:>6} {vix_s:>8} {c.get('sl',0):>4.1f} | "
              f"{c['pf']:>5.2f} {c['dd']:>5.1f} {c['wr']:>5.1f} {c['trades']:>4}")
else:
    print("  ⚠  No configuration passed PF≥2.0 & DD≤5%")
    # Show best fallback
    all_fb = []
    for flat, wing, (vlo,vhi), sl in itertools.product([0.3,0.5,0.7,1.0],[150,200,250,300,350],
                                                        [(12,22),(12,18),(14,22)],[1.5,2.0,2.5]):
        t = run_iron_butterfly(flat, wing, vlo, vhi, sl)
        s = calc_stats(t)
        if s: all_fb.append(dict(flat_pct=flat, wing=wing, vix_lo=vlo, vix_hi=vhi, sl=sl, **s))
    all_fb.sort(key=lambda x: (-x["pf"], x["dd"]))
    for c in all_fb[:5]:
        print(f"  flat≤{c['flat_pct']}% wing={c['wing']} VIX {c['vix_lo']}–{c['vix_hi']} SL×{c['sl']} "
              f"→ PF={c['pf']} DD={c['dd']}% WR={c['wr']}% #T={c['trades']}")

# ── Update results file ───────────────────────────────────────────────────
if all_candidates:
    try:
        with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json") as f:
            existing = json.load(f)
    except Exception:
        existing = {}

    existing["Short Iron Butterfly"] = {**cfg5, **s5_final}
    with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json","w") as f:
        json.dump(existing, f, indent=2)
    print("\n✅ S5 results saved to nifty_options_backtest.json")
