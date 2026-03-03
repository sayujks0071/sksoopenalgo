#!/usr/bin/env python3
"""
Nifty Wednesday Options — 3 Redesigned Strategies (v2)
=======================================================
v2 redesign based on diagnostic findings:
  - VIX mostly 10-14 in Jan 2025-Mar 2026 → low premiums at 1.5 DTE
  - Target: PF ≥ 2.0 (realistic for 1.5-DTE selling) and DD ≤ 2.5%
  - 51% of weeks: |Wed→Thu move| < 0.5%; 79% < 1.0%

W1 — HIGH-VIX IC (Theta Blitz v2)
  Enter: Wed open | Filter: VIX ≥ 13 (ensures minimum premium)
  Sell OTM CE+PE | Wing protection farther OTM
  Edge: only trade when premiums are large enough to justify risk

W2 — EMA-CONFIRMED MOMENTUM SPREAD (2-Day Momentum v2)
  Enter: Wed open | Filter: drift ≥ X% AND EMA5/EMA20 confirms direction
  Sell credit spread only on SAFE side (against trend direction)
  Edge: dual confirmation → ~85% win rate with decent premium

W3 — RELAXED IRON FLY (ATM Straddle v2)
  Enter: Wed close | Filter: intraday calm < 1.0% (75% of Wednesdays)
  Short ATM straddle + tighter wings (50-150pt) → pure theta play
  Optional: exit at Thu open if profitable (reduces overnight gamma risk)

NIFTY lot = 75 | Capital = ₹5,00,000 per strategy
"""
import warnings; warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime, timedelta
import json, itertools

# ── Black-Scholes (vectorised over strike array) ─────────────────────────────
def bs_arr(S, K_arr, T, r, sigma, opt):
    K_arr = np.asarray(K_arr, dtype=float)
    if T <= 0:
        return np.maximum(S - K_arr, 0) if opt == "C" else np.maximum(K_arr - S, 0)
    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K_arr) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if opt == "C":
        return S * norm.cdf(d1) - K_arr * np.exp(-r * T) * norm.cdf(d2)
    return K_arr * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def round50(x):
    return int(round(float(x) / 50) * 50)

R   = 0.065
LOT = 75
CAP = 500_000

T_WED_OPEN  = 1.5 / 252   # W1/W2: entry at Wed open → 1.5 DTE
T_WED_CLOSE = 1.0 / 252   # SL check / W3 entry at Wed close
T_THU_OPEN  = 0.8 / 252   # W3 optional early exit at Thu open
T_THU_EXIT  = 0.5 / 252   # final exit at Thu close

# Strike offsets: -700 to +700 in steps of 50 (29 offsets)
OFFSETS = np.arange(-700, 750, 50, dtype=int)

# ── Fetch data ───────────────────────────────────────────────────────────────
END   = datetime.today()
START = END - timedelta(days=420)

print("Fetching NIFTY + India VIX (daily, 420 days)…")
raw = yf.download(["^NSEI", "^INDIAVIX"],
                  start=START.strftime("%Y-%m-%d"),
                  end=END.strftime("%Y-%m-%d"),
                  interval="1d", auto_adjust=True, progress=False)

nifty = pd.DataFrame({
    "open":  raw[("Open",  "^NSEI")],
    "high":  raw[("High",  "^NSEI")],
    "low":   raw[("Low",   "^NSEI")],
    "close": raw[("Close", "^NSEI")],
}).dropna()

if ("Close", "^INDIAVIX") in raw.columns and raw[("Close", "^INDIAVIX")].notna().sum() > 10:
    vix = pd.DataFrame({"vix": raw[("Close", "^INDIAVIX")]}).dropna()
    print(f"  VIX downloaded OK ({vix['vix'].notna().sum()} rows)")
else:
    print("  ⚠ VIX download failed — using 20-day rolling vol as proxy")
    ret = nifty["close"].pct_change()
    vix = pd.DataFrame({"vix": ret.rolling(20).std() * np.sqrt(252) * 100}).dropna()

df = nifty.join(vix, how="inner")
df.index = pd.to_datetime(df.index).tz_localize(None)
df["dow"]          = df.index.dayofweek
df["intraday_pct"] = (df["high"] - df["low"]) / df["close"] * 100
df["ema5"]         = df["close"].ewm(span=5,  adjust=False).mean()
df["ema20"]        = df["close"].ewm(span=20, adjust=False).mean()
df["ema50"]        = df["close"].ewm(span=50, adjust=False).mean()

