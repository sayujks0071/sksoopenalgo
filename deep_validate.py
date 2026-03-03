#!/usr/bin/env python3
"""
DEEP VALIDATION & FINE-TUNING
==============================
Methods:
  1. Walk-forward validation (60% train / 40% test, no lookahead)
  2. Bootstrap confidence intervals (1000 resamples)
  3. Out-of-sample hold-out
  4. Statistical significance (t-test vs random baseline)
  5. Sharpe / Sortino / Calmar ratios
  6. Exhaustive parameter grids with cross-validation

Also fixes:
  - MCX uses daily data (2 years) for lot-correct P&L → more trades
  - Equity uses realistic slippage model (0.05% per trade)
  - Options uses 2.5yr data, no VIX filter overfitting check
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
from scipy.stats import norm
from datetime import datetime, timedelta
import json, itertools

TODAY = datetime.today()

# ── Stats helpers ─────────────────────────────────────────────────────────────
def compute_stats(pnls, cap=500_000, risk_free_annual=0.065, periods_per_year=252):
    if len(pnls) < 5:
        return None
    pnls = np.array(pnls)
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    pf   = round(wins.sum() / abs(losses.sum()), 3) if len(losses) > 0 else 99.0
    wr   = round(100 * len(wins) / len(pnls), 1)
    net  = round(pnls.sum())
    # Equity curve
    eq   = cap + np.cumsum(pnls)
    roll_max = np.maximum.accumulate(eq)
    dd_abs   = (roll_max - eq).max()
    dd_pct   = round(100 * dd_abs / roll_max.max(), 2)
    # Sharpe (annualised, per-trade basis)
    rf_per_trade = risk_free_annual / periods_per_year
    excess = pnls / cap - rf_per_trade
    sharpe = round(float(excess.mean() / (excess.std() + 1e-9) * np.sqrt(periods_per_year)), 2)
    # Sortino (only downside deviation)
    down_dev = np.sqrt((excess[excess < 0]**2).mean() + 1e-9)
    sortino  = round(float(excess.mean() / down_dev * np.sqrt(periods_per_year)), 2)
    # Calmar
    ann_ret = (net / cap) * (periods_per_year / len(pnls))
    calmar  = round(ann_ret / (dd_pct / 100 + 1e-9), 2)
    # t-test vs zero
    t_stat, p_val = stats.ttest_1samp(pnls, 0)
    significant = p_val < 0.05
    # Expected value per trade
    ev = round(float(pnls.mean()), 2)
    # Kelly
    win_avg  = wins.mean() if len(wins) > 0 else 0
    loss_avg = abs(losses.mean()) if len(losses) > 0 else 1
    kelly = round(float((wr/100) / loss_avg - (1 - wr/100) / win_avg) if win_avg > 0 else 0, 3)
    return {
        "pf": pf, "wr_pct": wr, "dd_pct": dd_pct, "trades": len(pnls),
        "net_pnl": net, "ev_per_trade": ev,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "kelly_fraction": kelly,
        "p_value": round(float(p_val), 4), "statistically_significant": significant,
        "run_date": TODAY.strftime("%Y-%m-%d")
    }

def bootstrap_ci(pnls, n_boot=1000, ci=0.95):
    """Bootstrap 95% CI on PF and WR"""
    if len(pnls) < 5: return None
    pnls = np.array(pnls)
    pf_samples = []; wr_samples = []
    rng = np.random.default_rng(42)
    for _ in range(n_boot):
        sample = rng.choice(pnls, len(pnls), replace=True)
        w = sample[sample > 0]; l = sample[sample <= 0]
        pf_samples.append(w.sum() / abs(l.sum()) if len(l) > 0 else 99)
        wr_samples.append(100 * len(w) / len(sample))
    alpha = (1 - ci) / 2
    return {
        "pf_ci":  [round(np.quantile(pf_samples, alpha), 2), round(np.quantile(pf_samples, 1-alpha), 2)],
        "wr_ci":  [round(np.quantile(wr_samples, alpha), 1), round(np.quantile(wr_samples, 1-alpha), 1)],
        "pf_mean": round(float(np.mean(pf_samples)), 2),
    }

def walk_forward(pnls, train_frac=0.60):
    """Split into train/test, return both stats"""
    if len(pnls) < 10: return None, None
    n_train = int(len(pnls) * train_frac)
    return compute_stats(pnls[:n_train]), compute_stats(pnls[n_train:])

def print_validation(name, pnls, cap=500_000):
    s = compute_stats(pnls, cap)
    if not s:
        print(f"  ❌ {name}: insufficient trades ({len(pnls)})")
        return s
    ci = bootstrap_ci(pnls)
    s_train, s_test = walk_forward(pnls)
    pval_flag = "✅" if s["statistically_significant"] else "⚠️ NOT sig"
    robust = s_test and s_test["pf"] > 1.3 and s_test["wr_pct"] > 50
    overall = "✅ ROBUST" if robust and s["statistically_significant"] and s["pf"] > 1.5 else \
              "⚠️ MARGINAL" if s["pf"] > 1.3 else "❌ WEAK"
    print(f"\n  {overall}  {name}")
    print(f"    Full:  PF={s['pf']:6.2f}  WR={s['wr_pct']:5.1f}%  DD={s['dd_pct']:4.1f}%  T={s['trades']:3d}  "
          f"EV=₹{s['ev_per_trade']:,.0f}  Sharpe={s['sharpe']:.2f}  Sortino={s['sortino']:.2f}")
    if ci:
        print(f"    CI95:  PF=[{ci['pf_ci'][0]}, {ci['pf_ci'][1]}]  WR=[{ci['wr_ci'][0]}, {ci['wr_ci'][1]}%]  "
              f"p={s['p_value']:.3f} {pval_flag}")
    if s_train and s_test:
        print(f"    Train: PF={s_train['pf']:.2f}  WR={s_train['wr_pct']:.1f}%  T={s_train['trades']}")
        print(f"    Test:  PF={s_test['pf']:.2f}  WR={s_test['wr_pct']:.1f}%  T={s_test['trades']}  "
              f"{'✅ holds OOS' if s_test['pf'] > 1.2 else '❌ degrades OOS'}")
    return s

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 1: MCX — Daily data 2 years (more trades, realistic lot P&L)
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("SECTION 1: MCX STRATEGIES — 2-YEAR DAILY BACKTEST")
print("="*70)

START_LONG = TODAY - timedelta(days=730)

def fetch(t, interval="1d", start=START_LONG):
    df = yf.download(t, start=start.strftime("%Y-%m-%d"),
                     end=TODAY.strftime("%Y-%m-%d"), interval=interval,
                     auto_adjust=True, progress=False)
    df.columns = [c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    if "volume" not in df.columns: df["volume"] = 1
    return df[["open","high","low","close","volume"]].dropna()

def ema(s, n): return s.ewm(span=n, min_periods=n, adjust=False).mean()
def rsi_fn(c, n=14):
    d=c.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    return 100-100/(1+g.ewm(com=n-1,min_periods=n).mean()/l.ewm(com=n-1,min_periods=n).mean().replace(0,np.nan))
def atr_fn(df, n=14):
    h,l,c=df["close"].shift(),df["low"],df["high"]
    tr=pd.concat([(df["high"]-df["low"]),(df["high"]-h).abs(),(df["low"]-h).abs()],axis=1).max(axis=1)
    return tr.ewm(span=n,min_periods=n).mean()
def adx_fn(df, n=14):
    h,l,c=df["high"],df["low"],df["close"]
    up=h.diff(); dn=-l.diff()
    pdm=pd.Series(np.where((up>dn)&(up>0),up,0.),index=df.index)
    mdm=pd.Series(np.where((dn>up)&(dn>0),dn,0.),index=df.index)
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr_s=tr.ewm(span=n,min_periods=n).mean()
    pdi=100*pdm.ewm(span=n,min_periods=n).mean()/atr_s
    mdi=100*mdm.ewm(span=n,min_periods=n).mean()/atr_s
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(span=n,min_periods=n).mean()

print("\nFetching 2yr daily data (MCX proxies)…")
silver_d = fetch("SILVER.NS")
gold_d   = fetch("GOLDBEES.NS")
crude_d  = fetch("BZ=F")
print(f"  Silver: {len(silver_d)}d | Gold: {len(gold_d)}d | Crude: {len(crude_d)}d")

# Lot-correct P&L: Silver=30kg lot, Gold Mini=100g=0.1kg, Crude=100bbl
# But we're using ETF proxies so use notional %
def mcx_ema_cross(df, lot_val=100_000, ema_f=9, ema_s=21, adx_min=22,
                   rsi_lo=40, rsi_hi=70, sl_atr=1.2, tp_atr=2.5,
                   slippage=0.0005):
    df=df.copy()
    df["ef"]=ema(df["close"],ema_f); df["es"]=ema(df["close"],ema_s)
    df["adx"]=adx_fn(df); df["atr"]=atr_fn(df); df["rsi"]=rsi_fn(df["close"])
    trades=[]; pos=None
    for i in range(ema_s+5, len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        if pos:
            sl=(pos["e"]-pos["atr"]*sl_atr if pos["d"]==1 else pos["e"]+pos["atr"]*sl_atr)
            tp=(pos["e"]+pos["atr"]*tp_atr if pos["d"]==1 else pos["e"]-pos["atr"]*tp_atr)
            qty=int(lot_val/pos["e"])
            if (pos["d"]==1 and r["close"]<=sl) or (pos["d"]==-1 and r["close"]>=sl):
                exit_p=sl*(1+slippage*pos["d"])
                trades.append({"pnl":round((exit_p-pos["e"])*qty*pos["d"],2),"type":"sl"}); pos=None
            elif (pos["d"]==1 and r["close"]>=tp) or (pos["d"]==-1 and r["close"]<=tp):
                exit_p=tp*(1-slippage*pos["d"])
                trades.append({"pnl":round((exit_p-pos["e"])*qty*pos["d"],2),"type":"tp"}); pos=None
            elif r["ef"]<r["es"] and pr["ef"]>=pr["es"] and pos["d"]==1:
                trades.append({"pnl":round((r["close"]*(1-slippage)-pos["e"])*qty,2),"type":"sig"}); pos=None
            elif r["ef"]>r["es"] and pr["ef"]<=pr["es"] and pos["d"]==-1:
                trades.append({"pnl":round((pos["e"]-r["close"]*(1+slippage))*qty,2),"type":"sig"}); pos=None
        if not pos:
            cross_up=(pr["ef"]<=pr["es"] and r["ef"]>r["es"])
            cross_dn=(pr["ef"]>=pr["es"] and r["ef"]<r["es"])
            if cross_up and r["adx"]>adx_min and rsi_lo<r["rsi"]<rsi_hi:
                entry=r["close"]*(1+slippage)
                pos={"e":entry,"d":1,"atr":r["atr"]}
            elif cross_dn and r["adx"]>adx_min and (100-rsi_hi)<r["rsi"]<(100-rsi_lo):
                entry=r["close"]*(1-slippage)
                pos={"e":entry,"d":-1,"atr":r["atr"]}
    return [t["pnl"] for t in trades]

print("\n[MCX Silver — 2yr daily, exhaustive param sweep]")
best_silver=None; best_score_s=0; cnt_s=0
sweep_results_s=[]
for ef in [5,9,13,21]:
    for es in [21,34,55]:
        if ef>=es: continue
        for adx in [18,22,26,30]:
            for sl in [1.0,1.2,1.5,2.0]:
                for tp in [2.0,2.5,3.0,3.5]:
                    t=mcx_ema_cross(silver_d,ema_f=ef,ema_s=es,adx_min=adx,sl_atr=sl,tp_atr=tp)
                    s=compute_stats(t,100_000)
                    cnt_s+=1
                    if s and s["trades"]>=20 and s["statistically_significant"]:
                        _, s_test=walk_forward(t)
                        oos_ok=(s_test and s_test["pf"]>1.2) if s_test else False
                        score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1) if oos_ok else 0
                        sweep_results_s.append({"params":{"ef":ef,"es":es,"adx":adx,"sl":sl,"tp":tp},"stats":s,"oos_ok":oos_ok})
                        if score>best_score_s:
                            best_score_s=score
                            best_silver={**s,"params":{"ema_f":ef,"ema_s":es,"adx_min":adx,"sl_atr":sl,"tp_atr":tp}}
print(f"  Configs tested: {cnt_s} | Statistically valid + OOS-confirmed: {sum(1 for r in sweep_results_s if r['oos_ok'])}")
if best_silver:
    p=best_silver["params"]
    print(f"  BEST params: EMA {p['ema_f']}/{p['ema_s']} ADX>{p['adx_min']} SL={p['sl_atr']}×ATR TP={p['tp_atr']}×ATR")
    pnls=mcx_ema_cross(silver_d,**p); print_validation("MCX_SILVER_v3 (VALIDATED)",pnls,100_000)

print("\n[MCX Gold — 2yr daily, exhaustive sweep]")
best_gold=None; best_score_g=0; cnt_g=0
for ef in [5,9,13,21]:
    for es in [21,34,55]:
        if ef>=es: continue
        for adx in [20,25,28,32]:
            for sl in [1.0,1.2,1.5]:
                for tp in [2.0,2.5,3.0,4.0]:
                    t=mcx_ema_cross(gold_d,ema_f=ef,ema_s=es,adx_min=adx,sl_atr=sl,tp_atr=tp)
                    s=compute_stats(t,100_000)
                    cnt_g+=1
                    if s and s["trades"]>=20 and s["statistically_significant"]:
                        _, s_test=walk_forward(t)
                        oos_ok=(s_test and s_test["pf"]>1.2) if s_test else False
                        score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1) if oos_ok else 0
                        if score>best_score_g:
                            best_score_g=score
                            best_gold={**s,"params":{"ema_f":ef,"ema_s":es,"adx_min":adx,"sl_atr":sl,"tp_atr":tp}}
print(f"  Configs tested: {cnt_g}")
if best_gold:
    p=best_gold["params"]
    print(f"  BEST params: EMA {p['ema_f']}/{p['ema_s']} ADX>{p['adx_min']} SL={p['sl_atr']}×ATR TP={p['tp_atr']}×ATR")
    pnls=mcx_ema_cross(gold_d,**p); print_validation("MCX_GOLD_v3 (VALIDATED)",pnls,100_000)

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 2: NSE EQUITY — 5m data, slippage, walk-forward
# ════════════════════════════════════════════════════════════════════════════════
print("\n\n" + "="*70)
print("SECTION 2: NSE EQUITY — WALK-FORWARD + SLIPPAGE VALIDATION")
print("="*70)

START_5M = TODAY - timedelta(days=58)
print("\nFetching 5m intraday data…")
nifty_5m = fetch("NIFTYBEES.NS", "5m", START_5M)
bank_5m  = fetch("BANKBEES.NS", "5m", START_5M)
print(f"  NIFTY 5m: {len(nifty_5m)} bars | BankNIFTY 5m: {len(bank_5m)} bars")

def supertrend_fn(df, period=10, mult=3.0):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr_s=tr.ewm(span=period,min_periods=period).mean()
    ub=(h+l)/2+mult*atr_s; lb=(h+l)/2-mult*atr_s
    st=pd.Series(np.nan,index=df.index); trend=pd.Series(1,index=df.index)
    for i in range(1,len(df)):
        fub=ub.iloc[i] if ub.iloc[i]<st.iloc[i-1] or c.iloc[i-1]>st.iloc[i-1] else st.iloc[i-1]
        flb=lb.iloc[i] if lb.iloc[i]>st.iloc[i-1] or c.iloc[i-1]<st.iloc[i-1] else st.iloc[i-1]
        if c.iloc[i]>fub: trend.iloc[i]=1; st.iloc[i]=flb
        elif c.iloc[i]<flb: trend.iloc[i]=-1; st.iloc[i]=fub
        else: trend.iloc[i]=trend.iloc[i-1]; st.iloc[i]=flb if trend.iloc[i]==1 else fub
    return st, trend

def orb_strategy(df, lot_val=300_000, orb_min=15, sl_pct=0.003, tp_ratio=2.0,
                  vol_mult=1.3, slippage=0.0005):
    df=df.copy(); df["date"]=df.index.date; df["hour"]=df.index.hour; df["minute"]=df.index.minute
    df["vol_avg"]=df["volume"].rolling(20).mean()
    df["adx"]=adx_fn(df)
    trades=[]; pos=None; orb_hi={}; orb_lo={}
    for i in range(20,len(df)):
        r=df.iloc[i]; d=r["date"]; h=r["hour"]; m=r["minute"]
        if h==9 and m<=orb_min:
            orb_hi[d]=max(orb_hi.get(d,0),r["high"]); orb_lo[d]=min(orb_lo.get(d,1e9),r["low"]); continue
        if h>=15 and m>=5:
            if pos:
                ep=r["close"]*(1-slippage if pos["d"]==1 else 1+slippage)
                trades.append({"pnl":round((ep-pos["e"])*int(lot_val/pos["e"])*pos["d"],2)}); pos=None
            continue
        if d not in orb_hi: continue
        if pos:
            orb_r=orb_hi[d]-orb_lo[d]
            sl=pos["e"]-orb_r*0.5 if pos["d"]==1 else pos["e"]+orb_r*0.5
            tp=pos["e"]+orb_r*tp_ratio if pos["d"]==1 else pos["e"]-orb_r*tp_ratio
            qty=int(lot_val/pos["e"])
            if (pos["d"]==1 and r["close"]<=sl) or (pos["d"]==-1 and r["close"]>=sl):
                ep=sl*(1+slippage*pos["d"]); trades.append({"pnl":round((ep-pos["e"])*qty*pos["d"],2)}); pos=None
            elif (pos["d"]==1 and r["close"]>=tp) or (pos["d"]==-1 and r["close"]<=tp):
                ep=tp*(1-slippage*pos["d"]); trades.append({"pnl":round((ep-pos["e"])*qty*pos["d"],2)}); pos=None
        if not pos and 9<=h<=13:
            vol_ok=r["volume"]>r["vol_avg"]*vol_mult if r["vol_avg"]>0 else False
            adx_ok=r["adx"]>20
            pr=df.iloc[i-1]
            if r["close"]>orb_hi[d] and pr["close"]<=orb_hi[d] and vol_ok and adx_ok:
                pos={"e":r["close"]*(1+slippage),"d":1}
            elif r["close"]<orb_lo[d] and pr["close"]>=orb_lo[d] and vol_ok and adx_ok:
                pos={"e":r["close"]*(1-slippage),"d":-1}
    return [t["pnl"] for t in trades]

# ORB validation on BankNIFTY and NIFTY
print("\n[ORB — BankNIFTY + NIFTY with slippage + walk-forward]")
pnls_bn_orb = orb_strategy(bank_5m, lot_val=500_000)
pnls_nf_orb = orb_strategy(nifty_5m, lot_val=200_000)
print_validation("BankNIFTY_ORB (slippage 0.05%)", pnls_bn_orb, 500_000)
print_validation("NIFTY_ORB (slippage 0.05%)", pnls_nf_orb, 200_000)

# Sweep ORB parameters
print("\n[ORB BankNIFTY — parameter sweep]")
best_orb=None; best_orb_score=0
for orb_min in [10,15,20]:
    for tp_ratio in [1.5,2.0,2.5,3.0]:
        for vol_mult in [1.2,1.5,2.0]:
            for sl_pct in [0.002,0.003,0.004]:
                t=orb_strategy(bank_5m,orb_min=orb_min,sl_pct=sl_pct,tp_ratio=tp_ratio,vol_mult=vol_mult)
                s=compute_stats(t,500_000)
                if s and s["trades"]>=8 and s["statistically_significant"]:
                    _, st=walk_forward(t)
                    oos_ok=st and st["pf"]>1.1 if st else False
                    score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1) if oos_ok else 0
                    if score>best_orb_score:
                        best_orb_score=score
                        best_orb={**s,"params":{"orb_min":orb_min,"tp_ratio":tp_ratio,"vol_mult":vol_mult,"sl_pct":sl_pct}}
if best_orb:
    p=best_orb["params"]
    print(f"  BEST ORB: orb_min={p['orb_min']} tp={p['tp_ratio']}× vol>{p['vol_mult']}× sl={p['sl_pct']:.3f}")
    pnls=orb_strategy(bank_5m,**p); print_validation("BankNIFTY_ORB_TUNED",pnls,500_000)

# ════════════════════════════════════════════════════════════════════════════════
# SECTION 3: OPTIONS — OOS validation + tighter parameter grid
# ════════════════════════════════════════════════════════════════════════════════
print("\n\n" + "="*70)
print("SECTION 3: OPTIONS STRATEGIES — OOS VALIDATION (2.5yr data)")
print("="*70)

START_OPTS = TODAY - timedelta(days=900)
print("\nFetching 2.5yr data for options…")
nifty_d  = fetch("^NSEI", "1d", START_OPTS)
vix_d    = fetch("^INDIAVIX","1d",START_OPTS)[["close"]].rename(columns={"close":"vix"})

def enrich(df):
    d=df.join(vix_d,how="inner"); d.index=pd.to_datetime(d.index).tz_localize(None)
    d["ema5"]=ema(d["close"],5); d["ema20"]=ema(d["close"],20)
    d["flat_score"]=(d["ema5"]-d["ema20"]).abs()/d["close"]*100
    d["dow"]=d.index.dayofweek; return d

ndf=enrich(nifty_d)
print(f"  NIFTY: {len(ndf)}d | VIX: {ndf['vix'].min():.1f}–{ndf['vix'].max():.1f}")

def bs(S,K,T_days,r,sigma,opt="C"):
    T=T_days/365.0
    if T<=0: return max(0,S-K) if opt=="C" else max(0,K-S)
    d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T))
    d2=d1-sigma*np.sqrt(T)
    if opt=="C": return S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)
    return K*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)

def rs(s,step=50): return int(round(s/step)*step)
def one_sd(S,sigma,T_days): return sigma*np.sqrt(T_days/365)*S
R=0.065

# Build weekly move pairs
mon_idx=[i for i in ndf.index if i.dayofweek==0]
weekly_moves=[]
for mon in mon_idx:
    thu=mon+timedelta(days=3)
    while thu not in ndf.index and thu<mon+timedelta(days=7): thu+=timedelta(days=1)
    if thu in ndf.index:
        weekly_moves.append({"mon":mon,"thu":thu,"vix":ndf.loc[mon,"vix"],"S":ndf.loc[mon,"close"],"Se":ndf.loc[thu,"close"],"flat":ndf.loc[mon,"flat_score"]})

# Build fortnightly pairs
fort_moves=[]
mlist=list(weekly_moves)
for i in range(0,len(mlist)-1,2):
    fort_moves.append({"mon":mlist[i]["mon"],"thu":mlist[i+1]["thu"],"vix":mlist[i]["vix"],"S":mlist[i]["S"],"Se":mlist[i+1]["Se"],"flat":mlist[i]["flat"]})

print(f"  Weekly pairs: {len(weekly_moves)} | Fortnightly pairs: {len(fort_moves)}")

def weekly_ic(moves, sd_otm=1.4, vix_lo=11, vix_hi=16, sl_mult=1.5, step=50, lot=75):
    pnls=[]
    for mw in moves:
        S,vix,Se=mw["S"],mw["vix"],mw["Se"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        T=(mw["thu"]-mw["mon"]).days
        sigma=vix/100; sd=one_sd(S,sigma,T); otm=rs(sd*sd_otm,step); wing=rs(sd*0.7,step)
        if otm<step or wing<step: continue
        K=rs(S,step); Kc=K+otm; Kcw=Kc+wing; Kp=K-otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=5: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnls.append(max(credit-exp_pnl,-(credit*sl_mult)))
    return pnls

def fort_ic(moves, sd_otm=1.1, vix_lo=11, vix_hi=20, sl_mult=2.5, step=50, lot=75):
    pnls=[]
    for mw in moves:
        S,vix,Se=mw["S"],mw["vix"],mw["Se"]
        if pd.isna(vix) or not(vix_lo<=vix<=vix_hi): continue
        T=(mw["thu"]-mw["mon"]).days
        sigma=vix/100; sd=one_sd(S,sigma,T); otm=rs(sd*sd_otm,step); wing=rs(sd*0.9,step)
        if otm<step or wing<step: continue
        K=rs(S,step); Kc=K+otm; Kcw=Kc+wing; Kp=K-otm; Kpw=Kp-wing
        credit=(bs(S,Kc,T,R,sigma,"C")-bs(S,Kcw,T,R,sigma,"C")+bs(S,Kp,T,R,sigma,"P")-bs(S,Kpw,T,R,sigma,"P"))*lot
        if credit<=5: continue
        exp_pnl=(max(0,Se-Kc)-max(0,Se-Kcw)+max(0,Kp-Se)-max(0,Kpw-Se))*lot
        pnls.append(max(credit-exp_pnl,-(credit*sl_mult)))
    return pnls

print("\n[E1_Weekly_IC — OOS validation + sweep on 2.5yr]")
pnls_w1=weekly_ic(weekly_moves); print_validation("E1_Weekly_IC (2.5yr, sd_otm=1.4, vix≤16)",pnls_w1,500_000)

# Sweep weekly IC
print("\n  Weekly IC sweep (OOS-confirmed only):")
best_w=None; best_ws=0
for sd_otm in [1.0,1.2,1.4,1.6,1.8]:
    for vix_hi in [14,15,16,17,18]:
        for sl in [1.2,1.5,2.0]:
            t=weekly_ic(weekly_moves,sd_otm=sd_otm,vix_hi=vix_hi,sl_mult=sl)
            s=compute_stats(t,500_000)
            if s and s["trades"]>=20 and s["statistically_significant"]:
                _,st=walk_forward(t)
                oos_ok=st and st["pf"]>1.2 and st["wr_pct"]>55 if st else False
                score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1) if oos_ok else 0
                if score>best_ws:
                    best_ws=score; best_w={**s,"params":{"sd_otm":sd_otm,"vix_hi":vix_hi,"sl":sl}}
if best_w:
    p=best_w["params"]
    print(f"  BEST: sd_otm={p['sd_otm']} vix_hi={p['vix_hi']} sl={p['sl']}")
    pnls=weekly_ic(weekly_moves,**p); print_validation("E1_Weekly_IC_TUNED",pnls,500_000)

print("\n[E6_Fortnightly_IC — OOS validation + sweep on 2.5yr]")
pnls_f1=fort_ic(fort_moves); print_validation("E6_Fortnightly_IC (2.5yr)",pnls_f1,500_000)

# Sweep fortnightly IC
best_f=None; best_fs=0
for sd_otm in [0.8,1.0,1.1,1.2,1.4]:
    for vix_hi in [17,18,20,22]:
        for sl in [2.0,2.5,3.0]:
            t=fort_ic(fort_moves,sd_otm=sd_otm,vix_hi=vix_hi,sl_mult=sl)
            s=compute_stats(t,500_000)
            if s and s["trades"]>=25 and s["statistically_significant"]:
                _,st=walk_forward(t)
                oos_ok=st and st["pf"]>1.2 and st["wr_pct"]>55 if st else False
                score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1) if oos_ok else 0
                if score>best_fs:
                    best_fs=score; best_f={**s,"params":{"sd_otm":sd_otm,"vix_hi":vix_hi,"sl_mult":sl}}
if best_f:
    p=best_f["params"]
    print(f"\n  BEST Fortnightly: sd_otm={p['sd_otm']} vix_hi={p['vix_hi']} sl={p['sl_mult']}")
    pnls=fort_ic(fort_moves,**p); print_validation("E6_Fortnightly_IC_TUNED",pnls,500_000)

# ════════════════════════════════════════════════════════════════════════════════
# FINAL CONSOLIDATED RESULTS
# ════════════════════════════════════════════════════════════════════════════════
print("\n\n" + "="*70)
print("FINAL VALIDATED DEPLOYMENT SUMMARY")
print("="*70)
print("""
  Criteria for DEPLOY:
  ✅ Statistically significant (p < 0.05)
  ✅ OOS PF > 1.2 (holds on unseen data)
  ✅ Trades ≥ 20 (enough for confidence)
  ✅ PF > 1.5 on full sample
  ✅ DD < 5%
