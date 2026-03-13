#!/usr/bin/env python3
"""
NIFTY 10MAR26 Expiry Monitor
Watches positions until settlement. Alerts on key thresholds.
Run: nohup python3 /Users/mac/sksoopenalgo/openalgo/expiry_monitor.py >> expiry_monitor.log 2>&1 &
"""
import requests, json, time, os, subprocess
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")
KEY = "09854f66270c372a56b5560970270d00e375d2e63131a3f5d9dd0f7d2505aae7"
ENV_FILE = "/Users/mac/sksoopenalgo/openalgo/.env"
EXPIRY = "10MAR26"
REALIZED_PNL = -550  # from ic_monitor's MIS close orders

# Open NIFTY positions: (sym, opt_type, direction, qty, avg_entry)
POSITIONS = [
    ("24500PE", "PE", +1, 65, 282.55),
    ("24600CE", "CE", -1, 65, 317.60),
    ("24600PE", "PE", -1, 65, 321.10),
    ("24650PE", "PE", -1, 65, 163.15),
    ("24700CE", "CE", +1, 65, 261.55),
    ("24750CE", "CE", +1, 65, 231.05),
    ("24750PE", "PE", +1, 65, 200.15),
    ("24850CE", "CE", -1, 65, 173.90),
]

# Alert thresholds
PROFIT_ALERT = 24_550    # NIFTY reaching profit zone — consider taking profit
DANGER_ALERT = 24_650    # NIFTY entering loss zone — consider closing
HARD_CLOSE_H = 15
HARD_CLOSE_M = 10

def load_token():
    try:
        for line in open(ENV_FILE):
            if line.startswith("DHAN_ACCESS_TOKEN="):
                return line.strip().split("=", 1)[1]
    except:
        pass
    return ""

def get_nifty(token):
    """Get NIFTY LTP via option chain"""
    try:
        r = requests.post("http://127.0.0.1:5002/api/v1/optionchain",
            json={"apikey": KEY, "underlying": "NIFTY",
                  "exchange": "NSE_INDEX", "expiry_date": EXPIRY, "strike_count": 3},
            timeout=5)
        return r.json().get("underlying_ltp", 0)
    except:
        return 0

def settlement_pnl(nifty):
    total = 0
    for sym, opt_type, direction, qty, entry in POSITIONS:
        strike = int(sym[:5])
        intr = max(strike - nifty, 0) if opt_type == "PE" else max(nifty - strike, 0)
        total += direction * (intr - entry) * qty
    return total

def send_alert(msg):
    """System notification"""
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "{msg}" with title "🚨 NIFTY EXPIRY ALERT"'],
            timeout=3)
    except:
        pass
    print(f"🔔 ALERT: {msg}")

def place_close_order(symbol, action, qty):
    """Close a NIFTY NRML position"""
    try:
        r = requests.post("http://127.0.0.1:5002/api/v1/placeorder",
            json={"apikey": KEY, "strategy": "EXPIRY_CLOSE",
                  "symbol": symbol, "action": action, "exchange": "NFO",
                  "pricetype": "MARKET", "product": "NRML", "quantity": qty},
            timeout=10)
        result = r.json()
        status = "✅" if result.get("status") == "success" else "❌"
        return status, result.get("orderid", result.get("message", "?"))
    except Exception as e:
        return "❌", str(e)

def hard_close_all():
    """Emergency: close all 8 NIFTY NRML positions with NRML product type"""
    print("\n" + "="*60)
    print("🔴 HARD CLOSE — CLOSING ALL 8 NIFTY POSITIONS (NRML)")
    print("="*60)
    # Buy to close SHORTs, Sell to close LONGs
    close_orders = [
        (f"NIFTY{EXPIRY}24500PE", "SELL", 65),  # LONG → SELL
        (f"NIFTY{EXPIRY}24600CE", "BUY",  65),  # SHORT → BUY
        (f"NIFTY{EXPIRY}24600PE", "BUY",  65),  # SHORT → BUY
        (f"NIFTY{EXPIRY}24650PE", "BUY",  65),  # SHORT → BUY
        (f"NIFTY{EXPIRY}24700CE", "SELL", 65),  # LONG → SELL
        (f"NIFTY{EXPIRY}24750CE", "SELL", 65),  # LONG → SELL
        (f"NIFTY{EXPIRY}24750PE", "SELL", 65),  # LONG → SELL
        (f"NIFTY{EXPIRY}24850CE", "BUY",  65),  # SHORT → BUY
    ]
    for sym, action, qty in close_orders:
        status, oid = place_close_order(sym, action, qty)
        print(f"  {action} {sym} {qty} → {status} {oid}")
        time.sleep(0.5)
    print("Hard close complete.")

# ─── MAIN LOOP ──────────────────────────────────────────────────────────────
print("="*60)
print(f"EXPIRY MONITOR STARTED — {datetime.now(IST).strftime('%H:%M:%S IST %d-%b-%Y')}")
print(f"Watching: 8 NIFTY NRML positions expiring {EXPIRY}")
print(f"Profit alert at NIFTY > {PROFIT_ALERT} | Danger alert > {DANGER_ALERT}")
print(f"Hard close at {HARD_CLOSE_H:02d}:{HARD_CLOSE_M:02d} IST")
print(f"Realized locked in: {REALIZED_PNL:+,.0f}")
print("="*60)

last_alert = None
check_interval = 60  # seconds

while True:
    now = IST.localize(datetime.now())
    hm = (now.hour, now.minute)

    # Stop after 15:35 (settlement done)
    if hm >= (15, 35):
        print(f"[{now.strftime('%H:%M:%S')}] Market closed, positions settled. Monitor stopping.")
        break

    nifty = get_nifty(load_token())
    spnl = settlement_pnl(nifty) if nifty > 0 else 0
    grand = spnl + REALIZED_PNL
    mins_to_close = (HARD_CLOSE_H - hm[0]) * 60 + (HARD_CLOSE_M - hm[1])

    zone = "FLAT"
    if 24550 <= nifty < 24650: zone = "★ PROFIT"
    elif 24650 <= nifty < 24800: zone = "⚠️ RISK"
    elif nifty >= 24800: zone = "★ SAFE"

    print(f"[{now.strftime('%H:%M:%S')}] NIFTY={nifty:.1f} | setl_P&L={spnl:+,.0f} | "
          f"GRAND={grand:+,.0f} | T-{mins_to_close}m | {zone}")

    # Alerts
    if nifty > PROFIT_ALERT and last_alert != "profit":
        send_alert(f"NIFTY {nifty:.0f} → Profit zone! Est. Grand P&L = {grand:+,.0f}")
        last_alert = "profit"

    if nifty > DANGER_ALERT and last_alert != "danger":
        send_alert(f"⚠️ NIFTY {nifty:.0f} > 24650! Risk zone — consider closing. Est. Loss = {grand:+,.0f}")
        last_alert = "danger"

    # Hard close at 15:10
    if hm >= (HARD_CLOSE_H, HARD_CLOSE_M) and hm < (15, 15):
        send_alert(f"HARD CLOSE TIME 15:10! NIFTY={nifty:.0f} Grand={grand:+,.0f}")
        hard_close_all()
        break

    time.sleep(check_interval)

print(f"\n[{datetime.now(IST).strftime('%H:%M:%S')}] Expiry monitor exiting.")
