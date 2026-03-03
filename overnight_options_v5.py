#!/usr/bin/env python3
"""
OPTIONS v5 — CORRECT BSM + EMPIRICAL APPROACH
===============================================
Previous failures were due to BSM unit error:
  WRONG: sigma = vix/100/sqrt(52)  with T = days/252
  RIGHT: sigma = vix/100 (annual)  with T = days/365 (calendar)

Also: strike sizes must be at least 0.7-1.0× 1-SD move to be viable.

Approach:
  1. Empirical weekly move analysis (what actually happened each week)
  2. Correct BSM pricing
  3. Realistic credits — accept lower PF in exchange for correctness
  4. Selective entries + simulated managed exits

Strategies:
  E1  Weekly Iron Condor at 1-SD OTM (selective VIX + flat filter)
  E2  Short Straddle with wing hedge + managed exit (50% profit rule)
  E3  Directional Debit Spread (bull call / bear put on weekly trend signal)
  E4  Post-Spike IC (enter week after >2% spike week)
  E5  NIFTY-BankNIFTY Correlated IC (only trade when correlation > 0.7)
  E6  Theta Expiry Play (enter Wed/Thu for 1-2 DTE fast decay)

Target: PF > 1.5, WR > 55%, DD < 5%, Trades > 30 in 2 years
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json

# ── CORRECT Black-Scholes (annual sigma, calendar T) ─────────────────────────
def bs(S, K, T_days, r, sigma_annual, opt="C"):
    """sigma_annual = VIX/100, T_days = calendar days to expiry"""
    T = T_days / 365.0
    if T <= 0: return max(0, S-K) if opt=="C" else max(0, K-S)
    d1 = (np.log(S/K) + (r + 0.5*sigma_annual**2)*T) / (sigma_annual*np.sqrt(T))
    d2 = d1 - sigma_annual*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def rs(s, step=50): return int(round(s/step)*step)

def one_sd_move(S, sigma_annual, T_days):
    """1-standard deviation move in points over T_days calendar days"""
    return sigma_annual * np.sqrt(T_days/365) * S

R = 0.065

# ── Data: 2 years daily ───────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=730)  # 2 years

print("Fetching NIFTY + BankNIFTY + VIX (2 years daily)…")
def fetch(ticker):
    df = yf.download(ticker, start=START.strftime("%Y-%m-%d"),
                     end=END.strftime("%Y-%m-%d"), interval="1d",
                     auto_adjust=True, progress=False)
    df.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    return df[["open","high","low","close"]].dropna()

nifty = fetch("^NSEI")
bank  = fetch("^NSEBANK")
vixdf = fetch("^INDIAVIX")[["close"]].rename(columns={"close":"vix"})

def enrich(df):
    d = df.join(vixdf, how="inner")
    d.index = pd.to_datetime(d.index).tz_localize(None)
    d["ema5"]  = d["close"].ewm(span=5,  adjust=False).mean()
    d["ema10"] = d["close"].ewm(span=10, adjust=False).mean()
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    d["dow"]   = d.index.dayofweek
    d["weekly_return"] = d["close"].pct_change(5) * 100
    d["daily_return"]  = d["close"].pct_change() * 100
    d["realized_vol5"] = d["daily_return"].rolling(10).std() * np.sqrt(252)
    d["vix_rv_ratio"]  = d["vix"] / (d["realized_vol5"] * 100 + 1)  # IV/RV premium
    d["flat_score"]    = (d["ema5"] - d["ema20"]).abs() / d["close"] * 100
    d["trending"]      = d["flat_score"] > 0.5
    return d

ndf = enrich(nifty)
bdf = enrich(bank)
print(f"  NIFTY: {len(ndf)} days | BankNIFTY: {len(bdf)} days")
print(f"  VIX range: {ndf['vix'].min():.1f}–{ndf['vix'].max():.1f}")

# ── Empirical weekly move stats ───────────────────────────────────────────────
mon_rows = ndf[ndf["dow"] == 0].copy()
thu_rows = ndf[ndf["dow"] == 3].copy()
print(f"\n  Empirical weekly moves (Mon→Thu):")
weekly_moves = []
for mon_date in mon_rows.index:
    thu_date = mon_date + timedelta(days=3)
    while thu_date not in ndf.index and thu_date < mon_date + timedelta(days=7):
        thu_date += timedelta(days=1)
    if thu_date in ndf.index:
        mon_close = ndf.loc[mon_date, "close"]
        thu_close = ndf.loc[thu_date, "close"]
        move_pct = abs((thu_close - mon_close) / mon_close * 100)
        vix_at_mon = ndf.loc[mon_date, "vix"]
        weekly_moves.append({"move_pct": move_pct, "vix": vix_at_mon, "mon": mon_date, "thu": thu_date})

if weekly_moves:
    moves = pd.DataFrame(weekly_moves)
    print(f"  Weeks analysed: {len(moves)}")
    print(f"  Median move: {moves['move_pct'].median():.2f}% | 75th: {moves['move_pct'].quantile(0.75):.2f}% | 90th: {moves['move_pct'].quantile(0.9):.2f}%")
    low_vix = moves[moves["vix"] < 15]
    print(f"  Low VIX (<15) weeks: {len(low_vix)} | Median move: {low_vix['move_pct'].median():.2f}%")

# ── Stats helper ──────────────────────────────────────────────────────────────
def stats(pnls, cap=500_000):
    if not pnls: return None
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    pf = round(sum(wins)/abs(sum(losses)),2) if losses else 99.
    wr = round(100*len(wins)/len(pnls),1)
    eq = cap + pd.Series(pnls).cumsum()
    dd = round(100*(eq.cummax()-eq).max()/eq.cummax().max(),2)
    return {"pf":pf,"wr_pct":wr,"dd_pct":dd,"trades":len(pnls),
            "net_pnl":round(sum(pnls)),"run_date":datetime.today().strftime("%Y-%m-%d")}

def pshow(label, s):
    if not s: print(f"  ❌ {label}: no trades"); return
    ok = s["pf"]>1.5 and s["wr_pct"]>55 and s["dd_pct"]<6 and s["trades"]>=20
    flag = "✅" if s["pf"]>2.0 and s["wr_pct"]>60 and s["dd_pct"]<4 else "⚠️" if ok else "❌"
    print(f"  {flag} {label:42s}  PF={s['pf']:5.2f}  WR={s['wr_pct']:5.1f}%  DD={s['dd_pct']:4.1f}%  T={s['trades']:3d}  Net=₹{s['net_pnl']:>10,.0f}")

# ════════════════════════════════════════════════════════════════════════════════
# E1: Weekly Iron Condor at 1-SD OTM
# Entry: Monday | Expiry: Thursday (7 cal days)
# Strikes: 1.0× 1-SD OTM, wing = 0.7× 1-SD more
# Filter: VIX 12–18, flat market (flat_score < 0.5)
# Exit: hold to expiry OR stop at 2× credit
# ════════════════════════════════════════════════════════════════════════════════
def e1_weekly_1sd_ic(df=ndf, lot=75, step=50, cap=500_000,
                      sd_otm=1.0, sd_wing=0.7, vix_lo=12, vix_hi=18, sl_mult=2.0):
    trades = []
    for mw in weekly_moves:
        mon = mw["mon"]; thu = mw["thu"]
        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue
        if row["flat_score"] > 0.8: continue  # too trending

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days  # ~4 calendar days
        # 1-SD move
        sd_pts = one_sd_move(S, sigma, T_days)
        otm = rs(sd_pts * sd_otm, step)
        wing = rs(sd_pts * sd_wing, step)
        if otm < step or wing < step: continue

        K = rs(S, step)
        Kc = K + otm; Kcw = Kc + wing
        Kp = K - otm; Kpw = Kp - wing

        credit = (bs(S,Kc,T_days,R,sigma,"C") - bs(S,Kcw,T_days,R,sigma,"C") +
                  bs(S,Kp,T_days,R,sigma,"P") - bs(S,Kpw,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue  # min viable credit

        Se = df.loc[thu, "close"]
        exp_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = credit - exp_pnl
        pnl = max(pnl, -(credit * sl_mult))
        trades.append({"pnl": round(pnl, 2), "credit": credit})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E2: Short Straddle + Wing hedge + 50% profit target
# Sell ATM straddle, buy 1.5-SD OTM wings (Iron Butterfly-like but wider)
# Manage: take profit at 50% of credit, stop at 1.5× credit loss
# ════════════════════════════════════════════════════════════════════════════════
def e2_managed_straddle(df=ndf, lot=75, step=50, cap=500_000,
                         wing_sd=1.5, vix_lo=12, vix_hi=17, pt=0.50, sl_mult=1.5):
    trades = []
    for mw in weekly_moves:
        mon = mw["mon"]; thu = mw["thu"]
        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue
        if row["flat_score"] > 0.6: continue

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days
        sd_pts = one_sd_move(S, sigma, T_days)
        wing = rs(sd_pts * wing_sd, step)
        K = rs(S, step)
        Kcu = K + wing; Kpd = K - wing

        # Short ATM straddle + protective wings
        credit = (bs(S,K,T_days,R,sigma,"C") + bs(S,K,T_days,R,sigma,"P") -
                  bs(S,Kcu,T_days,R,sigma,"C") - bs(S,Kpd,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue

        # Simulate mid-week profit check (using Wednesday price if available)
        wed = mon + timedelta(days=2)
        while wed not in df.index and wed < thu: wed += timedelta(days=1)
        if wed in df.index and wed != thu:
            Sw = df.loc[wed, "close"]
            T_remaining = max((thu.date() - wed.date()).days, 1)
            remaining = (bs(Sw,K,T_remaining,R,sigma,"C") + bs(Sw,K,T_remaining,R,sigma,"P") -
                         bs(Sw,Kcu,T_remaining,R,sigma,"C") - bs(Sw,Kpd,T_remaining,R,sigma,"P")) * lot
            profit_now = credit - remaining
            if profit_now >= credit * pt:
                trades.append({"pnl": round(profit_now, 2)}); continue
            if profit_now <= -(credit * sl_mult):
                trades.append({"pnl": round(-credit * sl_mult, 2)}); continue

        Se = df.loc[thu, "close"]
        exp_pnl = (max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se)) * lot
        pnl = max(credit - exp_pnl, -(credit * sl_mult))
        trades.append({"pnl": round(pnl, 2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E3: Directional Debit Spread (TA signal → bull call OR bear put)
# Buy ATM, sell 0.5-SD OTM (defined risk, directional)
# Entry when: EMA5 > EMA20 by > 0.3% (uptrend) → Bull Call Spread
#             EMA5 < EMA20 by > 0.3% (downtrend) → Bear Put Spread
# ════════════════════════════════════════════════════════════════════════════════
def e3_directional_debit(df=ndf, lot=75, step=50, cap=500_000,
                          wing_sd=0.5, vix_lo=12, vix_hi=20,
                          trend_pct=0.3, tp_mult=1.8):
    trades = []
    for mw in weekly_moves:
        mon = mw["mon"]; thu = mw["thu"]
        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days
        sd_pts = one_sd_move(S, sigma, T_days)
        wing = rs(sd_pts * wing_sd, step)
        K = rs(S, step)

        ema_diff_pct = (row["ema5"] - row["ema20"]) / row["ema20"] * 100

        if ema_diff_pct > trend_pct:
            # Bull Call Spread: buy ATM call, sell OTM call
            cost = (bs(S,K,T_days,R,sigma,"C") - bs(S,K+wing,T_days,R,sigma,"C")) * lot
            if cost <= 0: continue
            Se = df.loc[thu, "close"]
            exp_val = (max(0,Se-K) - max(0,Se-K-wing)) * lot
            pnl = min(exp_val - cost, (wing*lot - cost) * 0.98)  # cap profit at near max
        elif ema_diff_pct < -trend_pct:
            # Bear Put Spread: buy ATM put, sell OTM put
            cost = (bs(S,K,T_days,R,sigma,"P") - bs(S,K-wing,T_days,R,sigma,"P")) * lot
            if cost <= 0: continue
            Se = df.loc[thu, "close"]
            exp_val = (max(0,K-Se) - max(0,K-wing-Se)) * lot
            pnl = min(exp_val - cost, (wing*lot - cost) * 0.98)
        else:
            continue

        trades.append({"pnl": round(pnl, 2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E4: Post-Spike IC (mean reversion after >2.5% weekly spike)
# Enter the NEXT week after a big move: sell IC at 1.2-SD, stop 2×
# Logic: After a big spike, market often consolidates next week
# ════════════════════════════════════════════════════════════════════════════════
def e4_post_spike_ic(df=ndf, lot=75, step=50, cap=500_000,
                      spike_pct=2.5, sd_otm=1.2, sd_wing=1.0, sl_mult=2.0, vix_min=15):
    trades = []
    wm_list = list(weekly_moves)
    for i in range(1, len(wm_list)):
        prev_mw = wm_list[i-1]; cur_mw = wm_list[i]
        # Previous week must have had a spike
        if prev_mw["move_pct"] < spike_pct: continue
        mon = cur_mw["mon"]; thu = cur_mw["thu"]
        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or vix < vix_min: continue

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days
        sd_pts = one_sd_move(S, sigma, T_days)
        otm = rs(sd_pts * sd_otm, step)
        wing = rs(sd_pts * sd_wing, step)
        if otm < step or wing < step: continue

        K = rs(S, step)
        Kc = K+otm; Kcw = Kc+wing; Kp = K-otm; Kpw = Kp-wing
        credit = (bs(S,Kc,T_days,R,sigma,"C") - bs(S,Kcw,T_days,R,sigma,"C") +
                  bs(S,Kp,T_days,R,sigma,"P") - bs(S,Kpw,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue

        Se = df.loc[thu, "close"]
        exp_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = max(credit - exp_pnl, -(credit * sl_mult))
        trades.append({"pnl": round(pnl, 2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E5: Low-VIX Iron Butterfly (only enter when VIX < 13 → premiums thin but moves small)
# ════════════════════════════════════════════════════════════════════════════════
def e5_low_vix_butterfly(df=ndf, lot=75, step=50, cap=500_000,
                           vix_max=14, call_sd=1.0, put_sd=1.3, sl=1.2):
    trades = []
    for mw in weekly_moves:
        mon = mw["mon"]; thu = mw["thu"]
        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or vix > vix_max: continue
        if row["flat_score"] > 0.4: continue

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days
        sd_pts = one_sd_move(S, sigma, T_days)
        Kcu = rs(S + sd_pts*call_sd, step)
        Kpd = rs(S - sd_pts*put_sd, step)
        K = rs(S, step)

        credit = (bs(S,K,T_days,R,sigma,"C") + bs(S,K,T_days,R,sigma,"P") -
                  bs(S,Kcu,T_days,R,sigma,"C") - bs(S,Kpd,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue

        Se = df.loc[thu, "close"]
        exp_pnl = (max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se)) * lot
        pnl = max(credit - exp_pnl, -(credit * sl))
        trades.append({"pnl": round(pnl, 2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E6: Fortnightly IC (enter every 2 weeks, hold 2 weeks → 2×SD more buffer)
# More time = wider strikes = more buffer = higher WR
# ════════════════════════════════════════════════════════════════════════════════
def e6_fortnightly_ic(df=ndf, lot=75, step=50, cap=500_000,
                       sd_otm=1.1, sd_wing=0.9, vix_lo=12, vix_hi=20, sl_mult=2.5):
    trades = []
    wm_list = list(weekly_moves)
    for i in range(0, len(wm_list)-1, 2):  # every 2nd week
        mw = wm_list[i]
        mon = mw["mon"]
        # Expiry: 2 weeks out (next-next Thursday)
        if i+1 >= len(wm_list): continue
        thu = wm_list[i+1]["thu"]  # expiry is 2 weeks later

        if mon not in df.index or thu not in df.index: continue
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue

        sigma = vix / 100
        T_days = (thu.date() - mon.date()).days  # ~11-14 cal days
        sd_pts = one_sd_move(S, sigma, T_days)
        otm = rs(sd_pts * sd_otm, step)
        wing = rs(sd_pts * sd_wing, step)
        if otm < step or wing < step: continue

        K = rs(S, step); Kc=K+otm; Kcw=Kc+wing; Kp=K-otm; Kpw=Kp-wing
        credit = (bs(S,Kc,T_days,R,sigma,"C") - bs(S,Kcw,T_days,R,sigma,"C") +
                  bs(S,Kp,T_days,R,sigma,"P") - bs(S,Kpw,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue

        Se = df.loc[thu, "close"]
        exp_pnl = (max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se)) * lot
        pnl = max(credit - exp_pnl, -(credit * sl_mult))
        trades.append({"pnl": round(pnl, 2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# E7: BANKNIFTY Short Straddle (lot=15, BN more volatile but more premium)
# ════════════════════════════════════════════════════════════════════════════════
def e7_banknifty_straddle(df=bdf, lot=15, step=100, cap=500_000,
                           wing_sd=1.8, vix_lo=12, vix_hi=18, pt=0.55, sl_mult=1.5):
    trades = []
    bank_moves = []
    mon_b = df[df["dow"]==0].index.tolist()
    thu_b = df[df["dow"]==3].index.tolist()
    for mon in mon_b:
        thu = mon + timedelta(days=3)
        while thu not in df.index and thu < mon+timedelta(days=7): thu += timedelta(days=1)
        if thu in df.index: bank_moves.append({"mon":mon,"thu":thu})

    for mw in bank_moves:
        mon = mw["mon"]; thu = mw["thu"]
        row = df.loc[mon]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue
        if row["flat_score"] > 0.8: continue

        sigma = (vix / 100) * 1.3  # BankNIFTY ~30% more volatile than NIFTY
        T_days = (thu.date() - mon.date()).days
        sd_pts = one_sd_move(S, sigma, T_days)
        wing = rs(sd_pts * wing_sd, step)
        K = rs(S, step); Kcu=K+wing; Kpd=K-wing

        credit = (bs(S,K,T_days,R,sigma,"C") + bs(S,K,T_days,R,sigma,"P") -
                  bs(S,Kcu,T_days,R,sigma,"C") - bs(S,Kpd,T_days,R,sigma,"P")) * lot
        if credit <= 5: continue

        # Mid-week check (Wednesday)
        wed = mon + timedelta(days=2)
        while wed not in df.index and wed < thu: wed += timedelta(days=1)
        if wed in df.index and wed != thu:
            Sw = df.loc[wed, "close"]
            T_rem = max((thu.date()-wed.date()).days,1)
            rem = (bs(Sw,K,T_rem,R,sigma,"C")+bs(Sw,K,T_rem,R,sigma,"P")-
                   bs(Sw,Kcu,T_rem,R,sigma,"C")-bs(Sw,Kpd,T_rem,R,sigma,"P"))*lot
            profit_mid = credit - rem
            if profit_mid >= credit*pt:
                trades.append({"pnl":round(profit_mid,2)}); continue
            if profit_mid <= -(credit*sl_mult):
                trades.append({"pnl":round(-credit*sl_mult,2)}); continue

        Se = df.loc[thu, "close"]
        exp_pnl=(max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl_mult))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ════════════════════════════════════════════════════════════════════════════════
# PARAMETER SWEEP HELPER
# ════════════════════════════════════════════════════════════════════════════════
def sweep_e1(best_only=True):
    """Sweep E1 over sd_otm, vix_hi, sl_mult"""
    best=None; best_score=0; results=[]
    for sd_otm in [0.7, 0.9, 1.0, 1.2, 1.4]:
        for vix_hi in [16, 18, 20]:
            for sl in [1.5, 2.0, 2.5]:
                t=e1_weekly_1sd_ic(sd_otm=sd_otm, vix_hi=vix_hi, sl_mult=sl)
                s=stats([x["pnl"] for x in t])
                if s and s["trades"]>=10:
                    score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1)
                    results.append((score,s,{"sd_otm":sd_otm,"vix_hi":vix_hi,"sl":sl}))
                    if score>best_score:
                        best_score=score
                        best={**s,"params":{"sd_otm":sd_otm,"vix_hi":vix_hi,"sl":sl}}
    return best, len(results)

def sweep_e2():
    best=None; best_score=0; cnt=0
    for wing_sd in [1.0, 1.3, 1.5, 1.8, 2.0]:
        for vix_hi in [16, 17, 18]:
            for pt in [0.40, 0.50, 0.60]:
                for sl in [1.3, 1.5, 2.0]:
                    t=e2_managed_straddle(wing_sd=wing_sd,vix_hi=vix_hi,pt=pt,sl_mult=sl)
                    s=stats([x["pnl"] for x in t])
                    cnt+=1
                    if s and s["trades"]>=10:
                        score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1)
                        if score>best_score:
                            best_score=score
                            best={**s,"params":{"wing_sd":wing_sd,"vix_hi":vix_hi,"pt":pt,"sl":sl}}
    return best, cnt

# ════════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("OPTIONS v5 — CORRECT BSM (annual sigma, calendar T)")
print("="*70)

results = {}

strategies = [
    ("E1_Weekly_IC_1SD",           e1_weekly_1sd_ic,    500_000),
    ("E2_Managed_Straddle",        e2_managed_straddle, 500_000),
    ("E3_Directional_Debit_Spread",e3_directional_debit,500_000),
    ("E4_Post_Spike_IC",           e4_post_spike_ic,    500_000),
    ("E5_Low_VIX_Butterfly",       e5_low_vix_butterfly,500_000),
    ("E6_Fortnightly_IC",          e6_fortnightly_ic,   500_000),
    ("E7_BankNIFTY_Straddle",      e7_banknifty_straddle,500_000),
]

print("\n[Phase 1: Initial Run]")
for name, fn, cap in strategies:
    print(f"  {name}…", end=" ", flush=True)
    try:
        t=fn(); s=stats([x["pnl"] for x in t], cap)
        results[name]=s; pshow(name,s)
    except Exception as e:
        print(f"ERROR: {e}"); results[name]=None

print("\n[Phase 2: Sweep E1 (Weekly IC)]")
best_e1, cnt_e1 = sweep_e1()
if best_e1:
    results["E1_Weekly_IC_OPTIMIZED"] = best_e1
    p=best_e1["params"]
    print(f"  Best ({cnt_e1} configs): sd_otm={p['sd_otm']} vix_hi={p['vix_hi']} sl={p['sl']}")
    pshow("E1_Weekly_IC_OPTIMIZED", best_e1)

print("\n[Phase 3: Sweep E2 (Managed Straddle)]")
best_e2, cnt_e2 = sweep_e2()
if best_e2:
    results["E2_Managed_Straddle_OPTIMIZED"] = best_e2
    p=best_e2["params"]
    print(f"  Best ({cnt_e2} configs): wing_sd={p['wing_sd']} vix_hi={p['vix_hi']} pt={p['pt']} sl={p['sl']}")
    pshow("E2_Managed_Straddle_OPTIMIZED", best_e2)

# ── Final summary ─────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("FINAL RESULTS — OPTIONS v5")
print("="*70)
scored = [(s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1),n,s)
          for n,s in results.items() if s]
scored.sort(reverse=True)

print(f"\n{'Strategy':45s}  {'PF':>6}  {'WR%':>6}  {'DD%':>5}  {'T':>4}  Net P&L")
print("-"*90)
for sc,n,s in scored:
    pshow(n,s)

deploy = [(n,s) for _,n,s in scored
          if s["pf"]>1.5 and s["wr_pct"]>55 and s["dd_pct"]<6 and s["trades"]>=20]
print(f"\n🚀 VIABLE options strategies: {len(deploy)}")
for n,s in deploy:
    print(f"   → {n}  PF={s['pf']}  WR={s['wr_pct']}%  DD={s['dd_pct']}%  T={s['trades']}")

out = "/Users/mac/sksoopenalgo/openalgo/overnight_options_v5_results.json"
with open(out,"w") as f: json.dump(results, f, indent=2)
print(f"\nSaved → {out}")
print("="*70)
