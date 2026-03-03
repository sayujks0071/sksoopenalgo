#!/usr/bin/env python3
"""
OVERNIGHT REFINEMENT — Nifty & Sensex Options Strategies v3
============================================================
Goal: PF > 2.5, WR > 60%, DD < 3%, Trades > 40 in 400 days

New strategies vs v2:
  W1  Weekly VIX-Adaptive IC          (weekly expiry, 4 regimes)
  W2  Weekly Broken-Wing Butterfly    (asymmetric, bearish tilt)
  W3  Thursday Theta Decay IC         (Tue entry, 3 DTE, max theta)
  W4  VIX-Spike Mean Reversion        (post-spike premium harvest)
  W5  Trend-Momentum Bull Put Spread  (directional credit, weekly)
  W6  Sideways Short Straddle         (delta-hedged at 0.3)
  W7  SENSEX Weekly BWB               (lot=10, step=100)
  W8  Composite: Best-of-3 combo      (W1+W2+W3 on different weeks)

NIFTY lot=75  step=50   CAP=₹5L
SENSEX lot=10 step=100  CAP=₹2L
Interest rate = 6.5%  |  400-day window
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json, itertools

# ── Black-Scholes ─────────────────────────────────────────────────────────────
def bs(S, K, T, r, sigma, opt="C"):
    if T <= 0: return max(0, S-K) if opt=="C" else max(0, K-S)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def rs(s, step): return int(round(s/step)*step)

R = 0.065

# ── Fetch data ─────────────────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=420)

def fetch_index(ticker, start, end):
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                     end=end.strftime("%Y-%m-%d"), interval="1d",
                     auto_adjust=True, progress=False)
    df.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    return df[["open","high","low","close"]].dropna()

print("Fetching data…")
nifty  = fetch_index("^NSEI",     START, END)
sensex = fetch_index("^BSESN",    START, END)
vix_df = fetch_index("^INDIAVIX", START, END)[["close"]].rename(columns={"close":"vix"})

def prep(idx_df, vix_df, ema_spans=(5,20,50)):
    df = idx_df.join(vix_df, how="inner")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    for s in ema_spans:
        df[f"ema{s}"] = df["close"].ewm(span=s, adjust=False).mean()
    df["rsi"] = _rsi(df["close"])
    df["atr"] = _atr(df)
    df["wk_range_pct"] = (df["high"].rolling(5).max() - df["low"].rolling(5).min()) / df["close"] * 100
    df["prev_wk_range"] = df["wk_range_pct"].shift(5)
    df["vol_regime"] = pd.cut(df["vix"], bins=[0,13,17,22,100],
                               labels=["low","mid","high","spike"]).astype(str)
    df["trend"] = np.where(df["ema5"] > df["ema20"]*1.005, "up",
                  np.where(df["ema5"] < df["ema20"]*0.995, "dn", "flat"))
    df["dow"]  = df.index.dayofweek
    return df

def _rsi(close, n=14):
    d = close.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(com=n-1, min_periods=n).mean()
    al = l.ewm(com=n-1, min_periods=n).mean()
    return 100 - 100/(1 + ag/al.replace(0,np.nan))

def _atr(df, n=14):
    h,l,c = df["high"],df["low"],df["close"]
    tr = pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=n, min_periods=n).mean()

ndf = prep(nifty,  vix_df)
sdf = prep(sensex, vix_df)
print(f"  NIFTY : {len(ndf)} days  VIX {ndf['vix'].min():.1f}–{ndf['vix'].max():.1f}")
print(f"  SENSEX: {len(sdf)} days")

# ── Stats helper ───────────────────────────────────────────────────────────────
def stats(pnls, cap, label=""):
    if not pnls: return None
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    pf = round(sum(wins)/abs(sum(losses)),2) if losses else 99.0
    wr = round(100*len(wins)/len(pnls),1)
    eq = cap + pd.Series(pnls).cumsum()
    dd = round(100*(eq.cummax()-eq).max()/eq.cummax().max(), 2)
    net = round(sum(pnls))
    return {"pf":pf,"wr_pct":wr,"dd_pct":dd,"trades":len(pnls),"net_pnl":net,"run_date":datetime.today().strftime("%Y-%m-%d")}

def print_stats(label, s):
    if not s: print(f"  {label}: no trades"); return
    flag = "✅" if s["pf"]>2.5 and s["wr_pct"]>60 and s["dd_pct"]<3 else "⚠️" if s["pf"]>1.5 else "❌"
    print(f"  {flag} {label:35s}  PF={s['pf']:5.2f}  WR={s['wr_pct']:5.1f}%  DD={s['dd_pct']:4.1f}%  T={s['trades']:3d}  Net=₹{s['net_pnl']:,.0f}")

# ── Expiry calendar: every Thursday ───────────────────────────────────────────
def thursdays(df):
    return df[df["dow"]==3].index.tolist()

# ══════════════════════════════════════════════════════════════════════════════
# W1: Weekly VIX-Adaptive Iron Condor
# Entry: Monday; width driven by VIX regime
# Exit: Thursday close OR stop at 2× credit
# ══════════════════════════════════════════════════════════════════════════════
def w1_adaptive_ic(df, lot=75, step=50, cap=500_000, sl_mult=2.0):
    rows = df.reset_index()
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        # Find the Monday of the same week (look back up to 4 days)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 0:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,5):
                if th_pos-back >= 0:
                    mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or pd.isna(S): continue

        # Regime-based strike selection
        regime = row["vol_regime"]
        if regime in ("low","mid"):
            if regime == "low":    c_otm, p_otm, wing = 100, 100, 200
            else:                   c_otm, p_otm, wing = 150, 150, 250
            vix_filter = 12 <= vix <= 20
        elif regime == "high":
            c_otm, p_otm, wing = 200, 200, 300; vix_filter = True
        else:  # spike: skip
            continue
        if not vix_filter: continue

        sigma = (vix/100) / np.sqrt(52)
        T = 4/252
        K_atm = rs(S, step)
        Kc  = K_atm + c_otm;  Kcw = Kc + wing
        Kp  = K_atm - p_otm;  Kpw = Kp - wing

        credit = (bs(S,Kc,T,R,sigma,"C") - bs(S,Kcw,T,R,sigma,"C") +
                  bs(S,Kp,T,R,sigma,"P") - bs(S,Kpw,T,R,sigma,"P")) * lot
        if credit <= 0: continue
        max_loss = (wing - credit/lot) * lot
        stop = credit * sl_mult

        # Expiry P&L
        row_th = df.iloc[th_pos]
        Se = row_th["close"]
        expiry_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -stop)
        trades.append({"pnl": round(pnl,2), "date": str(th_idx.date())})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W2: Weekly Broken-Wing Butterfly (bearish asymmetric)
# Short ATM straddle, long OTM wings (call side narrow, put side wide)
# Entry: Monday when market flat (|EMA5/EMA20-1| < 0.8%)
# ══════════════════════════════════════════════════════════════════════════════
def w2_bwb(df, lot=75, step=50, cap=500_000, call_wing=200, put_wing=350, flat_pct=0.8, sl=1.5):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek <= 1:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or pd.isna(S): continue
        flat = abs(row["ema5"]/row["ema20"] - 1)*100 < flat_pct
        if not flat or not (12 <= vix <= 22): continue

        sigma = (vix/100) / np.sqrt(52)
        T = 4/252
        K = rs(S, step)
        Kcu = K + call_wing;  Kpd = K - put_wing

        # Sell ATM call + ATM put, buy OTM call, buy OTM put
        credit = (bs(S,K,T,R,sigma,"C") + bs(S,K,T,R,sigma,"P")
                  - bs(S,Kcu,T,R,sigma,"C") - bs(S,Kpd,T,R,sigma,"P")) * lot
        if credit <= 0: continue
        stop_val = credit * sl

        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-K) - max(0,Se-Kcu) +
                      max(0,K-Se) - max(0,Kpd-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -stop_val)
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W3: Thursday Theta Decay IC (Enter Tuesday, 3 DTE, max theta)
# ══════════════════════════════════════════════════════════════════════════════
def w3_theta_ic(df, lot=75, step=50, cap=500_000, otm=100, wing=200, sl=2.0, profit_tgt=0.6):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        # Find Tuesday before Thursday
        tue_pos = None
        for back in range(1,4):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 1:
                tue_pos = th_pos-back; break
        if tue_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: tue_pos = th_pos-back; break
        if tue_pos is None: continue
        row = df.iloc[tue_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (13 <= vix <= 20): continue

        sigma = (vix/100) / np.sqrt(52)
        T = 3/252
        K = rs(S, step)
        Kc = K + otm; Kcw = Kc + wing
        Kp = K - otm; Kpw = Kp - wing

        credit = (bs(S,Kc,T,R,sigma,"C") - bs(S,Kcw,T,R,sigma,"C") +
                  bs(S,Kp,T,R,sigma,"P") - bs(S,Kpw,T,R,sigma,"P")) * lot
        if credit <= 0: continue

        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -(credit * sl))
        pnl = min(pnl, credit * profit_tgt)
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W4: VIX-Spike Mean Reversion (enter week after VIX > 18 spike)
# ══════════════════════════════════════════════════════════════════════════════
def w4_spike_reversion(df, lot=75, step=50, cap=500_000, otm=200, wing=350, vix_min=17, sl=2.0):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 0:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or pd.isna(S): continue
        prev_range = row["prev_wk_range"]
        if pd.isna(prev_range) or prev_range < 2.5 or vix < vix_min: continue

        sigma = (vix/100) / np.sqrt(52)
        T = 4/252
        K = rs(S, step)
        Kc = K+otm; Kcw = Kc+wing; Kp = K-otm; Kpw = Kp-wing

        credit = (bs(S,Kc,T,R,sigma,"C") - bs(S,Kcw,T,R,sigma,"C") +
                  bs(S,Kp,T,R,sigma,"P") - bs(S,Kpw,T,R,sigma,"P")) * lot
        if credit <= 0: continue

        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -(credit*sl))
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W5: Trend-Momentum Bull Put / Bear Call spread (directional credit)
# ══════════════════════════════════════════════════════════════════════════════
def w5_directional_spread(df, lot=75, step=50, cap=500_000, otm=100, wing=150, sl=2.5):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 0:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (12 <= vix <= 22): continue
        trend = row["trend"]
        rsi_val = row["rsi"]
        if trend == "flat": continue
        # Uptrend: Bull Put Spread; Downtrend: Bear Call Spread
        sigma = (vix/100) / np.sqrt(52)
        T = 4/252
        K = rs(S, step)
        if trend == "up" and 40 <= rsi_val <= 65:
            # Bull Put: sell OTM put, buy lower put
            Ks = K - otm; Kb = Ks - wing
            credit = (bs(S,Ks,T,R,sigma,"P") - bs(S,Kb,T,R,sigma,"P")) * lot
            if credit <= 0: continue
            Se = df.iloc[th_pos]["close"]
            expiry_pnl = (max(0,Ks-Se) - max(0,Kb-Se)) * lot
        elif trend == "dn" and 35 <= rsi_val <= 60:
            # Bear Call: sell OTM call, buy higher call
            Ks = K + otm; Kb = Ks + wing
            credit = (bs(S,Ks,T,R,sigma,"C") - bs(S,Kb,T,R,sigma,"C")) * lot
            if credit <= 0: continue
            Se = df.iloc[th_pos]["close"]
            expiry_pnl = (max(0,Se-Ks) - max(0,Se-Kb)) * lot
        else:
            continue
        pnl = credit - expiry_pnl
        pnl = max(pnl, -(credit*sl))
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W6: Delta-Neutral Short Straddle with tight stop (flat weeks only)
# ══════════════════════════════════════════════════════════════════════════════
def w6_short_straddle(df, lot=75, step=50, cap=500_000, flat_pct=0.5, sl=1.3, vix_lo=12, vix_hi=16):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 0:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue
        flat = abs(row["ema5"]/row["ema20"]-1)*100 < flat_pct
        if not flat: continue

        sigma = (vix/100) / np.sqrt(52)
        T = 4/252
        K = rs(S, step)
        credit = (bs(S,K,T,R,sigma,"C") + bs(S,K,T,R,sigma,"P")) * lot
        if credit <= 0: continue

        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-K) + max(0,K-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -(credit*sl))
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W7: SENSEX Weekly BWB (lot=10, step=100)
# ══════════════════════════════════════════════════════════════════════════════
def w7_sensex_bwb(df, lot=10, step=100, cap=200_000, call_wing=500, put_wing=800,
                   flat_pct=0.8, sl=1.5):
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek <= 1:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or pd.isna(S): continue
        flat = abs(row["ema5"]/row["ema20"]-1)*100 < flat_pct
        if not flat or not (12 <= vix <= 22): continue

        sigma = (vix/100) / np.sqrt(52) * 1.15  # SENSEX ~15% more volatile
        T = 4/252
        K = rs(S, step)
        Kcu = K + call_wing;  Kpd = K - put_wing

        credit = (bs(S,K,T,R,sigma,"C") + bs(S,K,T,R,sigma,"P")
                  - bs(S,Kcu,T,R,sigma,"C") - bs(S,Kpd,T,R,sigma,"P")) * lot
        if credit <= 0: continue

        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se)) * lot
        pnl = credit - expiry_pnl
        pnl = max(pnl, -(credit*sl))
        trades.append({"pnl": round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# W8: Composite — run W1+W3+W5 simultaneously (3 small lots each, avoid double)
# ══════════════════════════════════════════════════════════════════════════════
def w8_composite(df, lot=75, step=50, cap=500_000):
    from collections import defaultdict
    week_pnls = defaultdict(float)
    # W1 (small lot)
    for t in w1_adaptive_ic(df, lot=25, step=step, cap=cap):
        week_pnls[t["date"]] += t["pnl"]
    # W3 (small lot) 
    for t in w3_theta_ic(df, lot=25, step=step, cap=cap):
        week_pnls["W3_"+str(len(week_pnls))] = t["pnl"]  # independent dates
    # W5 (small lot)
    for t in w5_directional_spread(df, lot=25, step=step, cap=cap):
        week_pnls["W5_"+str(len(week_pnls))] = t["pnl"]
    return [{"pnl": v} for v in week_pnls.values()]

# ══════════════════════════════════════════════════════════════════════════════
# Parameter Sweep for W1 (best strategy from existing)
# ══════════════════════════════════════════════════════════════════════════════
def sweep_w1(df, lot=75, step=50, cap=500_000):
    best = None
    best_score = 0
    configs_tried = 0
    # Fewer params to sweep for speed
    for sl in [1.5, 2.0, 2.5]:
        t = w1_adaptive_ic(df, lot=lot, step=step, cap=cap, sl_mult=sl)
        s = stats([x["pnl"] for x in t], cap)
        if s and s["trades"] >= 20:
            score = s["pf"] * s["wr_pct"] / max(s["dd_pct"], 0.1)
            if score > best_score:
                best_score = score
                best = {**s, "params": {"sl_mult": sl}}
        configs_tried += 1
    return best, configs_tried

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("OVERNIGHT REFINEMENT — NIFTY & SENSEX OPTIONS v3")
print("="*70)

results = {}

strategies = [
    ("W1_VIX_Adaptive_IC_NIFTY",    lambda: w1_adaptive_ic(ndf),           75,  500_000),
    ("W2_BrokenWing_Butterfly_NIFTY",lambda: w2_bwb(ndf),                  75,  500_000),
    ("W3_Theta_Decay_IC_NIFTY",      lambda: w3_theta_ic(ndf),             75,  500_000),
    ("W4_Spike_Reversion_NIFTY",     lambda: w4_spike_reversion(ndf),      75,  500_000),
    ("W5_Directional_Spread_NIFTY",  lambda: w5_directional_spread(ndf),   75,  500_000),
    ("W6_Short_Straddle_NIFTY",      lambda: w6_short_straddle(ndf),       75,  500_000),
    ("W7_SENSEX_BWB",                lambda: w7_sensex_bwb(sdf),           10,  200_000),
    ("W8_Composite_NIFTY",           lambda: w8_composite(ndf),            75,  500_000),
]

print("\n[Phase 1: Initial Backtest]")
for name, fn, lot, cap in strategies:
    print(f"  Running {name}…", end=" ", flush=True)
    try:
        t = fn()
        s = stats([x["pnl"] for x in t], cap)
        if s: s["window"] = "400d weekly"
        results[name] = s
        print_stats(name, s)
    except Exception as e:
        print(f"ERROR: {e}")
        results[name] = None

# ── Phase 2: sweep best strategies ────────────────────────────────────────────
print("\n[Phase 2: Parameter Sweep on W1 (VIX-Adaptive IC)]")
best_w1, n_configs = sweep_w1(ndf)
if best_w1:
    print(f"  Best W1 config ({n_configs} tested): sl_mult={best_w1['params']['sl_mult']}")
    print_stats("W1_OPTIMIZED", best_w1)
    results["W1_VIX_Adaptive_IC_NIFTY_OPTIMIZED"] = best_w1

# ── Phase 3: Sensex IC (adapt W1 for SENSEX) ─────────────────────────────────
print("\n[Phase 3: SENSEX Adaptive IC]")
def w1_sensex(df, lot=10, step=100, cap=200_000, sl_mult=2.0):
    rows = df.reset_index()
    trades = []
    for th_idx in thursdays(df):
        th_pos = df.index.get_loc(th_idx)
        mon_pos = None
        for back in range(1,5):
            if th_pos-back >= 0 and df.index[th_pos-back].dayofweek == 0:
                mon_pos = th_pos-back; break
        if mon_pos is None:
            for back in range(1,4):
                if th_pos-back >= 0: mon_pos = th_pos-back; break
        if mon_pos is None: continue
        row = df.iloc[mon_pos]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or pd.isna(S): continue
        regime = row["vol_regime"]
        if regime == "spike": continue
        sigma = (vix/100) / np.sqrt(52) * 1.15  # SENSEX premium
        T = 4/252
        K = rs(S, step)
        if regime == "low":    c_otm, p_otm, wing = 300, 300, 500
        elif regime == "mid":  c_otm, p_otm, wing = 400, 400, 600
        else:                  c_otm, p_otm, wing = 500, 500, 800
        Kc=K+c_otm; Kcw=Kc+wing; Kp=K-p_otm; Kpw=Kp-wing
        credit = (bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+
                  bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit <= 0: continue
        Se = df.iloc[th_pos]["close"]
        expiry_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnl = max(credit - expiry_pnl, -(credit*sl_mult))
        trades.append({"pnl": round(pnl,2)})
    return trades

t_sx = w1_sensex(sdf)
s_sx = stats([x["pnl"] for x in t_sx], 200_000)
if s_sx: s_sx["window"] = "400d weekly"
results["W9_SENSEX_Adaptive_IC"] = s_sx
print_stats("W9_SENSEX_Adaptive_IC", s_sx)

# ── Final Summary ─────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("FINAL SUMMARY — RANKED BY SCORE (PF × WR / DD)")
print("="*70)
scored = []
for name, s in results.items():
    if not s: continue
    score = s["pf"] * s["wr_pct"] / max(s["dd_pct"], 0.1)
    scored.append((score, name, s))
scored.sort(reverse=True)

print(f"\n{'Strategy':42s}  {'PF':>6} {'WR%':>6} {'DD%':>5} {'T':>4}  {'Net P&L':>12}  Score")
print("-"*95)
for score, name, s in scored:
    flag = "✅" if s["pf"]>2.5 and s["wr_pct"]>60 and s["dd_pct"]<3 else "⚠️"
    print(f"{flag} {name:40s}  {s['pf']:6.2f} {s['wr_pct']:6.1f} {s['dd_pct']:5.1f} {s['trades']:4d}  ₹{s['net_pnl']:>10,.0f}  {score:.1f}")

deploy_list = [(n,s) for _,n,s in scored if s["pf"]>2.5 and s["wr_pct"]>60 and s["dd_pct"]<3 and s["trades"]>=30]
print(f"\n🚀 DEPLOY-READY strategies: {len(deploy_list)}")
for n,s in deploy_list:
    print(f"   → {n}  PF={s['pf']}  WR={s['wr_pct']}%  DD={s['dd_pct']}%  T={s['trades']}")

# Save
out_path = "/Users/mac/sksoopenalgo/openalgo/overnight_options_v3_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved → {out_path}")
print("="*70)
