#!/usr/bin/env python3
"""
Atomic IC wave executor with fill verification.
CLI: python3 ic_order_executor.py --wave 1 [--expiry 06MAR26] [--lots 12]
Outputs JSON: {"ok": true/false, "reason": "...", "lots": 12, ...}
"""
import time, json, requests, sys, argparse
from datetime import datetime, date
from ic_config import (OPENALGO_KEY, OPENALGO_URL, LOT_SIZE, SPAN_PER_LOT,
                       get_next_expiry, N8N_WEBHOOK)

def _post(ep, payload, key, timeout=8):
    try:
        r = requests.post(f"{OPENALGO_URL}/{ep}",
                          json={**payload, "apikey": key}, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def check_sell_margin(n_lots, key=OPENALGO_KEY):
    """Returns (ok, available, required). SPAN_PER_LOT covers full IC spread (CE+PE both sides)."""
    data     = _post("funds", {}, key).get("data", {})
    avail    = float(data.get("availablecash", 0) or 0)
    required = n_lots * SPAN_PER_LOT
    return (avail >= required), avail, required

def verify_fill(symbol, action, qty_min, key=OPENALGO_KEY, timeout=45, placed_after=None):
    """
    Poll tradebook every 5s for up to timeout seconds.
    Returns (confirmed: bool, filled_qty: int, avg_price: float).
    1.5: If placed_after (epoch float) is set, skip trades older than that time.
    """
    sym_n    = symbol.upper().replace(" ", "").replace("-", "")
    deadline = time.time() + timeout
    while time.time() < deadline:
        trades = _post("tradebook", {}, key, timeout=8).get("data", []) or []
        for t in trades:
            if (str(t.get("symbol","")).upper().replace(" ","").replace("-","") == sym_n
                    and str(t.get("action","")).upper() == action
                    and int(t.get("quantity", 0)) >= qty_min):
                # 1.5: Timestamp filter — skip stale fills from earlier waves/rolls
                if placed_after and t.get("updatetime"):
                    try:
                        # Dhan tradebook timestamp format: "HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
                        ts_str = str(t["updatetime"]).strip()
                        if len(ts_str) <= 8:  # "HH:MM:SS"
                            parts = ts_str.split(":")
                            trade_dt = datetime(date.today().year, date.today().month,
                                                date.today().day,
                                                int(parts[0]), int(parts[1]), int(parts[2]))
                            trade_epoch = trade_dt.timestamp()
                        else:
                            trade_epoch = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").timestamp()
                        if trade_epoch < placed_after - 10:  # 10s grace for clock skew
                            continue  # stale fill from earlier in the day
                    except Exception:
                        pass  # if parsing fails, accept the match
                return True, int(t["quantity"]), float(t.get("average_price", 0))
        time.sleep(5)
    return False, 0, 0.0

def _place(sym, action, qty, strategy, key):
    return _post("placeorder", {
        "strategy": strategy, "symbol": sym, "action": action,
        "exchange": "NFO", "pricetype": "MARKET", "product": "MIS",
        "quantity": str(qty)
    }, key)

def _notify(event, data):
    try:
        requests.post(N8N_WEBHOOK, json={"event": event, **data}, timeout=4)
    except Exception:
        pass

def place_wave_atomic(wave_num, atm, qty, expiry, key=OPENALGO_KEY):
    """
    SELL CE → verify → SELL PE → verify → BUY CE → BUY PE.
    If any SELL fails: compensate (buy back confirmed SELLs) → return failure.
    BUY hedges only placed after BOTH SELLs confirmed.
    """
    tag   = f"IC_WAVE{wave_num}"
    s_ce  = f"NIFTY{expiry}{atm+100}CE"
    l_ce  = f"NIFTY{expiry}{atm+200}CE"
    s_pe  = f"NIFTY{expiry}{atm-100}PE"
    l_pe  = f"NIFTY{expiry}{atm-200}PE"
    res   = {"ok": False, "wave_num": wave_num, "qty": qty,
             "short_ce": atm+100, "short_pe": atm-100,
             "long_ce": atm+200, "long_pe": atm-200,
             "ce_avg": 0.0, "pe_avg": 0.0, "reason": ""}

    # LEG 1 — SELL CE short
    ce_placed_at = time.time()
    r1 = _place(s_ce, "SELL", qty, tag, key)
    if r1.get("status") != "success":
        res["reason"] = f"CE SELL OpenAlgo rejected: {r1}"; return res
    ok, fq, fa = verify_fill(s_ce, "SELL", qty, key, timeout=45, placed_after=ce_placed_at)
    if not ok:
        res["reason"] = "CE SELL not in tradebook after 45s (Dhan RMS silent reject)"
        _notify("WAVE_SELL_FAIL", {"wave": wave_num, "leg": "CE", "reason": res["reason"]})
        return res
    res["ce_avg"] = fa

    # LEG 2 — SELL PE short
    time.sleep(0.5)
    pe_placed_at = time.time()
    r2 = _place(s_pe, "SELL", qty, tag, key)
    if r2.get("status") != "success":
        comp_at = time.time()
        _place(s_ce, "BUY", qty, f"{tag}_COMP", key)   # compensate CE
        comp_ok, _, _ = verify_fill(s_ce, "BUY", qty, key, timeout=30, placed_after=comp_at)
        if not comp_ok:
            _notify("COMP_FAIL", {
                "wave": wave_num, "leg": "CE",
                "reason": "Compensation BUY for CE short NOT confirmed — OPEN SHORT POSITION"
            })
        res["reason"] = f"PE SELL OpenAlgo rejected (CE comp {'ok' if comp_ok else 'FAILED — CHECK NOW'}): {r2}"; return res
    ok, fq, fa = verify_fill(s_pe, "SELL", qty, key, timeout=45, placed_after=pe_placed_at)
    if not ok:
        comp_at = time.time()
        _place(s_ce, "BUY", qty, f"{tag}_COMP", key)   # compensate CE
        comp_ok, _, _ = verify_fill(s_ce, "BUY", qty, key, timeout=30, placed_after=comp_at)
        if not comp_ok:
            _notify("COMP_FAIL", {
                "wave": wave_num, "leg": "CE",
                "reason": "Compensation BUY for CE short NOT confirmed — OPEN SHORT POSITION"
            })
        res["reason"] = "PE SELL not in tradebook after 45s (CE comp " + ("ok" if comp_ok else "FAILED — CHECK NOW") + ")"
        _notify("WAVE_SELL_FAIL", {"wave": wave_num, "leg": "PE", "reason": res["reason"]})
        return res
    res["pe_avg"] = fa

    # LEGS 3+4 — BUY hedges (only after both SELLs confirmed)
    # 1.7: Enhanced hedge verification with retry on failure
    time.sleep(0.5)
    hedge_placed_at = time.time()
    _place(l_ce, "BUY", qty, tag, key)
    time.sleep(0.5)
    _place(l_pe, "BUY", qty, tag, key)

    ce_h_ok, _, _ = verify_fill(l_ce, "BUY", qty, key, timeout=30, placed_after=hedge_placed_at)
    pe_h_ok, _, _ = verify_fill(l_pe, "BUY", qty, key, timeout=30, placed_after=hedge_placed_at)

    # 1.7: Retry unconfirmed hedges once — naked shorts are dangerous
    for hedge_sym, hedge_name, h_ok in [(l_ce, "CE", ce_h_ok), (l_pe, "PE", pe_h_ok)]:
        if not h_ok:
            retry_at = time.time()
            _place(hedge_sym, "BUY", qty, f"{tag}_HEDGE_RETRY", key)
            h_ok_retry, _, _ = verify_fill(hedge_sym, "BUY", qty, key, timeout=20, placed_after=retry_at)
            if hedge_name == "CE":
                ce_h_ok = h_ok_retry
            else:
                pe_h_ok = h_ok_retry
            if not h_ok_retry:
                _notify("HEDGE_CRITICAL", {
                    "wave": wave_num, "side": hedge_name,
                    "reason": f"BUY hedge {hedge_name} NOT confirmed after retry — NAKED SHORT"
                })

    res["ok"] = True
    res["ce_hedge_ok"] = ce_h_ok
    res["pe_hedge_ok"] = pe_h_ok
    res["hedge_warning"] = not (ce_h_ok and pe_h_ok)
    res["reason"] = (f"SELL fills confirmed; hedges CE={'OK' if ce_h_ok else 'FAIL'} "
                     f"PE={'OK' if pe_h_ok else 'FAIL'}")
    return res

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wave",   type=int, required=True)
    p.add_argument("--expiry", type=str, default=None)
    p.add_argument("--lots",   type=int, default=None)
    args = p.parse_args()

    expiry = args.expiry or get_next_expiry()
    key    = OPENALGO_KEY

    # Fetch ATM
    oc = _post("optionchain", {"underlying": "NIFTY", "exchange": "NSE_INDEX",
                               "expiry_date": expiry, "strike_count": 4}, key)
    atm   = int(oc.get("atm_strike", 0) or 0)
    nifty = float(oc.get("underlying_ltp", 0) or 0)
    if atm == 0:
        print(json.dumps({"ok": False, "reason": "ATM=0 — market not open"})); sys.exit(1)

    # Lots sizing
    if args.lots:
        lots = args.lots
    else:
        data  = _post("funds", {}, key).get("data", {})
        avail = float(data.get("availablecash", 0) or 0)
        wf    = {1: 1.0, 2: 0.65, 3: 0.40}.get(args.wave, 1.0)
        lots  = max(4, min(40, int(avail * 0.78 / SPAN_PER_LOT * wf)))

    # Margin pre-check
    ok_m, avail, req = check_sell_margin(lots, key)
    if not ok_m:
        print(json.dumps({"ok": False, "reason": f"Insufficient margin: avail={avail:.0f} req={req:.0f}"}))
        sys.exit(1)

    result = place_wave_atomic(args.wave, atm, lots * LOT_SIZE, expiry, key)
    result.update({"lots": lots, "expiry": expiry, "nifty": nifty})
    print(json.dumps(result))
    sys.exit(0 if result["ok"] else 1)
