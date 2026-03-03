#!/usr/bin/env python3
"""
MCX Re-optimisation sweep — Silver / Gold / CrudeOil
Data source: OpenAlgo API (real MCX 15m bars, 58 days)
Target: PF > 2.5, MaxDD < 5%
Variants: fixed TP  +  trailing stop
"""
import warnings, itertools, json
warnings.filterwarnings("ignore")

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

HOST   = "http://127.0.0.1:5002"
APIKEY = "372ffc43867ca4586f2a90621bc153849c2fd2bf5f86f071751c6ce7c16492eb"
END    = datetime.today()
START  = END - timedelta(days=58)

# ── indicators ───────────────────────────────────────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + g/l)

def atr_s(h, l, c, n=14):
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def adx_s(h, l, c, n=14):
    dm_p = h.diff().clip(lower=0)
    dm_n = (-l.diff()).clip(lower=0)
    dm_p[dm_p < (-l.diff()).clip(lower=0)] = 0
    dm_n[dm_n < h.diff().clip(lower=0)] = 0
    tr   = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    at   = tr.ewm(alpha=1/n, adjust=False).mean()
    di_p = 100*dm_p.ewm(alpha=1/n, adjust=False).mean()/at
    di_n = 100*dm_n.ewm(alpha=1/n, adjust=False).mean()/at
    dx   = 100*(di_p-di_n).abs()/(di_p+di_n).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()

def backtest(df, ema_f, ema_s, rsi_buy, rsi_sell, adx_th,
             atr_sl, atr_tp=None, trail_atr=None):
    df = df.copy()
    df["ef"]  = ema(df["close"], ema_f)
    df["es"]  = ema(df["close"], ema_s)
    df["rsi"] = rsi(df["close"])
    df["atr"] = atr_s(df["high"], df["low"], df["close"])
    df["adx"] = adx_s(df["high"], df["low"], df["close"])
    df = df.dropna().reset_index(drop=True)

    pos=0; entry=0; sl=0; tp=0; trail_sl=0
    trades=[]; equity=0; peak=0; max_dd=0

    for i in range(2, len(df)):
        c = df.iloc[i]; p = df.iloc[i-1]
        px = float(c["close"]); at = float(c["atr"])
        bull = c["ef"]>c["es"]; bear = c["ef"]<c["es"]
        up   = px>float(p["close"]); dn = px<float(p["close"])

        if pos != 0:
            if trail_atr:
                if pos>0: trail_sl = max(trail_sl, px - trail_atr*at)
                else:     trail_sl = min(trail_sl, px + trail_atr*at)
                sl = trail_sl

            exit_p = None
            if pos>0:
                if px<=sl: exit_p=sl
                elif atr_tp and px>=tp: exit_p=tp
            else:
                if px>=sl: exit_p=sl
                elif atr_tp and px<=tp: exit_p=tp

            if exit_p:
                pnl = (exit_p-entry)*pos
                trades.append(pnl)
                equity += pnl
                peak = max(peak, equity)
                if peak > 0:
                    dd = (peak - equity)/peak*100
                    max_dd = max(max_dd, dd)
                pos=0; entry=0; sl=0; tp=0; trail_sl=0
            continue

        if float(c["adx"]) < adx_th: continue
        if bull and float(c["rsi"])>=rsi_buy and up:
            pos=1; entry=px
            sl=px-atr_sl*at
            tp=px+atr_tp*at if atr_tp else None
            trail_sl=px-trail_atr*at if trail_atr else 0
        elif bear and float(c["rsi"])<=rsi_sell and dn:
            pos=-1; entry=px
            sl=px+atr_sl*at
            tp=px-atr_tp*at if atr_tp else None
            trail_sl=px+trail_atr*at if trail_atr else 0

    if not trades: return None
    wins=[t for t in trades if t>0]; loss=[t for t in trades if t<0]
    gp=sum(wins); gl=abs(sum(loss)) if loss else 1e-9
    return dict(pf=round(gp/gl,3), dd=round(max_dd,2),
                wr=round(len(wins)/len(trades)*100,1), trades=len(trades))

# ── fetch real MCX data via OpenAlgo ──────────────────────────────────────
symbols = {
    "SILVER":   "SILVERM30APR26FUT",
    "GOLD":     "GOLDM02APR26FUT",
    "CRUDEOIL": "CRUDEOILM19MAR26FUT",
}

raw = {}
print("Fetching MCX 15m data from OpenAlgo API…")
for name, sym in symbols.items():
    r = requests.post(f"{HOST}/api/v1/history",
        json={"apikey": APIKEY, "symbol": sym, "exchange": "MCX",
              "interval": "15m",
              "start_date": START.strftime("%Y-%m-%d"),
              "end_date":   END.strftime("%Y-%m-%d")},
        timeout=20)
    data = r.json().get("data", [])
    df = pd.DataFrame(data)
    df.columns = [c.lower() for c in df.columns]
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().reset_index(drop=True)
    raw[name] = df
    print(f"  {name:10s}: {len(df):4d} bars  ({sym})")