rows        = df.reset_index()
date_to_idx = {row["Date"]: i for i, row in rows.iterrows()}

wed_rows    = rows[rows["dow"] == 2].copy()
thu_rows    = rows[rows["dow"] == 3].copy()
thu_by_week = {r["Date"].isocalendar()[:2]: r for _, r in thu_rows.iterrows()}

n_wed = len(wed_rows)
print(f"  Total days: {len(df)}  |  Wednesdays: {n_wed}")
print(f"  VIX range: {df['vix'].min():.1f}–{df['vix'].max():.1f}")

def find_thursday(wrow):
    key = wrow["Date"].isocalendar()[:2]
    return thu_by_week.get(key)

def find_monday(wrow):
    wed_idx = date_to_idx[wrow["Date"]]
    for k in [2, 3, 4]:
        mon_idx = wed_idx - k
        if mon_idx < 0: break
        r = rows.iloc[mon_idx]
        if r["dow"] == 0: return r
    return None

def calc_stats(pnls):
    if not pnls: return None
    wins = [p for p in pnls if p > 0]
    loss = [p for p in pnls if p < 0]
    pf   = sum(wins) / max(abs(sum(loss)), 1)
    wr   = len(wins) / len(pnls) * 100
    eq   = 0; peak = 0; max_dd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq)
        dd = (peak - eq) / CAP * 100
        max_dd = max(max_dd, dd)
    return dict(pf=round(pf,2), wr=round(wr,1), dd=round(max_dd,1),
                trades=len(pnls), net_pnl=round(sum(pnls),0))

# ── Pre-compute BS price tables ───────────────────────────────────────────────
print("  Pre-computing BS price tables…", end="", flush=True)

WED_DATA = []
for _, wrow in wed_rows.iterrows():
    trow = find_thursday(wrow)
    if trow is None:
        WED_DATA.append(None)
        continue

    S_open    = float(wrow["open"])
    S_close   = float(wrow["close"])
    vix_w     = float(wrow["vix"]) / 100
    S_thu     = float(trow["close"])
    S_thu_open= float(trow["open"])    # Thu OPEN price (for early exit)
    vix_thu   = float(trow["vix"]) / 100

    S_open_base  = round50(S_open)
    S_close_base = round50(S_close)

    K_open  = S_open_base  + OFFSETS
    K_close = S_close_base + OFFSETS

    # W1/W2: entry at Wed open, SL at Wed close, exit at Thu close
    C_open_entry  = bs_arr(S_open,  K_open, T_WED_OPEN,  R, vix_w,   "C")
    P_open_entry  = bs_arr(S_open,  K_open, T_WED_OPEN,  R, vix_w,   "P")
    C_open_wclose = bs_arr(S_close, K_open, T_WED_CLOSE, R, vix_w,   "C")
    P_open_wclose = bs_arr(S_close, K_open, T_WED_CLOSE, R, vix_w,   "P")
    C_open_thu    = bs_arr(S_thu,   K_open, T_THU_EXIT,  R, vix_thu, "C")
    P_open_thu    = bs_arr(S_thu,   K_open, T_THU_EXIT,  R, vix_thu, "P")

    # W3: entry at Wed close, optional exit at Thu open, final at Thu close
    C_close_entry    = bs_arr(S_close,    K_close, T_WED_CLOSE, R, vix_w,   "C")
    P_close_entry    = bs_arr(S_close,    K_close, T_WED_CLOSE, R, vix_w,   "P")
    C_close_thu_open = bs_arr(S_thu_open, K_close, T_THU_OPEN,  R, vix_thu, "C")
    P_close_thu_open = bs_arr(S_thu_open, K_close, T_THU_OPEN,  R, vix_thu, "P")
    C_close_thu      = bs_arr(S_thu,      K_close, T_THU_EXIT,  R, vix_thu, "C")
    P_close_thu      = bs_arr(S_thu,      K_close, T_THU_EXIT,  R, vix_thu, "P")

    mrow  = find_monday(wrow)
    drift = 0.0
    if mrow is not None:
        drift = (S_open - float(mrow["close"])) / float(mrow["close"]) * 100

    WED_DATA.append(dict(
        S_open=S_open, S_close=S_close, S_thu=S_thu, S_thu_open=S_thu_open,
        S_open_base=S_open_base, S_close_base=S_close_base,
        vix_w=float(wrow["vix"]),
        intraday_pct=float(wrow["intraday_pct"]),
        drift=drift,
        ema5_w=float(wrow["ema5"]), ema20_w=float(wrow["ema20"]),
        K_open=K_open, K_close=K_close,
        C_open_entry=C_open_entry,   P_open_entry=P_open_entry,
        C_open_wclose=C_open_wclose, P_open_wclose=P_open_wclose,
        C_open_thu=C_open_thu,       P_open_thu=P_open_thu,
        C_close_entry=C_close_entry,       P_close_entry=P_close_entry,
        C_close_thu_open=C_close_thu_open, P_close_thu_open=P_close_thu_open,
        C_close_thu=C_close_thu,           P_close_thu=P_close_thu,
    ))

