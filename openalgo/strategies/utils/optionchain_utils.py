import logging
import random
import requests
import time
from datetime import datetime, timedelta

try:
    from .trading_utils import (
        safe_float,
        safe_int,
        normalize_expiry,
        choose_nearest_expiry,
        choose_monthly_expiry,
        is_chain_valid,
        get_atm_strike,
        calculate_straddle_premium,
    )
except ImportError:
    # Fallback if running as script or different context
    try:
        from trading_utils import (
            safe_float,
            safe_int,
            normalize_expiry,
            choose_nearest_expiry,
            choose_monthly_expiry,
            is_chain_valid,
            get_atm_strike,
            calculate_straddle_premium,
        )
    except ImportError:
        # Fallback implementation if trading_utils not found (should not happen in prod)
        def safe_float(value, default=0.0):
            try:
                if value is None: return default
                return float(value)
            except (ValueError, TypeError): return default

        def safe_int(value, default=0):
            try:
                if value is None: return default
                return int(float(value))
            except (ValueError, TypeError): return default

        def normalize_expiry(expiry_date):
            if not expiry_date: return None
            try:
                expiry_date = expiry_date.strip().upper()
                datetime.strptime(expiry_date, "%d%b%y")
                return expiry_date
            except ValueError: pass
            return expiry_date

_oc_logger = logging.getLogger("OptionChainClient")


class _OCCircuitBreaker:
    """Lightweight circuit breaker for option chain API calls."""

    def __init__(self, failure_threshold=3, recovery_timeout=120.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_fail = 0.0
        self._open = False

    def allow(self) -> bool:
        if not self._open:
            return True
        if time.time() - self._last_fail >= self.recovery_timeout:
            self._open = False
            self._failures = 0
            _oc_logger.info("OC circuit breaker → CLOSED (recovery timeout elapsed)")
            return True
        return False

    def success(self):
        self._failures = 0
        if self._open:
            self._open = False
            _oc_logger.info("OC circuit breaker → CLOSED (success)")

    def failure(self):
        self._failures += 1
        self._last_fail = time.time()
        if self._failures >= self.failure_threshold and not self._open:
            self._open = True
            _oc_logger.warning(
                f"OC circuit breaker → OPEN after {self._failures} consecutive failures"
            )


class OptionChainClient:
    def __init__(self, api_key, host="http://127.0.0.1:5000"):
        self.api_key = api_key
        self.host = host.rstrip('/')
        self.session = requests.Session()
        self._breaker = _OCCircuitBreaker(failure_threshold=3, recovery_timeout=120)

    def _post(self, endpoint, payload, max_retries=3):
        url = f"{self.host}/api/v1/{endpoint}"
        payload["apikey"] = self.api_key

        if not self._breaker.allow():
            _oc_logger.warning(f"OC circuit breaker OPEN — skipping {endpoint}")
            return {"status": "error", "message": "circuit_breaker_open"}

        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                response = self.session.post(url, json=payload, timeout=10)
                response.raise_for_status()
                self._breaker.success()
                return response.json()
            except Exception as e:
                last_exc = e
                self._breaker.failure()
                if attempt < max_retries:
                    wait = (2 ** attempt) + random.uniform(0, 0.3)
                    _oc_logger.info(
                        f"OC retry {attempt + 1}/{max_retries} for {endpoint} in {wait:.1f}s"
                    )
                    time.sleep(wait)

        _oc_logger.error(f"OC API Error ({endpoint}) after {max_retries} retries: {last_exc}")
        return {"status": "error", "message": str(last_exc)}

    def expiry(self, underlying, exchange, instrument_type="options"):
        return self._post("expiry", {
            "symbol": underlying,          # API expects "symbol", not "underlying"
            "exchange": exchange,
            "instrumenttype": instrument_type  # API expects "instrumenttype" (no underscore)
        })

    def optionchain(self, underlying, exchange, expiry_date, strike_count=10):
        res = self._post("optionchain", {
            "underlying": underlying,
            "exchange": exchange,
            "expiry_date": expiry_date,
            "strike_count": strike_count
        })
        # The API returns the chain under the "chain" key; callers expect "data".
        # Normalise so both keys work.
        if isinstance(res, dict) and "chain" in res and "data" not in res:
            res["data"] = res["chain"]
        return res

    def optionsmultiorder(self, strategy, underlying, exchange, expiry_date, legs):
        return self._post("optionsmultiorder", {
            "strategy": strategy,
            "underlying": underlying,
            "exchange": exchange,
            "expiry_date": expiry_date,
            "legs": legs
        })

    def placesmartorder(self, strategy, symbol, action, exchange, pricetype, product, quantity, position_size):
        """
        Places a smart order (single leg).
        """
        payload = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "action": action,
            "exchange": exchange,
            "pricetype": pricetype,
            "product": product,
            "quantity": str(quantity),
            "position_size": str(position_size),
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0"
        }
        # Note: endpoint is placesmartorder (not _post generic if key names differ, but here we construct payload manually)
        # Using _post wrapper might be cleaner but _post adds apikey.
        # Let's use _post but we need to be careful about payload structure if _post modifies it.
        # _post does: payload["apikey"] = self.api_key.
        # So we can just pass the fields.

        return self._post("placesmartorder", {
            "strategy": strategy,
            "symbol": symbol,
            "action": action,
            "exchange": exchange,
            "pricetype": pricetype,
            "product": product,
            "quantity": str(quantity),
            "position_size": str(position_size),
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0"
        })

    def get_quote(self, symbol, exchange="NSE"):
        """
        Fetches a real-time quote for a symbol.
        Returns the data dictionary (containing ltp, etc.) or None.
        """
        res = self._post("quotes", {
            "symbol": symbol,
            "exchange": exchange
        })

        if res.get("status") == "success" and "data" in res:
            return res["data"]
        return None