# ── parameter grid ────────────────────────────────────────────────────────
EMA_PAIRS  = [(5,13),(5,21),(9,21),(9,34),(13,34),(13,55),(9,50),(21,55),(8,21),(8,34)]
RSI_BUY    = [50,55,58,60,62]
RSI_SELL   = [50,45,42,40,38]
ADX_TH     = [20,25,30,35]
ATR_SL     = [1.0,1.5,2.0,2.5]
ATR_TP     = [2.0,2.5,3.0,4.0,5.0,6.0,8.0,10.0]
TRAIL      = [None, 1.5, 2.0, 2.5, 3.0]

MIN_TRADES = 20
TARGET_PF  = 2.5
MAX_DD     = 5.0

results = {}
for name, df in raw.items():
    print(f"\n{'='*56}\nSweeping {name} ({len(df)} bars)…")
    best = []
    tested = 0
    for (ef,es),rb,rs,adx_th,atr_sl,trail in itertools.product(
            EMA_PAIRS, RSI_BUY, RSI_SELL, ADX_TH, ATR_SL, TRAIL):
        if rb <= rs: continue

        if trail is None:
            # fixed TP combos
            for atr_tp in ATR_TP:
                tested += 1
                r = backtest(df, ef, es, rb, rs, adx_th, atr_sl, atr_tp=atr_tp)
                if r and r["trades"]>=MIN_TRADES:
                    if r["pf"]>=TARGET_PF and r["dd"]<=MAX_DD:
                        best.append(dict(ema_f=ef,ema_s=es,rsi_buy=rb,rsi_sell=rs,
                            adx_th=adx_th,atr_sl=atr_sl,atr_tp=atr_tp,trail=None,**r))
        else:
            tested += 1
            r = backtest(df, ef, es, rb, rs, adx_th, atr_sl, trail_atr=trail)
            if r and r["trades"]>=MIN_TRADES:
                if r["pf"]>=TARGET_PF and r["dd"]<=MAX_DD:
                    best.append(dict(ema_f=ef,ema_s=es,rsi_buy=rb,rsi_sell=rs,
                        adx_th=adx_th,atr_sl=atr_sl,atr_tp=None,trail=trail,**r))

    print(f"  Tested: {tested:,} | Passed PF≥{TARGET_PF} & DD≤{MAX_DD}%: {len(best)}")
    best.sort(key=lambda x: (-x["pf"], x["dd"]))

    # fallback: if nothing passes strict filter, lower to PF>2.0
    if not best:
        print(f"  ⚠  Loosening to PF>2.0…")
        tested2 = 0
        for (ef,es),rb,rs,adx_th,atr_sl,trail in itertools.product(
                EMA_PAIRS, RSI_BUY, RSI_SELL, ADX_TH, ATR_SL, TRAIL):
            if rb<=rs: continue
            if trail is None:
                for atr_tp in ATR_TP:
                    tested2+=1
                    r=backtest(df,ef,es,rb,rs,adx_th,atr_sl,atr_tp=atr_tp)
                    if r and r["trades"]>=MIN_TRADES and r["pf"]>=2.0 and r["dd"]<=MAX_DD:
                        best.append(dict(ema_f=ef,ema_s=es,rsi_buy=rb,rsi_sell=rs,
                            adx_th=adx_th,atr_sl=atr_sl,atr_tp=atr_tp,trail=None,**r))
            else:
                tested2+=1
                r=backtest(df,ef,es,rb,rs,adx_th,atr_sl,trail_atr=trail)
                if r and r["trades"]>=MIN_TRADES and r["pf"]>=2.0 and r["dd"]<=MAX_DD:
                    best.append(dict(ema_f=ef,ema_s=es,rsi_buy=rb,rsi_sell=rs,
                        adx_th=adx_th,atr_sl=atr_sl,atr_tp=None,trail=trail,**r))
        best.sort(key=lambda x:(-x["pf"],x["dd"]))

    results[name] = best[:5]

    print(f"\n  TOP configs for {name}:")
    print(f"  {'EMAf':>4} {'EMAs':>5} {'RSIb':>4} {'RSIs':>4} {'ADX':>4} "
          f"{'SL×':>4} {'TP×':>5} {'Trail':>5} | {'PF':>5} {'DD%':>5} {'WR%':>5} {'#T':>4}")
    print("  " + "-"*65)
    for r in results[name]:
        tp_s   = f"{r['atr_tp']:.1f}" if r.get("atr_tp") else "  —"
        trail_s= f"{r['trail']:.1f}" if r.get("trail") else "  —"
        print(f"  {r['ema_f']:>4} {r['ema_s']:>5} {r['rsi_buy']:>4} {r['rsi_sell']:>4} "
              f"{r['adx_th']:>4} {r['atr_sl']:>4} {tp_s:>5} {trail_s:>5} | "
              f"{r['pf']:>5.2f} {r['dd']:>5.1f} {r['wr']:>5.1f} {r['trades']:>4}")

with open("/Users/mac/sksoopenalgo/openalgo/mcx_reoptimise_results.json","w") as f:
    json.dump(results, f, indent=2)
print("\n✅ MCX results saved to mcx_reoptimise_results.json")