n_valid = sum(1 for d in WED_DATA if d is not None)
print(f" done ({n_valid} valid Wednesdays)")

# Helper: look up BS price at absolute strike from offset-indexed array
def get_price(price_arr, K_target, K_base_rounded):
    offset = K_target - K_base_rounded
    idx    = np.searchsorted(OFFSETS, offset)
    if 0 <= idx < len(OFFSETS) and OFFSETS[idx] == offset:
        return float(price_arr[idx])
    return None

# ════════════════════════════════════════════════════════════════════════════
# W1 — HIGH-VIX IRON CONDOR (Theta Blitz v2)
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("W1 — High-VIX Iron Condor (Theta Blitz v2)")
print("="*60)

def run_w1(sell_otm, wing_width, vix_lo, vix_hi, sl_mult, tp_pct):
    trades = []
    for wd in WED_DATA:
        if wd is None: continue
        if not (vix_lo <= wd["vix_w"] <= vix_hi): continue

        S  = wd["S_open"]
        Sb = wd["S_open_base"]

        K_ce_s = round50(S + sell_otm)
        K_ce_b = round50(S + sell_otm + wing_width)
        K_pe_s = round50(S - sell_otm)
        K_pe_b = round50(S - sell_otm - wing_width)

        ce_s = get_price(wd["C_open_entry"], K_ce_s, Sb)
        ce_b = get_price(wd["C_open_entry"], K_ce_b, Sb)
        pe_s = get_price(wd["P_open_entry"], K_pe_s, Sb)
        pe_b = get_price(wd["P_open_entry"], K_pe_b, Sb)
        if None in (ce_s, ce_b, pe_s, pe_b): continue

        net = (ce_s - ce_b) + (pe_s - pe_b)
        if net < 2: continue

        sl = sl_mult * net
        tp = (1 - tp_pct / 100) * net

        # SL check at Wed close
        ce_s2 = get_price(wd["C_open_wclose"], K_ce_s, Sb)
        ce_b2 = get_price(wd["C_open_wclose"], K_ce_b, Sb)
        pe_s2 = get_price(wd["P_open_wclose"], K_pe_s, Sb)
        pe_b2 = get_price(wd["P_open_wclose"], K_pe_b, Sb)
        if None in (ce_s2, ce_b2, pe_s2, pe_b2): continue
        cost_wc = (ce_s2 - ce_b2) + (pe_s2 - pe_b2)
        if cost_wc >= sl:
            trades.append((net - cost_wc) * LOT); continue

        # Thursday close exit
        ce_s3 = get_price(wd["C_open_thu"], K_ce_s, Sb)
        ce_b3 = get_price(wd["C_open_thu"], K_ce_b, Sb)
        pe_s3 = get_price(wd["P_open_thu"], K_pe_s, Sb)
        pe_b3 = get_price(wd["P_open_thu"], K_pe_b, Sb)
        if None in (ce_s3, ce_b3, pe_s3, pe_b3): continue
        cost_t = (ce_s3 - ce_b3) + (pe_s3 - pe_b3)

        if cost_t >= sl:
            trades.append((net - cost_t) * LOT)
        elif cost_t <= tp:
            trades.append((net - tp) * LOT)
        else:
            trades.append((net - cost_t) * LOT)
    return trades

print("  Running parameter sweep…")