def validate_multiorder_response(resp: dict, expected_legs: int) -> tuple:
    """
    Validates an optionsmultiorder response at the leg level.

    The OpenAlgo /api/v1/optionsmultiorder endpoint can return outer
    status='success' even when individual legs fail.  This function
    inspects each inner leg response to detect partial fills.

    Args:
        resp:           Raw JSON response from optionsmultiorder.
        expected_legs:  Number of legs we expected to fill.

    Returns:
        (all_ok, failed_legs, resp)
        - all_ok:       True only if outer status=success AND every leg succeeded.
        - failed_legs:  List of dicts describing each failed leg
                        (index, symbol, action, message).
        - resp:         The original response dict (pass-through for logging).
    """
    failed_legs = []

    # 1. Outer status check
    if resp.get("status") != "success":
        _oc_logger.error(f"multiorder outer status={resp.get('status')}: {resp.get('message', '')}")
        return False, [{"index": -1, "symbol": "ALL", "action": "", "message": resp.get("message", "outer_failure")}], resp

    # 2. Inner leg inspection
    # The API may return leg results under various keys; try common ones.
    leg_results = resp.get("results", resp.get("data", resp.get("legs", [])))
    if not isinstance(leg_results, list):
        leg_results = []

    # If the API didn't return per-leg results, check for embedded message patterns
    if not leg_results:
        # Some API versions embed failures in the message string
        msg = str(resp.get("message", "")).lower()
        if "fail" in msg or "rejected" in msg or "error" in msg:
            _oc_logger.warning(f"multiorder message suggests failure: {resp.get('message')}")
            failed_legs.append({
                "index": -1, "symbol": "UNKNOWN", "action": "",
                "message": resp.get("message", "embedded_failure_in_message")
            })
            return False, failed_legs, resp
        # No per-leg data and no failure signal — trust outer status but warn
        if expected_legs > 0:
            _oc_logger.info(
                f"multiorder: outer success, no per-leg data returned "
                f"(expected {expected_legs} legs). Treating as OK."
            )
        return True, [], resp

    # 3. Validate each leg result
    for idx, leg in enumerate(leg_results):
        leg_status = str(leg.get("status", "")).lower()
        leg_msg = str(leg.get("message", ""))

        is_failed = (
            leg_status in ("error", "failed", "rejected")
            or "fail" in leg_msg.lower()
            or "rejected" in leg_msg.lower()
            or "error" in leg_msg.lower()
        )

        if is_failed:
            failed_legs.append({
                "index": idx,
                "symbol": leg.get("symbol", leg.get("tradingsymbol", f"leg_{idx}")),
                "action": leg.get("action", "?"),
                "message": leg_msg,
            })

    # 4. Check leg count mismatch
    if len(leg_results) != expected_legs:
        _oc_logger.warning(
            f"multiorder leg count mismatch: expected {expected_legs}, got {len(leg_results)}"
        )
        if not failed_legs:
            failed_legs.append({
                "index": -1, "symbol": "COUNT_MISMATCH", "action": "",
                "message": f"expected {expected_legs} legs, API returned {len(leg_results)}"
            })

    all_ok = len(failed_legs) == 0
    if not all_ok:
        for fl in failed_legs:
            _oc_logger.error(
                f"multiorder leg FAILED: idx={fl['index']} sym={fl['symbol']} "
                f"action={fl['action']} msg={fl['message']}"
            )

    return all_ok, failed_legs, resp


