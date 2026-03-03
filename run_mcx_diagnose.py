#!/usr/bin/env python3
"""
MCX Diagnostics — understand why real API data shows 0 passing configs
- Show best PF found even below threshold
- Show trade count distribution
- Show sample trades to check if strategy fires at all
- Compare data characteristics
"""
import warnings, json, itertools
warnings.filterwarnings("ignore")
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

HOST   = "http://127.0.0.1:5002"
APIKEY = "372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
END    = datetime.today()
START  = END - timedelta(days=58)

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rsi_ind(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + g/l)
def atr_ind(h, l, c, n=14):
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()
def adx_ind(h, l, c, n=14):
    dm_p = h.diff().clip(lower=0)
    dm_n = (-l.diff()).clip(lower=0)
    dm_p[dm_p < (-l.diff()).clip(lower=0)] = 0
    dm_n[dm_n < h.diff().clip(lower=0)] = 0
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    at = tr.ewm(alpha=1/n, adjust=False).mean()
    di_p = 100*dm_p.ewm(alpha=1/n, adjust=False).mean()/at
    di_n = 100*dm_n.ewm(alpha=1/n, adjust=False).mean()/at
    dx = 100*(di_p-di_n).abs()/(di_p+di_n).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()

def backtest_fast(closes, ef_arr, es_arr, rsi_arr, atr_arr, adx_arr,
                  rsi_buy, rsi_sell, adx_th, atr_sl, atr_tp=None, trail_atr=None):
    pos=0; entry=0.0; sl=0.0; tp=0.0; trail_sl=0.0
    trades=[]; equity=0.0; peak=0.0; max_dd=0.0
    n = len(closes)
    for i in range(2, n):
        px = closes[i]; at = atr_arr[i]
        bull = ef_arr[i] > es_arr[i]; bear = ef_arr[i] < es_arr[i]
        up = px > closes[i-1]; dn = px < closes[i-1]
        if pos != 0:
            if trail_atr:
                if pos > 0: trail_sl = max(trail_sl, px - trail_atr*at)
                else:       trail_sl = min(trail_sl, px + trail_atr*at)
                sl = trail_sl
            exit_p = None
            if pos > 0:
                if px <= sl: exit_p = sl
                elif atr_tp and px >= tp: exit_p = tp
            else:
                if px >= sl: exit_p = sl
                elif atr_tp and px <= tp: exit_p = tp
            if exit_p is not None:
                pnl = (exit_p - entry) * pos
                trades.append(pnl)
                equity += pnl; peak = max(peak, equity)
                if peak > 0: max_dd = max(max_dd, (peak-equity)/peak*100)
                pos=0; entry=0.0; sl=0.0; tp=0.0; trail_sl=0.0
            continue
        if adx_arr[i] < adx_th: continue
        if bull and rsi_arr[i] >= rsi_buy and up:
            pos=1; entry=px; sl=px-atr_sl*at
            tp=px+atr_tp*at if atr_tp else 0.0
            trail_sl=px-trail_atr*at if trail_atr else 0.0
        elif bear and rsi_arr[i] <= rsi_sell and dn:
            pos=-1; entry=px; sl=px+atr_sl*at
            tp=px-atr_tp*at if atr_tp else 0.0
            trail_sl=px+trail_atr*at if trail_atr else 0.0
    if not trades: return None
    wins=[t for t in trades if t>0]; loss=[t for t in trades if t<0]
    gp=sum(wins); gl=abs(sum(loss)) if loss else 1e-9
    return dict(pf=round(gp/gl,3), dd=round(max_dd,2),
                wr=round(len(wins)/len(trades)*100,1), trades=len(trades),
                net=round(sum(trades),2))

symbols = {"SILVER": "SILVERM30APR26FUT", "GOLD": "GOLDM02APR26FUT",
           "CRUDEOIL": "CRUDEOILM19MAR26FUT"}