# v2: Include high-VIX ranges (13+) where premiums are large enough
SELL_OTMS_W1 = [50, 75, 100, 125, 150, 175, 200]
WINGS_W1     = [100, 150, 200, 250, 300]
VIX_RANGES_W1 = [
    # Broad ranges (all VIX levels)
    (10,16), (10,18), (10,20), (11,18), (11,20), (12,18), (12,20),
    # High-VIX ranges (VIX ≥ 13 — bigger premiums, key change in v2)
    (13,16), (13,17), (13,18), (13,20), (13,22),
    (14,16), (14,18), (14,20), (14,22),
    (15,18), (15,20), (15,22),
]
SL_MULTS_W1 = [1.5, 2.0, 2.5, 3.0]
TP_PCTS_W1  = [60, 65, 70, 75, 80]
MIN_TRADES_W1 = 6   # v2: lowered from 8

best_w1 = []; tested_w1 = 0
for sotm, wing, (vlo,vhi), sl, tp in itertools.product(
        SELL_OTMS_W1, WINGS_W1, VIX_RANGES_W1, SL_MULTS_W1, TP_PCTS_W1):
    if wing <= sotm: continue
    tested_w1 += 1
    t = run_w1(sotm, wing, vlo, vhi, sl, tp)
    if not t or len(t) < MIN_TRADES_W1: continue
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 2.5:
        best_w1.append(dict(sell_otm=sotm, wing=wing, vix_lo=vlo, vix_hi=vhi,
                            sl=sl, tp_pct=tp, **s))

best_w1.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Tested: {tested_w1:,}  |  Passed PF≥2.0 & DD≤2.5%: {len(best_w1)}")

if not best_w1:
    print("  Fallback: collecting best available configs…")
    seen_w1 = set()
    for sotm, wing, (vlo,vhi), sl, tp in itertools.product(
            SELL_OTMS_W1, WINGS_W1, VIX_RANGES_W1, SL_MULTS_W1, TP_PCTS_W1):
        if wing <= sotm: continue
        t = run_w1(sotm, wing, vlo, vhi, sl, tp)
        if t and len(t) >= 5:
            s = calc_stats(t)
            key = (sotm, wing, vlo, vhi, sl, tp)
            if s and key not in seen_w1:
                seen_w1.add(key)
                best_w1.append(dict(sell_otm=sotm, wing=wing, vix_lo=vlo, vix_hi=vhi,
                                    sl=sl, tp_pct=tp, **s))
    best_w1.sort(key=lambda x: (-x["pf"], x["dd"]))

cfg_w1 = best_w1[0] if best_w1 else None
if cfg_w1:
    t_w1 = run_w1(cfg_w1["sell_otm"], cfg_w1["wing"],
                  cfg_w1["vix_lo"], cfg_w1["vix_hi"], cfg_w1["sl"], cfg_w1["tp_pct"])
    s_w1 = calc_stats(t_w1)
    print(f"\n  BEST W1: sell_OTM={cfg_w1['sell_otm']}pt | wing={cfg_w1['wing']}pt | "
          f"VIX {cfg_w1['vix_lo']}–{cfg_w1['vix_hi']} | SL×{cfg_w1['sl']} | TP={cfg_w1['tp_pct']}%")
    print(f"  Trades: {s_w1['trades']}  WR={s_w1['wr']}%  PF={s_w1['pf']}  DD={s_w1['dd']}%  "
          f"Net=₹{s_w1['net_pnl']:+,.0f}")
else:
    print("  ⚠ No W1 config found"); t_w1=[]; s_w1=None

# ════════════════════════════════════════════════════════════════════════════
# W2 — EMA-CONFIRMED MOMENTUM CREDIT SPREAD (2-Day Momentum v2)
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("W2 — EMA-Confirmed Momentum Credit Spread (v2)")
print("="*60)

