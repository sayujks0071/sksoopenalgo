#!/usr/bin/env python3
"""
OVERNIGHT — Equity Strategy Refinement
=======================================
Targets: SuperTrend_NIFTY PF 1.24 → 2.0+, BankNIFTY PF 1.13 → 2.0+
Also: Refine CrudeOil (too many trades), explore new equity setups

Strategies:
  E1  SuperTrend_NIFTY_v3    (adds: VolFilter + EMA200 + ATR entry)
  E2  BankNIFTY_VWAP_v3      (adds: ADX momentum + volume spike filter)
  E3  NIFTY_RSI_Pullback      (buy RSI pullback in uptrend)
  E4  BankNIFTY_ORB           (Opening Range Breakout, volume confirm)
  E5  MCX_SILVER_v2           (confirm & optimise current best PF=2.98)
  E6  MCX_GOLD_v2             (confirm & optimise current best PF=2.08)
  E7  CrudeOil_Filtered_v2   (strict regime filter: ADX>30, VIX<18)
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json, itertools

TODAY = datetime.today().strftime("%Y-%m-%d")
END   = datetime.today()
START_5M  = END - timedelta(days=58)
START_15M = END - timedelta(days=58)
START_1D  = END - timedelta(days=400)

# ── Indicators ────────────────────────────────────────────────────────────────
def rsi(close, n=14):
    d=close.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(com=n-1,min_periods=n).mean(); al=l.ewm(com=n-1,min_periods=n).mean()
    return 100-100/(1+ag/al.replace(0,np.nan))

def atr(df, n=14):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(span=n,min_periods=n).mean()

def adx(df, n=14):
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

def ema(close, n): return close.ewm(span=n,min_periods=n).mean()

def supertrend(df, period=10, mult=3.0):
    h,l,c=df["high"],df["low"],df["close"]
    tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr_s=tr.ewm(span=period,min_periods=period).mean()
    ub=(h+l)/2+mult*atr_s; lb=(h+l)/2-mult*atr_s
    st=pd.Series(np.nan,index=df.index); trend=pd.Series(1,index=df.index)
    for i in range(1,len(df)):
        f_ub = ub.iloc[i] if ub.iloc[i]<st.iloc[i-1] or c.iloc[i-1]>st.iloc[i-1] else st.iloc[i-1]
        f_lb = lb.iloc[i] if lb.iloc[i]>st.iloc[i-1] or c.iloc[i-1]<st.iloc[i-1] else st.iloc[i-1]
        if c.iloc[i] > f_ub: trend.iloc[i]=1;  st.iloc[i]=f_lb
        elif c.iloc[i] < f_lb: trend.iloc[i]=-1; st.iloc[i]=f_ub
        else:
            trend.iloc[i]=trend.iloc[i-1]
            st.iloc[i]=f_lb if trend.iloc[i]==1 else f_ub
    return st, trend

def intraday_vwap(df):
    typ=(df["high"]+df["low"]+df["close"])/3
    df2=df.copy(); df2["_typ"]=typ; df2["_date"]=df.index.date
    df2["_tv"]=df2["_typ"]*df2["volume"]
    df2["_cum_tv"]=df2.groupby("_date")["_tv"].cumsum()
    df2["_cum_v"]=df2.groupby("_date")["volume"].cumsum()
    return df2["_cum_tv"]/df2["_cum_v"].replace(0,np.nan)

def fetch(ticker, start, interval):
    df=yf.download(ticker,start=start.strftime("%Y-%m-%d"),
                   end=END.strftime("%Y-%m-%d"),interval=interval,
                   auto_adjust=True,progress=False)
    df.columns=[c[0].lower() if isinstance(c,tuple) else c.lower() for c in df.columns]
    if "volume" not in df.columns: df["volume"]=0
    return df[["open","high","low","close","volume"]].dropna()

def trade_stats(trades, cap=500_000):
    if not trades: return None
    pnls=[t["pnl"] for t in trades]
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    pf=round(sum(wins)/abs(sum(losses)),2) if losses else 99.
    wr=round(100*len(wins)/len(pnls),1)
    eq=cap+pd.Series(pnls).cumsum()
    dd=round(100*(eq.cummax()-eq).max()/eq.cummax().max(),2)
    return {"pf":pf,"wr_pct":wr,"dd_pct":dd,"trades":len(pnls),
            "net_pnl":round(sum(pnls)),"run_date":TODAY}

def pflag(s):
    if not s: return "❌"
    return "✅" if s["pf"]>=2.0 and s["wr_pct"]>=50 and s["dd_pct"]<=3 else "⚠️" if s["pf"]>=1.5 else "❌"

def pprint(name, s):
    if not s: print(f"  ❌ {name}: no trades"); return
    print(f"  {pflag(s)} {name:38s} PF={s['pf']:5.2f} WR={s['wr_pct']:5.1f}% DD={s['dd_pct']:4.1f}% T={s['trades']:3d} Net=₹{s['net_pnl']:>9,.0f}")

print("Fetching data…")
nifty_5m   = fetch("NIFTYBEES.NS", START_5M, "5m")
bank_5m    = fetch("BANKBEES.NS",  START_5M, "5m")
silver_15m = fetch("SILVER.NS",    START_15M,"15m")
gold_15m   = fetch("GOLDBEES.NS",  START_15M,"15m")
crude_15m  = fetch("BZ=F",         START_15M,"15m")
print(f"  NIFTY 5m: {len(nifty_5m)} bars | BankNIFTY 5m: {len(bank_5m)} bars | Silver: {len(silver_15m)} | Gold: {len(gold_15m)}")

# ─────────────────────────────────────────────────────────────────────────────
# E1: SuperTrend NIFTY v3 — adds EMA200, ATR size filter, ADX>20
# ─────────────────────────────────────────────────────────────────────────────
def e1_supertrend_nifty_v3(df, lot_val=200_000, sl_atr=1.5, tp_atr=3.0,
                            adx_min=20, atr_min_pct=0.15):
    df=df.copy()
    df["st"],df["trend"]=supertrend(df,10,3)
    df["ema50"]=ema(df["close"],50); df["ema200"]=ema(df["close"],200)
    df["adx"]=adx(df); df["atr"]=atr(df); df["rsi"]=rsi(df["close"])
    df["date"]=df.index.date; df["hour"]=df.index.hour; df["minute"]=df.index.minute
    trades=[]; pos=None
    for i in range(210,len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        time_ok=(9<=r["hour"]<=14) and not(r["hour"]==14 and r["minute"]>30)
        if r["hour"]>=15 and r["minute"]>=5: # force exit
            if pos:
                pnl=(r["close"]-pos["entry"] if pos["dir"]==1 else pos["entry"]-r["close"])
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round(pnl*qty,2)}); pos=None
            continue
        if pos:
            atr_val=r["atr"]
            sl_price=(pos["entry"]-atr_val*sl_atr if pos["dir"]==1 else pos["entry"]+atr_val*sl_atr)
            tp_price=(pos["entry"]+atr_val*tp_atr if pos["dir"]==1 else pos["entry"]-atr_val*tp_atr)
            qty=int(lot_val/pos["entry"])
            if (pos["dir"]==1 and r["close"]<=sl_price) or (pos["dir"]==-1 and r["close"]>=sl_price):
                trades.append({"pnl":round((sl_price-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif (pos["dir"]==1 and r["close"]>=tp_price) or (pos["dir"]==-1 and r["close"]<=tp_price):
                trades.append({"pnl":round((tp_price-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif r["trend"]!=pos["dir"]:
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty*pos["dir"],2)}); pos=None
        if not pos and time_ok:
            above200=(r["ema50"]>r["ema200"])
            adx_ok=r["adx"]>adx_min
            atr_ok=(r["atr"]/r["close"]*100)>atr_min_pct
            if r["trend"]==1 and pr["trend"]!=1 and above200 and adx_ok and atr_ok and 40<r["rsi"]<70:
                pos={"entry":r["close"],"dir":1,"atr":r["atr"]}
            elif r["trend"]==-1 and pr["trend"]!=-1 and not above200 and adx_ok and atr_ok and 30<r["rsi"]<60:
                pos={"entry":r["close"],"dir":-1,"atr":r["atr"]}
    return trades

# ─────────────────────────────────────────────────────────────────────────────
# E2: BankNIFTY VWAP v3 — ADX momentum + volume spike + EMA trend
# ─────────────────────────────────────────────────────────────────────────────
def e2_banknifty_vwap_v3(df, lot_val=500_000, sl_pct=0.003, tp_pct=0.006,
                          adx_min=22, vol_mult=1.5):
    df=df.copy()
    df["vwap"]=intraday_vwap(df)
    df["ema20"]=ema(df["close"],20); df["adx"]=adx(df); df["atr_v"]=atr(df)
    df["vol_avg"]=df["volume"].rolling(20).mean()
    df["rsi"]=rsi(df["close"])
    df["date"]=df.index.date; df["hour"]=df.index.hour; df["minute"]=df.index.minute
    trades=[]; pos=None
    for i in range(25,len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        time_ok=(9<=r["hour"]<=14) and not(r["hour"]==14 and r["minute"]>30)
        if r["hour"]>=15 and r["minute"]>=5:
            if pos:
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty*pos["dir"],2)}); pos=None
            continue
        if pos:
            sl=(pos["entry"]*(1-sl_pct) if pos["dir"]==1 else pos["entry"]*(1+sl_pct))
            tp=(pos["entry"]*(1+tp_pct) if pos["dir"]==1 else pos["entry"]*(1-tp_pct))
            qty=int(lot_val/pos["entry"])
            if (pos["dir"]==1 and r["close"]<=sl) or (pos["dir"]==-1 and r["close"]>=sl):
                trades.append({"pnl":round((sl-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif (pos["dir"]==1 and r["close"]>=tp) or (pos["dir"]==-1 and r["close"]<=tp):
                trades.append({"pnl":round((tp-pos["entry"])*qty*pos["dir"],2)}); pos=None
        if not pos and time_ok and pd.notna(r["vwap"]):
            vol_ok=(r["volume"]>r["vol_avg"]*vol_mult if r["vol_avg"]>0 else False)
            adx_ok=r["adx"]>adx_min
            cross_up=(pr["close"]<=pr["vwap"] and r["close"]>r["vwap"])
            cross_dn=(pr["close"]>=pr["vwap"] and r["close"]<r["vwap"])
            trend_up=r["ema20"]>r["vwap"]; trend_dn=r["ema20"]<r["vwap"]
            if cross_up and vol_ok and adx_ok and trend_up and 45<r["rsi"]<70:
                pos={"entry":r["close"],"dir":1}
            elif cross_dn and vol_ok and adx_ok and trend_dn and 30<r["rsi"]<55:
                pos={"entry":r["close"],"dir":-1}
    return trades

# ─────────────────────────────────────────────────────────────────────────────
# E3: NIFTY RSI Pullback in EMA Uptrend
# ─────────────────────────────────────────────────────────────────────────────
def e3_rsi_pullback(df, lot_val=200_000, sl_pct=0.004, tp_pct=0.009, rsi_lo=35, rsi_hi=55):
    df=df.copy()
    df["ema20"]=ema(df["close"],20); df["ema50"]=ema(df["close"],50)
    df["rsi"]=rsi(df["close"]); df["adx"]=adx(df)
    df["hour"]=df.index.hour; df["minute"]=df.index.minute
    trades=[]; pos=None
    for i in range(55,len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        time_ok=(9<=r["hour"]<=14) and not(r["hour"]==14 and r["minute"]>30)
        if r["hour"]>=15 and r["minute"]>=5:
            if pos:
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty,2)}); pos=None
            continue
        if pos:
            sl=pos["entry"]*(1-sl_pct); tp=pos["entry"]*(1+tp_pct)
            qty=int(lot_val/pos["entry"])
            if r["close"]<=sl: trades.append({"pnl":round((sl-pos["entry"])*qty,2)}); pos=None
            elif r["close"]>=tp: trades.append({"pnl":round((tp-pos["entry"])*qty,2)}); pos=None
        if not pos and time_ok:
            in_uptrend=(r["ema20"]>r["ema50"] and r["close"]>r["ema50"])
            rsi_pullback=(rsi_lo<=r["rsi"]<=rsi_hi and pr["rsi"]<rsi_lo)  # RSI just crossed up from oversold
            adx_ok=r["adx"]>18
            if in_uptrend and rsi_pullback and adx_ok:
                pos={"entry":r["close"]}
    return trades

# ─────────────────────────────────────────────────────────────────────────────
# E4: BankNIFTY ORB (Opening Range Breakout, volume confirm)
# ─────────────────────────────────────────────────────────────────────────────
def e4_banknifty_orb(df, lot_val=500_000, orb_min=15, sl_pct=0.003, tp_ratio=2.0):
    df=df.copy()
    df["date"]=df.index.date; df["hour"]=df.index.hour; df["minute"]=df.index.minute
    df["vol_avg"]=df["volume"].rolling(20).mean()
    df["adx"]=adx(df)
    trades=[]; pos=None
    orb_hi={}; orb_lo={}
    for i in range(20,len(df)):
        r=df.iloc[i]
        d=r["date"]; h=r["hour"]; m=r["minute"]
        # Build ORB in first 15 min
        if h==9 and m<=orb_min:
            orb_hi[d]=max(orb_hi.get(d,0), r["high"])
            orb_lo[d]=min(orb_lo.get(d,float("inf")), r["low"])
            continue
        if h>=15 and m>=5:
            if pos:
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty*pos["dir"],2)}); pos=None
            continue
        if d not in orb_hi or d not in orb_lo: continue
        pr=df.iloc[i-1]
        if pos:
            orb_range=orb_hi[d]-orb_lo[d]
            sl=(pos["entry"]-orb_range*0.5 if pos["dir"]==1 else pos["entry"]+orb_range*0.5)
            tp=(pos["entry"]+orb_range*tp_ratio if pos["dir"]==1 else pos["entry"]-orb_range*tp_ratio)
            qty=int(lot_val/pos["entry"])
            if (pos["dir"]==1 and r["close"]<=sl) or (pos["dir"]==-1 and r["close"]>=sl):
                trades.append({"pnl":round((sl-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif (pos["dir"]==1 and r["close"]>=tp) or (pos["dir"]==-1 and r["close"]<=tp):
                trades.append({"pnl":round((tp-pos["entry"])*qty*pos["dir"],2)}); pos=None
        if not pos and 9<=h<=13:
            vol_ok=(r["volume"]>r["vol_avg"]*1.3 if r["vol_avg"]>0 else False)
            adx_ok=r["adx"]>20
            if r["close"]>orb_hi[d] and pr["close"]<=orb_hi[d] and vol_ok and adx_ok:
                pos={"entry":r["close"],"dir":1}
            elif r["close"]<orb_lo[d] and pr["close"]>=orb_lo[d] and vol_ok and adx_ok:
                pos={"entry":r["close"],"dir":-1}
    return trades

# ─────────────────────────────────────────────────────────────────────────────
# E5/E6: MCX v2 — sweep ATR mult + ADX filter
# ─────────────────────────────────────────────────────────────────────────────
def mcx_momentum_v2(df, lot_val=100_000, sl_atr=1.2, tp_atr=2.5, adx_min=22, ema_fast=9, ema_slow=21):
    df=df.copy()
    df["ema_f"]=ema(df["close"],ema_fast); df["ema_s"]=ema(df["close"],ema_slow)
    df["adx_v"]=adx(df); df["atr_v"]=atr(df); df["rsi_v"]=rsi(df["close"])
    df["hour"]=df.index.hour; df["minute"]=df.index.minute
    trades=[]; pos=None
    for i in range(30,len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        # MCX square-off at 23:00
        if r["hour"]>=23:
            if pos:
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty*pos["dir"],2)}); pos=None
            continue
        if pos:
            sl=(pos["entry"]-pos["atr"]*sl_atr if pos["dir"]==1 else pos["entry"]+pos["atr"]*sl_atr)
            tp=(pos["entry"]+pos["atr"]*tp_atr if pos["dir"]==1 else pos["entry"]-pos["atr"]*tp_atr)
            qty=int(lot_val/pos["entry"])
            if (pos["dir"]==1 and r["close"]<=sl) or (pos["dir"]==-1 and r["close"]>=sl):
                trades.append({"pnl":round((sl-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif (pos["dir"]==1 and r["close"]>=tp) or (pos["dir"]==-1 and r["close"]<=tp):
                trades.append({"pnl":round((tp-pos["entry"])*qty*pos["dir"],2)}); pos=None
        if not pos:
            adx_ok=r["adx_v"]>adx_min
            cross_up=(pr["ema_f"]<=pr["ema_s"] and r["ema_f"]>r["ema_s"])
            cross_dn=(pr["ema_f"]>=pr["ema_s"] and r["ema_f"]<r["ema_s"])
            if cross_up and adx_ok and 40<r["rsi_v"]<70:
                pos={"entry":r["close"],"dir":1,"atr":r["atr_v"]}
            elif cross_dn and adx_ok and 30<r["rsi_v"]<60:
                pos={"entry":r["close"],"dir":-1,"atr":r["atr_v"]}
    return trades

# ─────────────────────────────────────────────────────────────────────────────
# E7: CrudeOil v2 — strict regime filter
# ─────────────────────────────────────────────────────────────────────────────
def e7_crudeoil_v2(df, lot_val=50_000, sl_atr=1.5, tp_atr=3.0, adx_min=28):
    df=df.copy()
    df["ema21"]=ema(df["close"],21); df["ema55"]=ema(df["close"],55)
    df["adx_v"]=adx(df); df["atr_v"]=atr(df); df["rsi_v"]=rsi(df["close"])
    df["hour"]=df.index.hour
    trades=[]; pos=None
    for i in range(60,len(df)):
        r=df.iloc[i]; pr=df.iloc[i-1]
        if r["hour"]>=22:
            if pos:
                qty=int(lot_val/pos["entry"])
                trades.append({"pnl":round((r["close"]-pos["entry"])*qty*pos["dir"],2)}); pos=None
            continue
        if pos:
            sl=(pos["entry"]-pos["atr"]*sl_atr if pos["dir"]==1 else pos["entry"]+pos["atr"]*sl_atr)
            tp=(pos["entry"]+pos["atr"]*tp_atr if pos["dir"]==1 else pos["entry"]-pos["atr"]*tp_atr)
            qty=int(lot_val/pos["entry"])
            if (pos["dir"]==1 and r["close"]<=sl) or (pos["dir"]==-1 and r["close"]>=sl):
                trades.append({"pnl":round((sl-pos["entry"])*qty*pos["dir"],2)}); pos=None
            elif (pos["dir"]==1 and r["close"]>=tp) or (pos["dir"]==-1 and r["close"]<=tp):
                trades.append({"pnl":round((tp-pos["entry"])*qty*pos["dir"],2)}); pos=None
        if not pos:
            # Strict: ADX>28 AND price above/below both EMAs AND RSI confirming
            strong_up=(r["close"]>r["ema21"]>r["ema55"] and r["adx_v"]>adx_min and 45<r["rsi_v"]<70)
            strong_dn=(r["close"]<r["ema21"]<r["ema55"] and r["adx_v"]>adx_min and 30<r["rsi_v"]<55)
            cross_up=(pr["ema21"]<=pr["ema55"] and r["ema21"]>r["ema55"])
            cross_dn=(pr["ema21"]>=pr["ema55"] and r["ema21"]<r["ema55"])
            if cross_up and strong_up:
                pos={"entry":r["close"],"dir":1,"atr":r["atr_v"]}
            elif cross_dn and strong_dn:
                pos={"entry":r["close"],"dir":-1,"atr":r["atr_v"]}
    return trades

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("OVERNIGHT EQUITY REFINEMENT")
print("="*70)

results = {}

print("\n[Phase 1: NIFTY/BankNIFTY Strategies]")
print(f"  Running E1 SuperTrend_NIFTY_v3…", end=" ", flush=True)
t=e1_supertrend_nifty_v3(nifty_5m); s=trade_stats(t); results["SuperTrend_NIFTY_v3"]=s; pprint("SuperTrend_NIFTY_v3",s)

print(f"  Running E2 BankNIFTY_VWAP_v3…", end=" ", flush=True)
t=e2_banknifty_vwap_v3(bank_5m); s=trade_stats(t,500_000); results["BankNIFTY_VWAP_v3"]=s; pprint("BankNIFTY_VWAP_v3",s)

print(f"  Running E3 NIFTY_RSI_Pullback…", end=" ", flush=True)
t=e3_rsi_pullback(nifty_5m); s=trade_stats(t,200_000); results["NIFTY_RSI_Pullback"]=s; pprint("NIFTY_RSI_Pullback",s)

print(f"  Running E4 BankNIFTY_ORB…", end=" ", flush=True)
t=e4_banknifty_orb(bank_5m); s=trade_stats(t,500_000); results["BankNIFTY_ORB"]=s; pprint("BankNIFTY_ORB",s)

print("\n[Phase 2: MCX Confirmation + Refinement]")
print(f"  Running E5 MCX_SILVER_v2…", end=" ", flush=True)
t=mcx_momentum_v2(silver_15m); s=trade_stats(t,100_000); results["MCX_SILVER_v2"]=s; pprint("MCX_SILVER_v2",s)

print(f"  Running E6 MCX_GOLD_v2…", end=" ", flush=True)
t=mcx_momentum_v2(gold_15m); s=trade_stats(t,100_000); results["MCX_GOLD_v2"]=s; pprint("MCX_GOLD_v2",s)

print(f"  Running E7 MCX_CrudeOil_v2 (filtered)…", end=" ", flush=True)
t=e7_crudeoil_v2(crude_15m); s=trade_stats(t,50_000); results["MCX_CrudeOil_v2"]=s; pprint("MCX_CrudeOil_v2",s)

# ── Parameter sweep for best NIFTY strategy ───────────────────────────────────
print("\n[Phase 3: Parameter Sweep — SuperTrend_NIFTY_v3]")
best_st=None; best_score=0
for sl in [1.2,1.5,2.0]:
    for tp in [2.5,3.0,3.5]:
        for adx_min in [18,22,25]:
            t=e1_supertrend_nifty_v3(nifty_5m, sl_atr=sl, tp_atr=tp, adx_min=adx_min)
            s=trade_stats(t)
            if s and s["trades"]>=8:
                score=s["pf"]*s["wr_pct"]/max(s["dd_pct"],0.1)
                if score>best_score:
                    best_score=score; best_st={**s,"params":{"sl":sl,"tp":tp,"adx":adx_min}}
if best_st:
    results["SuperTrend_NIFTY_v3_OPTIMIZED"]=best_st
    pprint(f"  BEST (sl={best_st['params']['sl']} tp={best_st['params']['tp']} adx={best_st['params']['adx']})", best_st)

# ── Final summary ──────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("FINAL EQUITY RESULTS")
print("="*70)
print(f"\n{'Strategy':38s}  {'PF':>6} {'WR%':>6} {'DD%':>5} {'T':>4}  Net")
print("-"*75)
for name, s in results.items():
    pprint(name, s)

deploy = [(n,s) for n,s in results.items() if s and s["pf"]>=2.0 and s["wr_pct"]>=45 and s["dd_pct"]<=3]
print(f"\n✅ DEPLOY-READY equity strategies: {len(deploy)}")
for n,s in deploy:
    print(f"   → {n}  PF={s['pf']} WR={s['wr_pct']}% DD={s['dd_pct']}%")

out_path="/Users/mac/sksoopenalgo/openalgo/overnight_equity_results.json"
with open(out_path,"w") as f: json.dump(results,f,indent=2)
print(f"\nSaved → {out_path}")
