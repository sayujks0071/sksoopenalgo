#!/usr/bin/env python3
"""
OPTIONS v4 — Fix: Use MONTHLY options + bi-weekly entries
==========================================================
Root-cause of v3 failure:
  Weekly options (T=4/252) with 100pt OTM on NIFTY = 0.5% buffer
  Weekly NIFTY 1-SD move = VIX/100 * sqrt(1/52) * 22000 ≈ 460pts
  → strikes blown through 50%+ of the time → losses dominate

Fix:
  Use MONTHLY options (T=21/252 = 3 weeks avg DTE)
  Strike selection based on actual 1-SD weekly move formula
  Enter bi-weekly (every 2 Mon) to get 26 trades/year vs 12 before

Strategies:
  O1  Wide IC (rebuild of existing PF=7.51) — validate + add freq
  O2  Iron Butterfly (rebuild of existing PF=14.11) — validate
  O3  Bi-weekly Wide IC — enter every 2 weeks (↑ frequency)
  O4  VIX-Sized IC — strikes = 1.2× actual weekly SD
  O5  Trending Butterfly — asymmetric, direction from EMA20/50
  O6  NIFTY+BankNIFTY combo — diversified 2-leg premium book

NIFTY lot=75 | BANKNIFTY lot=15 | CAP=₹5L
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json

# ── Black-Scholes ─────────────────────────────────────────────────────────────
def bs(S, K, T, r, sigma, opt="C"):
    if T <= 0: return max(0, S-K) if opt=="C" else max(0, K-S)
    d1 = (np.log(S/K) + (r+0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def rs(s, step=50): return int(round(s/step)*step)

R = 0.065

# ── Data ──────────────────────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=500)

print("Fetching NIFTY + VIX + BankNIFTY…")
def fetch_daily(ticker):
    df = yf.download(ticker, start=START.strftime("%Y-%m-%d"),
                     end=END.strftime("%Y-%m-%d"), interval="1d",
                     auto_adjust=True, progress=False)
    df.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    return df[["open","high","low","close"]].dropna()

nifty  = fetch_daily("^NSEI")
bank   = fetch_daily("^NSEBANK")
vixdf  = fetch_daily("^INDIAVIX")[["close"]].rename(columns={"close":"vix"})

def prep(df):
    d = df.join(vixdf, how="inner")
    d.index = pd.to_datetime(d.index).tz_localize(None)
    d["ema5"]  = d["close"].ewm(span=5,  adjust=False).mean()
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    d["rsi"]   = _rsi(d["close"])
    d["realized_vol"] = d["close"].pct_change().rolling(10).std() * np.sqrt(252) * 100
    d["wk_range"] = (d["high"].rolling(5).max() - d["low"].rolling(5).min()) / d["close"] * 100
    d["vol_regime"] = pd.cut(d["vix"], bins=[0,13,17,22,100],
                              labels=["low","mid","high","spike"]).astype(str)
    d["trend"] = np.where(d["ema5"]>d["ema20"]*1.005, "up",
                 np.where(d["ema5"]<d["ema20"]*0.995, "dn", "flat"))
    d["dow"] = d.index.dayofweek
    return d

def _rsi(close, n=14):
    d=close.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    return 100-100/(1+g.ewm(com=n-1,min_periods=n).mean()/l.ewm(com=n-1,min_periods=n).mean().replace(0,np.nan))

ndf = prep(nifty)
bdf = prep(bank)
print(f"  NIFTY: {len(ndf)} days | BankNIFTY: {len(bdf)} days | VIX: {ndf['vix'].min():.1f}–{ndf['vix'].max():.1f}")

# ── Stats ─────────────────────────────────────────────────────────────────────
def stats(pnls, cap=500_000, label=""):
    if not pnls: return None
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    pf=round(sum(wins)/abs(sum(losses)),2) if losses else 99.
    wr=round(100*len(wins)/len(pnls),1)
    eq=cap+pd.Series(pnls).cumsum()
    dd=round(100*(eq.cummax()-eq).max()/eq.cummax().max(),2)
    return {"pf":pf,"wr_pct":wr,"dd_pct":dd,"trades":len(pnls),
            "net_pnl":round(sum(pnls)),"run_date":datetime.today().strftime("%Y-%m-%d"),
            "window":"500d monthly-options"}

def pprint(label, s):
    if not s: print(f"  ❌ {label}: no trades"); return
    ok = s["pf"]>2.5 and s["wr_pct"]>60 and s["dd_pct"]<3 and s["trades"]>=25
    flag = "✅" if ok else "⚠️" if s["pf"]>1.5 else "❌"
    print(f"  {flag} {label:40s} PF={s['pf']:6.2f} WR={s['wr_pct']:5.1f}% DD={s['dd_pct']:4.1f}% T={s['trades']:3d} Net=₹{s['net_pnl']:>10,.0f}")

# ── Entry calendar: every Monday ──────────────────────────────────────────────
def mondays(df): return [i for i in df.index if i.dayofweek==0]
def bi_mondays(df):
    mons = mondays(df)
    return mons[::2]  # every other Monday

# ── Simulate expiry: 3 weeks later (Mon+21 days) ─────────────────────────────
def get_expiry_price(df, entry_date, hold_days=21):
    """Return close price hold_days after entry_date."""
    try:
        pos = df.index.get_loc(entry_date)
        exp_pos = min(pos + hold_days, len(df)-1)
        return df.iloc[exp_pos]["close"]
    except: return None

# ══════════════════════════════════════════════════════════════════════════════
# O1: Wide IC — replicate existing PF=7.51 (monthly, sideways filter)
# ══════════════════════════════════════════════════════════════════════════════
def o1_wide_ic(df, lot=75, step=50, cap=500_000, c_otm=150, p_otm=150, wing=350,
               flat_pct=1.0, vix_lo=12, vix_hi=22, sl=2.0, hold_days=21):
    trades=[]
    for entry in mondays(df):
        pos = df.index.get_loc(entry)
        if pos < 25: continue
        row = df.loc[entry]
        S, vix = row["close"], row["vix"]
        if pd.isna(vix) or not (vix_lo <= vix <= vix_hi): continue
        flat = abs(row["ema5"]/row["ema20"]-1)*100 < flat_pct
        if not flat: continue
        sigma = (vix/100) / np.sqrt(52)
        T = hold_days/252
        K=rs(S,step); Kc=K+c_otm; Kcw=Kc+wing; Kp=K-p_otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+
                bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=0: continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnl=max(credit-exp_pnl, -(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O2: Iron Butterfly — replicate existing PF=14.11
# ══════════════════════════════════════════════════════════════════════════════
def o2_iron_butterfly(df, lot=75, step=50, cap=500_000, call_wing=250, put_wing=400,
                       flat_pct=0.5, vix_lo=12, vix_hi=22, sl=1.5, hold_days=21):
    trades=[]
    for entry in mondays(df):
        pos=df.index.get_loc(entry)
        if pos<25: continue
        row=df.loc[entry]
        S,vix=row["close"],row["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        flat=abs(row["ema5"]/row["ema20"]-1)*100<flat_pct
        if not flat: continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        K=rs(S,step); Kcu=K+call_wing; Kpd=K-put_wing
        credit=(bs(S,K,T,R,sigma,"C")+bs(S,K,T,R,sigma,"P")
                -bs(S,Kcu,T,R,sigma,"C")-bs(S,Kpd,T,R,sigma,"P"))*lot
        if credit<=0: continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O3: Bi-weekly Wide IC — same as O1 but enter every 2 weeks (2× frequency)
# ══════════════════════════════════════════════════════════════════════════════
def o3_biweekly_ic(df, lot=75, step=50, cap=500_000, c_otm=150, p_otm=150, wing=300,
                    flat_pct=1.5, vix_lo=11, vix_hi=22, sl=2.0, hold_days=14):
    trades=[]
    for entry in bi_mondays(df):
        pos=df.index.get_loc(entry)
        if pos<25: continue
        row=df.loc[entry]
        S,vix=row["close"],row["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        K=rs(S,step); Kc=K+c_otm; Kcw=Kc+wing; Kp=K-p_otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+
                bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=0: continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O4: VIX-Sized IC — strikes = 1.3× actual 1-SD weekly move
# ══════════════════════════════════════════════════════════════════════════════
def o4_vix_sized_ic(df, lot=75, step=50, cap=500_000, sd_mult=1.3, wing_mult=1.8,
                     vix_lo=11, vix_hi=22, sl=2.5, hold_days=21):
    trades=[]
    for entry in mondays(df):
        pos=df.index.get_loc(entry)
        if pos<25: continue
        row=df.loc[entry]
        S,vix=row["close"],row["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        # 1 SD 3-week move
        weekly_sd = vix/100 * np.sqrt(hold_days/252) * S
        otm = rs(weekly_sd*sd_mult, step)
        wing = rs(weekly_sd*wing_mult, step)
        if otm<50 or wing<otm: continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        K=rs(S,step); Kc=K+otm; Kcw=Kc+wing; Kp=K-otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+
                bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=0: continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O5: Asymmetric Butterfly (bearish tilt, Indian market has downside bias)
# Call wing = 1×SD, Put wing = 1.5×SD (wider downside protection)
# ══════════════════════════════════════════════════════════════════════════════
def o5_asymmetric_bfly(df, lot=75, step=50, cap=500_000, flat_pct=1.2,
                        call_sd=0.9, put_sd=1.3, vix_lo=12, vix_hi=20, sl=1.8, hold_days=21):
    trades=[]
    for entry in mondays(df):
        pos=df.index.get_loc(entry)
        if pos<25: continue
        row=df.loc[entry]
        S,vix=row["close"],row["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        flat=abs(row["ema5"]/row["ema20"]-1)*100<flat_pct
        if not flat: continue
        move = vix/100 * np.sqrt(hold_days/252) * S
        call_wing=rs(move*call_sd,step); put_wing=rs(move*put_sd,step)
        if call_wing<100 or put_wing<100: continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        K=rs(S,step); Kcu=K+call_wing; Kpd=K-put_wing
        credit=(bs(S,K,T,R,sigma,"C")+bs(S,K,T,R,sigma,"P")
                -bs(S,Kcu,T,R,sigma,"C")-bs(S,Kpd,T,R,sigma,"P"))*lot
        if credit<=0: continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-K)-max(0,Se-Kcu)+max(0,K-Se)-max(0,Kpd-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O6: NIFTY + BankNIFTY Dual IC (diversified 2-lot book)
# ══════════════════════════════════════════════════════════════════════════════
def o6_dual_ic(ndf, bdf, nifty_lot=75, bank_lot=15, step_n=50, step_b=100,
                cap=500_000, vix_lo=12, vix_hi=22, sl=2.0, hold_days=21):
    trades=[]
    nifty_mons=set(mondays(ndf))
    for entry in mondays(bdf):
        if entry not in nifty_mons: continue
        pos_n=ndf.index.get_loc(entry); pos_b=bdf.index.get_loc(entry)
        if pos_n<25 or pos_b<25: continue
        rn=ndf.loc[entry]; rb=bdf.loc[entry]
        Sn,Sb,vix=rn["close"],rb["close"],rn["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        # NIFTY IC
        Kn=rs(Sn,step_n); Kc=Kn+150; Kcw=Kc+300; Kp=Kn-150; Kpw=Kp-300
        cn=(bs(Sn,Kc,T,R,sigma,"C")-bs(Sn,Kcw,T,R,sigma,"C")+
            bs(Sn,Kp,T,R,sigma,"P")-bs(Sn,Kpw,T,R,sigma,"P"))*nifty_lot
        # BankNIFTY IC (wider, BN is more volatile)
        sv=sigma*1.3
        Kb=rs(Sb,step_b); KcB=Kb+300; KcwB=KcB+500; KpB=Kb-300; KpwB=KpB-500
        cb=(bs(Sb,KcB,T,R,sv,"C")-bs(Sb,KcwB,T,R,sv,"C")+
            bs(Sb,KpB,T,R,sv,"P")-bs(Sb,KpwB,T,R,sv,"P"))*bank_lot
        credit=cn+cb
        if credit<=0: continue
        Sen=get_expiry_price(ndf,entry,hold_days)
        Seb=get_expiry_price(bdf,entry,hold_days)
        if Sen is None or Seb is None: continue
        pnl_n=(max(0,Sen-Kc)-max(0,Sen-Kcw)+max(0,Kp-Sen)-max(0,Kpw-Sen))*nifty_lot
        pnl_b=(max(0,Seb-KcB)-max(0,Seb-KcwB)+max(0,KpB-Seb)-max(0,KpwB-Seb))*bank_lot
        pnl=max(credit-pnl_n-pnl_b, -(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# O7: Profit-Target Exit IC (take 60% credit quickly, re-enter)
# Simulates: if after 10 days the option value = 40% of original credit, take profit
# ══════════════════════════════════════════════════════════════════════════════
def o7_profit_target_ic(df, lot=75, step=50, cap=500_000, c_otm=150, p_otm=150, wing=350,
                         flat_pct=1.0, vix_lo=12, vix_hi=22, sl=2.0, hold_days=21, pt=0.60):
    trades=[]
    for entry in mondays(df):
        pos=df.index.get_loc(entry)
        if pos<25: continue
        row=df.loc[entry]
        S,vix=row["close"],row["vix"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        flat=abs(row["ema5"]/row["ema20"]-1)*100<flat_pct
        if not flat: continue
        sigma=(vix/100)/np.sqrt(52); T=hold_days/252
        K=rs(S,step); Kc=K+c_otm; Kcw=Kc+wing; Kp=K-p_otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+
                bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=0: continue
        # Check at 10 days: if spot still within range, take profit
        mid_price=get_expiry_price(df,entry,10)
        if mid_price:
            T_mid=(hold_days-10)/252
            remaining=(bs(mid_price,Kc,T_mid,R,sigma,"C")-bs(mid_price,Kcw,T_mid,R,sigma,"C")+
                       bs(mid_price,Kp,T_mid,R,sigma,"P")-bs(mid_price,Kpw,T_mid,R,sigma,"P"))*lot
            profit_now=credit-remaining
            if profit_now>=credit*pt:
                trades.append({"pnl":round(profit_now,2)}); continue
        Se=get_expiry_price(df,entry,hold_days)
        if Se is None: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnl=max(credit-exp_pnl,-(credit*sl))
        trades.append({"pnl":round(pnl,2)})
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("OPTIONS v4 — MONTHLY OPTIONS, CORRECTED STRIKE SIZING")
print("="*70)

results={}
tests=[
    ("O1_Wide_IC_NIFTY_Monthly",         lambda: o1_wide_ic(ndf)),
    ("O2_Iron_Butterfly_Monthly",         lambda: o2_iron_butterfly(ndf)),
    ("O3_BiWeekly_IC_NIFTY",             lambda: o3_biweekly_ic(ndf)),
    ("O4_VIX_Sized_IC",                  lambda: o4_vix_sized_ic(ndf)),
    ("O5_Asymmetric_Butterfly",          lambda: o5_asymmetric_bfly(ndf)),
    ("O6_Dual_NIFTY_BankNIFTY_IC",      lambda: o6_dual_ic(ndf,bdf)),
    ("O7_Profit_Target_IC",              lambda: o7_profit_target_ic(ndf)),
]

print("\n[Phase 1: Monthly Options Strategies]")
for name, fn in tests:
    print(f"  Running {name}…", end=" ", flush=True)
    try:
        t=fn(); s=stats([x["pnl"] for x in t])
        results[name]=s; pprint(name,s)
    except Exception as e:
        print(f"ERROR: {e}"); results[name]=None

# ── Phase 2: Sweep O1 (Wide IC) ───────────────────────────────────────────────
print("\n[Phase 2: Wide IC Parameter Sweep (c_otm, flat_pct, hold)]")
best=None; best_score=0; cnt=0
for c_otm in [100,150,200]:
    for flat in [0.8,1.0,1.5,2.0]:
        for hold in [14,21]:
            t=o1_wide_ic(ndf,c_otm=c_otm,p_otm=c_otm,flat_pct=flat,hold_days=hold)
            s=stats([x["pnl"] for x in t])
            cnt+=1
            if s and s["trades"]>=12:
                score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1)
                if score>best_score:
                    best_score=score
                    best={**s,"params":{"c_otm":c_otm,"flat_pct":flat,"hold":hold}}
if best:
    results["O1_Wide_IC_OPTIMIZED"]=best
    print(f"  Best ({cnt} configs): c_otm={best['params']['c_otm']}, flat={best['params']['flat_pct']}, hold={best['params']['hold']}d")
    pprint("O1_Wide_IC_OPTIMIZED",best)

# ── Phase 3: Sweep O2 (Iron Butterfly) ────────────────────────────────────────
print("\n[Phase 3: Iron Butterfly Parameter Sweep]")
best2=None; best2_score=0; cnt2=0
for flat in [0.3,0.5,0.8,1.0]:
    for call_w in [200,250,300]:
        for put_w in [300,400,500]:
            for sl in [1.3,1.5,2.0]:
                t=o2_iron_butterfly(ndf,flat_pct=flat,call_wing=call_w,put_wing=put_w,sl=sl)
                s=stats([x["pnl"] for x in t])
                cnt2+=1
                if s and s["trades"]>=8:
                    score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1)
                    if score>best2_score:
                        best2_score=score
                        best2={**s,"params":{"flat":flat,"call_w":call_w,"put_w":put_w,"sl":sl}}
if best2:
    results["O2_Iron_Butterfly_OPTIMIZED"]=best2
    p=best2["params"]
    print(f"  Best ({cnt2} configs): flat={p['flat']}, call_w={p['call_w']}, put_w={p['put_w']}, sl={p['sl']}")
    pprint("O2_Iron_Butterfly_OPTIMIZED",best2)

# ── Final table ────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("FINAL OPTIONS v4 RESULTS")
print("="*70)
scored=[(s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1),n,s)
        for n,s in results.items() if s]
scored.sort(reverse=True)
print(f"\n{'Strategy':42s} {'PF':>6} {'WR%':>6} {'DD%':>5} {'T':>4}  Net P&L")
print("-"*85)
for sc,n,s in scored:
    flag="✅" if s["pf"]>2.5 and s["wr_pct"]>60 and s["dd_pct"]<3 else "⚠️" if s["pf"]>1.5 else "❌"
    print(f"{flag} {n:40s} {s['pf']:6.2f} {s['wr_pct']:6.1f} {s['dd_pct']:5.1f} {s['trades']:4d}  ₹{s['net_pnl']:>10,.0f}")

deploy=[(n,s) for _,n,s in scored if s["pf"]>2.0 and s["wr_pct"]>55 and s["dd_pct"]<4 and s["trades"]>=15]
print(f"\n🚀 Deploy-ready options: {len(deploy)}")
for n,s in deploy:
    print(f"   → {n}  PF={s['pf']}  WR={s['wr_pct']}%  DD={s['dd_pct']}%  T={s['trades']}")

out="/Users/mac/sksoopenalgo/openalgo/overnight_options_v4_results.json"
with open(out,"w") as f: json.dump(results,f,indent=2)
print(f"\nSaved → {out}")
print("="*70)