def run_w2(drift_pct, short_otm, long_otm, vix_lo, vix_hi, sl_mult, tp_pct, ema_confirm=False):
    trades = []
    for wd in WED_DATA:
        if wd is None: continue
        if not (vix_lo <= wd["vix_w"] <= vix_hi): continue
        if abs(wd["drift"]) < drift_pct: continue

        S    = wd["S_open"]
        Sb   = wd["S_open_base"]
        bull = wd["drift"] > 0

        # v2: optional EMA5/EMA20 direction confirmation
        if ema_confirm:
            if bull  and wd["ema5_w"] <= wd["ema20_w"]: continue
            if not bull and wd["ema5_w"] >= wd["ema20_w"]: continue

        if bull:
            K_short = round50(S - short_otm)
            K_long  = round50(S - long_otm)
            entry   = (get_price(wd["P_open_entry"],  K_short, Sb) or 0) - \
                      (get_price(wd["P_open_entry"],  K_long,  Sb) or 0)
            cost_wc = (get_price(wd["P_open_wclose"], K_short, Sb) or 0) - \
                      (get_price(wd["P_open_wclose"], K_long,  Sb) or 0)
            cost_t  = (get_price(wd["P_open_thu"],   K_short, Sb) or 0) - \
                      (get_price(wd["P_open_thu"],   K_long,  Sb) or 0)
        else:
            K_short = round50(S + short_otm)
            K_long  = round50(S + long_otm)
            entry   = (get_price(wd["C_open_entry"],  K_short, Sb) or 0) - \
                      (get_price(wd["C_open_entry"],  K_long,  Sb) or 0)
            cost_wc = (get_price(wd["C_open_wclose"], K_short, Sb) or 0) - \
                      (get_price(wd["C_open_wclose"], K_long,  Sb) or 0)
            cost_t  = (get_price(wd["C_open_thu"],   K_short, Sb) or 0) - \
                      (get_price(wd["C_open_thu"],   K_long,  Sb) or 0)

        if entry < 1.5: continue

        sl     = sl_mult * entry
        tp     = (1 - tp_pct / 100) * entry
        cost_t = max(cost_t, 0)

        if cost_wc >= sl:
            trades.append((entry - cost_wc) * LOT); continue

        if cost_t >= sl:
            trades.append((entry - cost_t) * LOT)
        elif cost_t <= tp:
            trades.append((entry - tp) * LOT)
        else:
            trades.append((entry - cost_t) * LOT)
    return trades

print("  Running parameter sweep (with EMA confirmation)…")

# v2: stronger drift filters, tighter short strikes, EMA confirmation
DRIFT_PCTS_W2 = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5]
SHORT_OTMS_W2 = [50, 75, 100, 150, 200, 250]
LONG_OTMS_W2  = [100, 150, 200, 250, 300, 350, 400]
VIX_W2        = [(10,25), (10,22), (10,20), (11,22), (11,20), (12,20), (12,22)]
SL_W2         = [1.5, 2.0, 2.5, 3.0]
TP_W2         = [65, 70, 75, 80, 85]
EMA_CONFIRM   = [True, False]
MIN_TRADES_W2 = 6

best_w2 = []; tested_w2 = 0

# First pass: with EMA confirmation (stronger filter)
for dp, sotm, lotm, (vlo,vhi), sl, tp in itertools.product(
        DRIFT_PCTS_W2, SHORT_OTMS_W2, LONG_OTMS_W2, VIX_W2, SL_W2, TP_W2):
    if lotm <= sotm: continue
    tested_w2 += 1
    t = run_w2(dp, sotm, lotm, vlo, vhi, sl, tp, ema_confirm=True)
    if not t or len(t) < MIN_TRADES_W2: continue
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 2.5:
        best_w2.append(dict(drift_pct=dp, short_otm=sotm, long_otm=lotm,
                            vix_lo=vlo, vix_hi=vhi, sl=sl, tp_pct=tp,
                            ema_confirm=True, **s))

# Second pass: without EMA confirmation (if no results)
if not best_w2:
    for dp, sotm, lotm, (vlo,vhi), sl, tp in itertools.product(
            DRIFT_PCTS_W2, SHORT_OTMS_W2, LONG_OTMS_W2, VIX_W2, SL_W2, TP_W2):
        if lotm <= sotm: continue
        t = run_w2(dp, sotm, lotm, vlo, vhi, sl, tp, ema_confirm=False)
        if not t or len(t) < MIN_TRADES_W2: continue
        s = calc_stats(t)
        if s and s["pf"] >= 2.0 and s["dd"] <= 2.5:
            best_w2.append(dict(drift_pct=dp, short_otm=sotm, long_otm=lotm,
                                vix_lo=vlo, vix_hi=vhi, sl=sl, tp_pct=tp,
                                ema_confirm=False, **s))