def reconcile_broker_positions(state: dict, api_key: str, host: str = "http://127.0.0.1:5002") -> bool:
    """
    Conservative position reconciliation: if local state says we have a
    position but the broker's positionbook shows FLAT (zero net qty) for
    ALL relevant symbols, clear local state.

    Only clears when broker shows **zero** positions — never modifies on
    quantity mismatch (avoids race conditions).

    Args:
        state:   The strategy's state dict (must have 'position' key).
        api_key: OpenAlgo API key.
        host:    OpenAlgo host URL.

    Returns:
        True if state was cleared (position reconciled to FLAT), False otherwise.
    """
    pos = state.get("position")
    if not pos:
        return False  # Nothing to reconcile — already flat

    # Gather all option symbols from state
    short_oc = pos.get("short_oc", [])
    long_oc = pos.get("long_oc", [])
    if not short_oc and not long_oc:
        return False

    # Query broker positionbook
    try:
        resp = requests.post(
            f"{host.rstrip('/')}/api/v1/positionbook",
            json={"apikey": api_key},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") != "success":
            _oc_logger.warning(f"reconcile: positionbook API failed: {data.get('message', '')}")
            return False
    except Exception as e:
        _oc_logger.warning(f"reconcile: positionbook request error: {e}")
        return False

    # Build broker position map: symbol -> net qty
    broker_positions = {}
    for p in data.get("data", []):
        sym = p.get("symbol", "")
        qty = safe_int(p.get("quantity", 0))
        if sym:
            broker_positions[sym] = qty

    # Check: if ALL option symbols show zero qty at broker → state is stale
    all_flat = True
    for strike_label, opt_type in short_oc + long_oc:
        # We don't have exact symbol names in state, but we can check
        # if there are ANY NFO positions at all
        pass

    # Simpler approach: check if broker has ANY non-zero NFO/MCX positions
    # that look like options (contain CE/PE in symbol)
    nfo_positions = {
        sym: qty for sym, qty in broker_positions.items()
        if qty != 0 and ("CE" in sym.upper() or "PE" in sym.upper())
    }

    if nfo_positions:
        # Broker still has option positions — don't clear
        return False

    # Broker shows zero option positions — local state is stale
    _oc_logger.warning(
        f"reconcile: LOCAL state has position but BROKER shows FLAT. "
        f"Clearing local state. short_oc={short_oc} long_oc={long_oc}"
    )
    state["position"] = None
    return True


class OptionPositionTracker:
    def __init__(self, sl_pct, tp_pct, max_hold_min):
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.max_hold_min = max_hold_min
        self.open_legs = []     # List of dicts: {symbol, action, entry_price, quantity, ...}
        self.entry_time = None
        self.side = None        # "BUY" or "SELL" (net position bias)

    def add_legs(self, legs, entry_prices, side):
        """
        legs: List of leg details dicts (must contain 'symbol', 'action', 'quantity')
        entry_prices: List of entry prices corresponding to legs
        side: "BUY" (Net Long/Debit) or "SELL" (Net Short/Credit)
        """
        self.open_legs = []
        self.entry_time = datetime.now()
        self.side = side.upper()

        for i, leg in enumerate(legs):
            leg_data = leg.copy()
            leg_data["entry_price"] = safe_float(entry_prices[i])
            self.open_legs.append(leg_data)

    def should_exit(self, chain):
        """
        Checks exit conditions based on current chain data.
        Returns: (bool exit_now, list legs, string reason)
        """
        if not self.open_legs:
            return False, [], ""

        # 1. Time Stop
        minutes_held = (datetime.now() - self.entry_time).total_seconds() / 60
        if minutes_held >= self.max_hold_min:
            return True, self.open_legs, "time_stop"

        # 2. PnL Check
        total_entry_val = 0.0
        total_curr_val = 0.0

        # Calculate total value of the spread/condor
        # For SELL strategy (Credit): Entry > Current is Profit
        # For BUY strategy (Debit): Current > Entry is Profit

        # We need to map chain LTPs to our legs
        # Create a lookup map: symbol -> ltp
        ltp_map = {}
        for item in chain:
            ce = item.get("ce", {})
            pe = item.get("pe", {})
            if ce.get("symbol"): ltp_map[ce["symbol"]] = safe_float(ce.get("ltp"))
            if pe.get("symbol"): ltp_map[pe["symbol"]] = safe_float(pe.get("ltp"))

        # Calculate PnL per leg
        # Note: quantities are assumed equal for pct calc simplification,
        # but properly we should weigh by quantity.

        current_pnl_pct = 0.0

        # We will track aggregate premium
        # e.g., Iron Condor: Sold @ 100+100=200. Bought @ 20+20=40. Net Credit = 160.
        # If Net Credit shrinks, we profit.

        net_entry_premium = 0.0
        net_current_premium = 0.0

        for leg in self.open_legs:
            sym = leg["symbol"]
            entry = leg["entry_price"]
            curr = ltp_map.get(sym, entry) # Fallback to entry if no LTP found (neutral)
            qty = leg.get("quantity", 1)

            action = leg["action"].upper()

            if action == "SELL":
                net_entry_premium += entry
                net_current_premium += curr
            else: # BUY
                net_entry_premium -= entry
                net_current_premium -= curr

        # Calculate PnL based on Strategy Side
        # side="SELL" implies we want Net Premium to DECREASE (if net credit)
        # or implies we are Net Short Options.

        # Let's simplify:
        # PnL = (Entry - Current) for SELL
        # PnL = (Current - Entry) for BUY

        # Wait, strictly speaking:
        # PnL = Sum(Sell_Entry - Sell_Curr) + Sum(Buy_Curr - Buy_Entry)

        pnl = 0.0
        total_initial_premium_abs = 0.0 # To calculate percentage

        for leg in self.open_legs:
            sym = leg["symbol"]
            entry = leg["entry_price"]
            curr = ltp_map.get(sym, entry)

            if leg["action"].upper() == "SELL":
                pnl += (entry - curr)
                total_initial_premium_abs += entry
            else:
                pnl += (curr - entry)
                total_initial_premium_abs += entry # Add to basis for % calculation?
                # Usually SL% is based on the premium collected (for credit) or paid (for debit).

        # If total_initial_premium_abs is 0, avoid div by zero
        if total_initial_premium_abs == 0:
            return False, [], ""

        pnl_pct = (pnl / total_initial_premium_abs) * 100

        # Check Stops
        # SL: pnl_pct < -SL_PCT
        if pnl_pct <= -self.sl_pct:
            return True, self.open_legs, f"stop_loss_hit ({pnl_pct:.1f}%)"

        # TP: pnl_pct > TP_PCT
        if pnl_pct >= self.tp_pct:
            return True, self.open_legs, f"take_profit_hit ({pnl_pct:.1f}%)"

        return False, [], ""

    def clear(self):
        self.open_legs = []
        self.entry_time = None
        self.side = None
