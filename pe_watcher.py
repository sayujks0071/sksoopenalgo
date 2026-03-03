#!/usr/bin/env python3
"""
PE Position Watcher — lightweight single-leg long-put tracker.
Polls every 30s. Hard-closes 25200PE at 15:05 IST or on stop-loss.
"""
import json, time, urllib.request, datetime, sys, os
import pytz

APIKEY   = "09854f66270c372a56b5560970270d00e375d2e63131a3f5d9dd0f7d2505aae7"
BASE     = "http://127.0.0.1:5002/api/v1"
IST      = pytz.timezone("Asia/Kolkata")
SYMBOL   = "NIFTY02MAR2625200PE"
EXPIRY   = "02MAR26"
STRIKE   = 25200
ENTRY    = 59.65
QTY      = 325
CLOSE_HM = (15, 5)       # hard close at 15:05
LOG      = "/Users/mac/openalgo/pe_watcher.log"

_is_tty = os.isatty(1)

def log(msg):
    ts   = datetime.datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _is_tty:   # only write to file when interactive (nohup already redirects stdout)
        with open(LOG, "a") as f:
            f.write(line + "\n")

def oa_post(ep, body, timeout=7):
    body["apikey"] = APIKEY
    req = urllib.request.Request(f"{BASE}/{ep}", json.dumps(body).encode(),
                                  {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def get_ltp():
    d = oa_post("optionchain", {"underlying":"NIFTY","exchange":"NFO","expiry_date":EXPIRY})
    spot = float(d.get("underlying_ltp") or 0)
    for x in d.get("chain", []):
        if int(x.get("strike", 0)) == STRIKE:
            ltp = float(x.get("pe", {}).get("ltp", 0) or 0)
            return spot, ltp
    return spot, 0.0

def close_pe(reason):
    log(f"CLOSING 25200PE — {reason}")
    r = oa_post("placeorder", {
        "strategy": "IC", "symbol": SYMBOL, "exchange": "NFO",
        "action": "SELL", "quantity": str(QTY),
        "pricetype": "MARKET", "product": "MIS"
    }, timeout=10)
    log(f"SELL result: {r}")
    return r.get("status") == "success"

log("=" * 55)
log(f"PE Watcher started | {SYMBOL} | entry={ENTRY} | qty={QTY}")
log(f"Hard close at {CLOSE_HM[0]}:{CLOSE_HM[1]:02d} IST")
log("=" * 55)

while True:
    now   = datetime.datetime.now(IST)
    hm    = (now.hour, now.minute)
    spot, ltp = get_ltp()
    pnl   = (ltp - ENTRY) * QTY if ltp > 0 else 0
    pct   = (ltp - ENTRY) / ENTRY * 100 if ENTRY > 0 else 0

    log(f"NIFTY={spot:,.1f} | 25200PE={ltp:.2f} | P&L={pnl:+,.0f} ({pct:+.1f}%) | dPE={spot-STRIKE:.0f}pt")

    # Hard close at 15:05
    if hm >= CLOSE_HM:
        close_pe("HARD CLOSE 15:05")
        break

    # Safety: if NIFTY spikes above 25500 (PE worthless territory), exit
    if spot > 25500:
        close_pe(f"NIFTY {spot:.0f} > 25500 — PE losing fast")
        break

    # Optional: lock in gains if PE hits 2× entry (₹119.30)
    if ltp >= ENTRY * 2:
        close_pe(f"PE {ltp:.2f} ≥ 2× entry — take profit")
        break

    time.sleep(30)

log("PE Watcher done.")