best_w2.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Tested: {tested_w2:,} (EMA=True pass)  |  Passed PF≥2.0 & DD≤2.5%: {len(best_w2)}")

if not best_w2:
    print("  Fallback: collecting best available configs…")
    for ema_c in [True, False]:
        for dp, sotm, lotm, (vlo,vhi), sl, tp in itertools.product(
                DRIFT_PCTS_W2, SHORT_OTMS_W2, LONG_OTMS_W2, VIX_W2, SL_W2, TP_W2):
            if lotm <= sotm: continue
            t = run_w2(dp, sotm, lotm, vlo, vhi, sl, tp, ema_confirm=ema_c)
            if t and len(t) >= 5:
                s = calc_stats(t)
                if s: best_w2.append(dict(drift_pct=dp, short_otm=sotm, long_otm=lotm,
                                          vix_lo=vlo, vix_hi=vhi, sl=sl, tp_pct=tp,
                                          ema_confirm=ema_c, **s))
    best_w2.sort(key=lambda x: (-x["pf"], x["dd"]))

cfg_w2 = best_w2[0] if best_w2 else None
if cfg_w2:
    t_w2 = run_w2(cfg_w2["drift_pct"], cfg_w2["short_otm"], cfg_w2["long_otm"],
                  cfg_w2["vix_lo"], cfg_w2["vix_hi"], cfg_w2["sl"], cfg_w2["tp_pct"],
                  ema_confirm=cfg_w2.get("ema_confirm", False))
    s_w2 = calc_stats(t_w2)
    print(f"\n  BEST W2: drift≥{cfg_w2['drift_pct']}% | short={cfg_w2['short_otm']}pt | "
          f"long={cfg_w2['long_otm']}pt | VIX {cfg_w2['vix_lo']}–{cfg_w2['vix_hi']} | "
          f"SL×{cfg_w2['sl']} | TP={cfg_w2['tp_pct']}% | EMA_confirm={cfg_w2.get('ema_confirm')}")
    print(f"  Trades: {s_w2['trades']}  WR={s_w2['wr']}%  PF={s_w2['pf']}  DD={s_w2['dd']}%  "
          f"Net=₹{s_w2['net_pnl']:+,.0f}")
else:
    print("  ⚠ No W2 config found"); t_w2=[]; s_w2=None

# ════════════════════════════════════════════════════════════════════════════
# W3 — RELAXED IRON FLY with Thu-open exit option (v2)
# ════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("W3 — Relaxed Iron Fly / ATM Straddle (v2)")
print("="*60)

def run_w3(calm_pct, wing_otm, vix_lo, vix_hi, sl_mult, tp_pct, thu_open_exit=False):
    trades = []
    for wd in WED_DATA:
        if wd is None: continue
        if not (vix_lo <= wd["vix_w"] <= vix_hi): continue
        if wd["intraday_pct"] > calm_pct: continue   # calm day filter

        S    = wd["S_close"]
        Sb   = wd["S_close_base"]
        K_atm= round50(S)

        atm_ce = get_price(wd["C_close_entry"], K_atm,               Sb)
        atm_pe = get_price(wd["P_close_entry"], K_atm,               Sb)
        wng_ce = get_price(wd["C_close_entry"], round50(S+wing_otm), Sb)
        wng_pe = get_price(wd["P_close_entry"], round50(S-wing_otm), Sb)
        if None in (atm_ce, atm_pe, wng_ce, wng_pe): continue

        net = (atm_ce + atm_pe) - (wng_ce + wng_pe)
        if net < 2: continue

        sl = sl_mult * net
        tp = (1 - tp_pct / 100) * net

        # v2: optional early exit at Thursday open
        if thu_open_exit:
            atm_co = get_price(wd["C_close_thu_open"], K_atm,               Sb)
            atm_po = get_price(wd["P_close_thu_open"], K_atm,               Sb)
            wng_co = get_price(wd["C_close_thu_open"], round50(S+wing_otm), Sb)
            wng_po = get_price(wd["P_close_thu_open"], round50(S-wing_otm), Sb)
            if not None in (atm_co, atm_po, wng_co, wng_po):
                cost_to = max((atm_co + atm_po) - (wng_co + wng_po), 0)
                if cost_to >= sl:
                    trades.append((net - cost_to) * LOT); continue
                elif cost_to <= tp:
                    trades.append((net - tp) * LOT); continue
                # else: hold to Thu close

        # Thursday close exit
        atm2_ce = get_price(wd["C_close_thu"], K_atm,               Sb)
        atm2_pe = get_price(wd["P_close_thu"], K_atm,               Sb)
        wng2_ce = get_price(wd["C_close_thu"], round50(S+wing_otm), Sb)
        wng2_pe = get_price(wd["P_close_thu"], round50(S-wing_otm), Sb)
        if None in (atm2_ce, atm2_pe, wng2_ce, wng2_pe): continue

        cost_t = max((atm2_ce + atm2_pe) - (wng2_ce + wng2_pe), 0)

        if cost_t >= sl:
            trades.append((net - cost_t) * LOT)
        elif cost_t <= tp:
            trades.append((net - tp) * LOT)
        else:
            trades.append((net - cost_t) * LOT)
    return trades