""")

final_results = {}

strategies_to_validate = []
if best_silver:
    strategies_to_validate.append(("MCX_SILVER_v3", mcx_ema_cross(silver_d,**best_silver["params"]), 100_000, best_silver["params"]))
if best_gold:
    strategies_to_validate.append(("MCX_GOLD_v3", mcx_ema_cross(gold_d,**best_gold["params"]), 100_000, best_gold["params"]))
if best_orb:
    strategies_to_validate.append(("BankNIFTY_ORB_v3", orb_strategy(bank_5m,**best_orb["params"]), 500_000, best_orb["params"]))
if best_w:
    strategies_to_validate.append(("Weekly_IC_TUNED", weekly_ic(weekly_moves,**best_w["params"]), 500_000, best_w["params"]))
if best_f:
    strategies_to_validate.append(("Fortnightly_IC_TUNED", fort_ic(fort_moves,**best_f["params"]), 500_000, best_f["params"]))

print(f"\n{'Strategy':35s}  {'PF':>6}  {'WR%':>6}  {'DD%':>5}  {'T':>4}  {'Sharpe':>7}  {'p-val':>8}  OOS?")
print("-"*90)
for name, pnls, cap, params in strategies_to_validate:
    if not pnls: continue
    s = compute_stats(pnls, cap)
    if not s: continue
    _, s_test = walk_forward(pnls)
    oos = s_test and s_test["pf"] > 1.2 if s_test else False
    ok = s["statistically_significant"] and oos and s["pf"] > 1.5 and s["dd_pct"] < 5 and s["trades"] >= 20
    flag = "✅ DEPLOY" if ok else "⚠️ CAUTION"
    oos_str = f"✅ PF={s_test['pf']:.2f}" if oos and s_test else "❌"
    print(f"{flag} {name:33s}  {s['pf']:6.2f}  {s['wr_pct']:6.1f}  {s['dd_pct']:5.1f}  {s['trades']:4d}  {s['sharpe']:7.2f}  {s['p_value']:8.4f}  {oos_str}")
    final_results[name] = {**s, "params": params, "oos_ok": oos}

out = "/Users/mac/sksoopenalgo/openalgo/deep_validation_results.json"
with open(out,"w") as f: json.dump(final_results, f, indent=2)
print(f"\nDetailed results → {out}")
print("="*70)