raw = {}
print("Fetching MCX 15m data…")
for name, sym in symbols.items():
    r = requests.post(f"{HOST}/api/v1/history",
        json={"apikey": APIKEY, "symbol": sym, "exchange": "MCX",
              "interval": "15m", "start_date": START.strftime("%Y-%m-%d"),
              "end_date": END.strftime("%Y-%m-%d")}, timeout=20)
    data = r.json().get("data", [])
    df = pd.DataFrame(data)
    df.columns = [c.lower() for c in df.columns]
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    raw[name] = df
    print(f"  {name}: {len(df)} bars | close range: {df['close'].min():.0f}–{df['close'].max():.0f}")
    # Show ATR and ADX stats
    atr = atr_ind(df["high"],df["low"],df["close"])
    adx = adx_ind(df["high"],df["low"],df["close"])
    print(f"    ATR(14): mean={atr.mean():.1f}, max={atr.max():.1f}")
    print(f"    ADX(14): mean={adx.mean():.1f}, %above30={len(adx[adx>30])/len(adx)*100:.1f}%")
    rsi = rsi_ind(df["close"])
    print(f"    RSI(14): mean={rsi.mean():.1f}, %above55={len(rsi[rsi>55])/len(rsi)*100:.1f}%")

print("\n" + "="*60)
print("BEST CONFIGS (no minimum PF threshold, min 10 trades)")
print("="*60)

for name, df in raw.items():
    closes = df["close"].values.astype(float)
    rsi_arr = rsi_ind(df["close"]).values.astype(float)
    atr_arr = atr_ind(df["high"],df["low"],df["close"]).values.astype(float)
    adx_arr = adx_ind(df["high"],df["low"],df["close"]).values.astype(float)
    EMA_PAIRS = [(9,21),(9,34),(9,50),(13,34),(13,55),(5,21)]
    ema_cache = {}
    for ef,es in set(EMA_PAIRS):
        ema_cache[(ef,es)] = (ema(df["close"],ef).values.astype(float),
                              ema(df["close"],es).values.astype(float))
    print(f"\n{name}:")
    all_r = []
    for (ef,es),rb,rs,adx_th,atr_sl in itertools.product(
            EMA_PAIRS,[50,55,60],[50,45,40],[20,25,30],[1.0,1.5,2.0]):
        if rb <= rs: continue
        ef_arr,es_arr = ema_cache[(ef,es)]
        for atr_tp in [2.0,3.0,4.0,5.0,6.0,8.0,10.0]:
            r = backtest_fast(closes,ef_arr,es_arr,rsi_arr,atr_arr,adx_arr,
                              rb,rs,adx_th,atr_sl,atr_tp=atr_tp)
            if r and r["trades"] >= 10:
                all_r.append(dict(ef=ef,es=es,rb=rb,rs=rs,adx=adx_th,
                                  sl=atr_sl,tp=atr_tp,trail="—",**r))
        for trail in [1.5,2.0,2.5,3.0]:
            r = backtest_fast(closes,ef_arr,es_arr,rsi_arr,atr_arr,adx_arr,
                              rb,rs,adx_th,atr_sl,trail_atr=trail)
            if r and r["trades"] >= 10:
                all_r.append(dict(ef=ef,es=es,rb=rb,rs=rs,adx=adx_th,
                                  sl=atr_sl,tp="—",trail=trail,**r))
    all_r.sort(key=lambda x: (-x["pf"], x["dd"]))
    print(f"  {'EMAf':>4} {'EMAs':>5} {'Rb':>3} {'Rs':>3} {'ADX':>4} {'SL':>4} "
          f"{'TP':>5} {'Trail':>5} | {'PF':>5} {'DD':>5} {'WR':>5} {'#T':>4} {'Net':>12}")
    for c in all_r[:10]:
        print(f"  {c['ef']:>4} {c['es']:>5} {c['rb']:>3} {c['rs']:>3} {c['adx']:>4} "
              f"{c['sl']:>4.1f} {str(c['tp']):>5} {str(c['trail']):>5} | "
              f"{c['pf']:>5.2f} {c['dd']:>5.1f} {c['wr']:>5.1f} {c['trades']:>4} "
              f"₹{c['net']:>11,.0f}")
    if not all_r:
        print("  ⚠  Zero trades even with no PF filter!")