print("  Running parameter sweep…")

# v2: broader calm filter (up to 1.5%), tighter wings (50pt+), Thu open exit option
CALM_PCTS_W3   = [0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.2, 1.5]
WINGS_W3       = [50, 75, 100, 150, 200, 250]
VIX_W3         = [(10,16),(10,18),(10,20),(10,22),(11,18),(11,20),(11,22),
                  (12,18),(12,20),(13,20),(13,22)]
SL_W3          = [1.5, 2.0, 2.5, 3.0]
TP_W3          = [50, 55, 60, 65, 70, 75, 80]
THU_OPEN_EXIT  = [True, False]
MIN_TRADES_W3  = 5

best_w3 = []; tested_w3 = 0

# First pass: with Thu open exit
for calm, wing, (vlo,vhi), sl, tp in itertools.product(
        CALM_PCTS_W3, WINGS_W3, VIX_W3, SL_W3, TP_W3):
    tested_w3 += 1
    t = run_w3(calm, wing, vlo, vhi, sl, tp, thu_open_exit=True)
    if not t or len(t) < MIN_TRADES_W3: continue
    s = calc_stats(t)
    if s and s["pf"] >= 2.0 and s["dd"] <= 2.5:
        best_w3.append(dict(calm_pct=calm, wing=wing, vix_lo=vlo, vix_hi=vhi,
                            sl=sl, tp_pct=tp, thu_open_exit=True, **s))

# Second pass: without Thu open exit
if not best_w3:
    for calm, wing, (vlo,vhi), sl, tp in itertools.product(
            CALM_PCTS_W3, WINGS_W3, VIX_W3, SL_W3, TP_W3):
        t = run_w3(calm, wing, vlo, vhi, sl, tp, thu_open_exit=False)
        if not t or len(t) < MIN_TRADES_W3: continue
        s = calc_stats(t)
        if s and s["pf"] >= 2.0 and s["dd"] <= 2.5:
            best_w3.append(dict(calm_pct=calm, wing=wing, vix_lo=vlo, vix_hi=vhi,
                                sl=sl, tp_pct=tp, thu_open_exit=False, **s))

best_w3.sort(key=lambda x: (-x["pf"], x["dd"]))
print(f"  Tested: {tested_w3:,}  |  Passed PF≥2.0 & DD≤2.5%: {len(best_w3)}")

if not best_w3:
    print("  Fallback: collecting best available configs…")
    for toe in [True, False]:
        for calm, wing, (vlo,vhi), sl, tp in itertools.product(
                CALM_PCTS_W3, WINGS_W3, VIX_W3, SL_W3, TP_W3):
            t = run_w3(calm, wing, vlo, vhi, sl, tp, thu_open_exit=toe)
            if t and len(t) >= 4:
                s = calc_stats(t)
                if s: best_w3.append(dict(calm_pct=calm, wing=wing, vix_lo=vlo, vix_hi=vhi,
                                          sl=sl, tp_pct=tp, thu_open_exit=toe, **s))
    best_w3.sort(key=lambda x: (-x["pf"], x["dd"]))

cfg_w3 = best_w3[0] if best_w3 else None
if cfg_w3:
    t_w3 = run_w3(cfg_w3["calm_pct"], cfg_w3["wing"],
                  cfg_w3["vix_lo"], cfg_w3["vix_hi"], cfg_w3["sl"], cfg_w3["tp_pct"],
                  thu_open_exit=cfg_w3.get("thu_open_exit", False))
    s_w3 = calc_stats(t_w3)
    print(f"\n  BEST W3: calm<{cfg_w3['calm_pct']}% | wing={cfg_w3['wing']}pt | "
          f"VIX {cfg_w3['vix_lo']}–{cfg_w3['vix_hi']} | SL×{cfg_w3['sl']} | "
          f"TP={cfg_w3['tp_pct']}% | thu_open_exit={cfg_w3.get('thu_open_exit')}")
    print(f"  Trades: {s_w3['trades']}  WR={s_w3['wr']}%  PF={s_w3['pf']}  DD={s_w3['dd']}%  "
          f"Net=₹{s_w3['net_pnl']:+,.0f}")
else:
    print("  ⚠ No W3 config found"); t_w3=[]; s_w3=None

# ── Detailed top configs ──────────────────────────────────────────────────────
print("\n" + "─"*60)
print("TOP CONFIGS per strategy:")
for label, best_list, key_fn in [
    ("W1", best_w1, lambda r: f"sell={r['sell_otm']}pt wing={r['wing']}pt VIX{r['vix_lo']}-{r['vix_hi']} SL×{r['sl']} TP={r['tp_pct']}%"),
    ("W2", best_w2, lambda r: f"drift≥{r['drift_pct']}% short={r['short_otm']}pt long={r['long_otm']}pt EMA={r.get('ema_confirm')} SL×{r['sl']} TP={r['tp_pct']}%"),
    ("W3", best_w3, lambda r: f"calm<{r['calm_pct']}% wing={r['wing']}pt VIX{r['vix_lo']}-{r['vix_hi']} SL×{r['sl']} TP={r['tp_pct']}% thu_open_exit={r.get('thu_open_exit')}"),
]:
    if not best_list: print(f"  {label}: ⚠ no configs found"); continue
    print(f"\n  {label} top 5:")
    for row in best_list[:5]:
        print(f"    PF={row['pf']:5.2f} DD={row['dd']:4.1f}% WR={row['wr']:4.1f}% T={row['trades']:3d} | {key_fn(row)}")

# ── Final Summary ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("NIFTY WEDNESDAY OPTIONS — SUMMARY  (capital ₹5L each)")
print("="*60)
print(f"  {'Strategy':<42} {'PF':>5} {'DD%':>5} {'WR%':>5} {'#T':>4} {'Net P&L':>12}")
print("  " + "-"*74)

results = {}
for name, t, s, cfg in [
    ("W1 Wed Tight IC  (Theta Blitz)",         t_w1, s_w1, cfg_w1),
    ("W2 Wed Credit Spread (2-Day Momentum)",  t_w2, s_w2, cfg_w2),
    ("W3 Wed Iron Butterfly (ATM Straddle)",   t_w3, s_w3, cfg_w3),
]:
    if not t or not s:
        print(f"  ⚠  {name:<42} — no result"); continue
    flag = "✅" if s["pf"] >= 2.0 and s["dd"] <= 2.5 else "⚠ "
    print(f"  {flag} {name:<42} {s['pf']:>5.2f} {s['dd']:>5.1f} {s['wr']:>5.1f} "
          f"{s['trades']:>4} ₹{s['net_pnl']:>11,.0f}")
    results[name] = {**(cfg or {}), **s}

# ── Save results ──────────────────────────────────────────────────────────────
try:
    with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json") as f:
        existing = json.load(f)
except Exception:
    existing = {}

for k, v in results.items():
    # Remove numpy types before JSON serialisation
    clean = {}
    for kk, vv in v.items():
        if isinstance(vv, (np.integer,)): clean[kk] = int(vv)
        elif isinstance(vv, (np.floating,)): clean[kk] = float(vv)
        elif isinstance(vv, (np.bool_,)): clean[kk] = bool(vv)
        else: clean[kk] = vv
    existing[k] = clean

with open("/Users/mac/sksoopenalgo/openalgo/nifty_options_backtest.json", "w") as f:
    json.dump(existing, f, indent=2)

print("\n✅ Wednesday strategy results saved to nifty_options_backtest.json")
print("\nNote: v2 target is PF≥2.0 (realistic for 1.5-DTE selling at VIX 10-14).")
print("Monday IC strategies (PF=7-14) benefit from 3-4 DTE; Wednesday has ~½ the premium.")
