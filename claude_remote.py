#!/usr/bin/env python3
"""
Claude Remote Control — ic_monitor skill trigger server
Port 18790 | Tailscale + loopback | Token auth

Lets you trigger any IC trading skill via HTTP POST from:
  - n8n cloud webhook relay
  - Mac Mini via Tailscale: curl -H "X-Remote-Token: TOKEN" http://100.72.75.74:18790/positions
  - SSH from phone: ssh mac 'curl -s -X POST -H "X-Remote-Token: TOKEN" http://localhost:18790/wave1'

Endpoints (no auth):
  GET  /health      → Monitor heartbeat + server status
  GET  /positions   → Live positions + LTPs + P&L (fast, OpenAlgo direct)

Endpoints (X-Remote-Token required):
  POST /wave1       → Run ic-wave1 skill  (Iron Condor Wave 1 entry)
  POST /wave2       → Run ic-wave2 skill  (Add lots at 11:30 AM)
  POST /wave3       → Run ic-wave3 skill  (Add lots at 2:00 PM)
  POST /close       → Run ic-close skill  (Close all positions)
  POST /emergency   → Run ic-emergency skill (Emergency exit now)
  POST /status      → Run ic-status skill (Session status)

Usage:
  python3 /Users/mac/openalgo/claude_remote.py
"""

import http.server
import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
import pytz

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PORT          = 18790
HOST          = "0.0.0.0"     # all interfaces — Tailscale provides network security
REMOTE_TOKEN  = os.environ.get("CLAUDE_REMOTE_TOKEN", "ic-remote-2026")
CLAUDE_BIN    = "/Users/mac/.local/bin/claude"
LOG_FILE      = "/Users/mac/openalgo/claude_remote.log"
IST           = pytz.timezone("Asia/Kolkata")
OPENALGO_URL  = "http://127.0.0.1:5002/api/v1"
OPENALGO_KEY  = os.environ.get("OPENALGO_API_KEY", "09854f66270c372a56b5560970270d00e375d2e63131a3f5d9dd0f7d2505aae7")

# ─── SKILL MAP ───────────────────────────────────────────────────────────────
SKILL_MAP = {
    "/wave1":     "Run the ic-wave1 skill",
    "/wave2":     "Run the ic-wave2 skill",
    "/wave3":     "Run the ic-wave3 skill",
    "/close":     "Run the ic-close skill",
    "/emergency": "Run the ic-emergency skill",
    "/status":    "Run the ic-status skill",
}

# ─── LOGGING ─────────────────────────────────────────────────────────────────
_IS_TTY = os.isatty(1)   # True when running interactively, False under launchd


def log(msg):
    ts   = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    # Only write to file explicitly when interactive (launchd already redirects stdout)
    if _IS_TTY:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ─── SKILL RUNNER ─────────────────────────────────────────────────────────────
_running_skills = {}   # path → subprocess (prevent duplicate parallel calls)
_lock = threading.Lock()


def run_skill(path: str) -> dict:
    """Run a Claude Code skill non-interactively.
    Returns {"status": "ok"|"error"|"busy", "output": str, "elapsed_s": float}
    """
    with _lock:
        if path in _running_skills:
            proc = _running_skills[path]
            if proc.poll() is None:   # still running
                return {"status": "busy", "output": f"{path} already running (PID {proc.pid})"}

    prompt = SKILL_MAP[path]
    log(f"INVOKE {path} → '{prompt}'")
    t0 = time.time()

    try:
        proc = subprocess.Popen(
            [CLAUDE_BIN, "--print", "-p", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="/Users/mac/openalgo"
        )
        with _lock:
            _running_skills[path] = proc

        stdout, _ = proc.communicate(timeout=120)   # 2 min max
        elapsed   = round(time.time() - t0, 1)
        status    = "ok" if proc.returncode == 0 else "error"
        log(f"DONE  {path} [{status}] {elapsed}s")

        # Trim output — return last 2000 chars (enough for status, not bloated)
        output = stdout.strip()
        if len(output) > 2000:
            output = "..." + output[-2000:]

        return {"status": status, "output": output, "elapsed_s": elapsed}

    except subprocess.TimeoutExpired:
        proc.kill()
        log(f"TIMEOUT {path} after 120s")
        return {"status": "error", "output": "Skill timed out after 120s", "elapsed_s": 120}
    except Exception as e:
        log(f"ERROR {path}: {e}")
        return {"status": "error", "output": str(e), "elapsed_s": round(time.time() - t0, 1)}
    finally:
        with _lock:
            _running_skills.pop(path, None)


# ─── LIVE DATA HELPER ─────────────────────────────────────────────────────────
def _oa_post(endpoint: str, payload: dict, timeout: int = 6) -> dict:
    """POST to OpenAlgo and return parsed JSON, or {} on error."""
    try:
        payload["apikey"] = OPENALGO_KEY
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"{OPENALGO_URL}/{endpoint}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def get_live_positions() -> dict:
    """Return live positions + LTPs + P&L from OpenAlgo. Fast (<3s)."""
    ist_now = datetime.now(IST)
    result  = {
        "time":      ist_now.strftime("%H:%M:%S IST"),
        "positions": [],
        "total_pnl": 0,
        "nifty":     None,
        "monitor":   None,
        "errors":    [],
    }

    # ── 1. Positionbook ───────────────────────────────────────────────────────
    pb = _oa_post("positionbook", {})
    open_pos = []
    if pb.get("status") == "success":
        for p in pb.get("data", []):
            if p.get("quantity", 0) != 0:
                open_pos.append(p)
    else:
        result["errors"].append("positionbook unavailable")

    if not open_pos:
        result["positions"] = []
        result["total_pnl"] = 0
    else:
        # ── 2. Option chain for live LTPs ─────────────────────────────────────
        # Determine expiry from first position symbol e.g. NIFTY02MAR2625400CE
        sym0 = open_pos[0].get("symbol", "")
        expiry = ""
        if sym0.startswith("NIFTY"):
            expiry = sym0[5:12]   # e.g. "02MAR26"

        chain_map = {}
        if expiry:
            oc = _oa_post("optionchain",
                          {"underlying": "NIFTY", "exchange": "NFO",
                           "expiry_date": expiry}, timeout=8)
            if oc.get("status") == "success":
                result["nifty"] = oc.get("underlying_ltp")
                for item in oc.get("chain", []):
                    try:
                        s = int(item.get("strike", 0))
                        chain_map[s] = {
                            "CE": float(item.get("ce", {}).get("ltp", 0) or 0),
                            "PE": float(item.get("pe", {}).get("ltp", 0) or 0),
                        }
                    except Exception:
                        pass
            else:
                result["errors"].append("optionchain unavailable")

        # ── 3. Build position rows ─────────────────────────────────────────────
        total_pnl = 0.0
        for p in open_pos:
            sym   = p.get("symbol", "")
            qty   = int(p.get("quantity", 0))
            avg   = float(p.get("average_price", 0) or 0)
            side  = "LONG" if qty > 0 else "SHORT"

            # Parse strike + type from symbol e.g. NIFTY02MAR2625400CE
            ltp = 0.0
            try:
                opt_type = sym[-2:]          # "CE" or "PE"
                strike   = int(sym[-7:-2])   # "25400" → 25400
                ltp = chain_map.get(strike, {}).get(opt_type, 0.0)
            except Exception:
                pass

            pnl = (ltp - avg) * qty if avg > 0 else 0.0
            total_pnl += pnl

            result["positions"].append({
                "symbol": sym,
                "side":   side,
                "qty":    qty,
                "avg":    round(avg, 2),
                "ltp":    round(ltp, 2),
                "pnl":    round(pnl, 0),
            })

        result["total_pnl"] = round(total_pnl, 0)

    # ── 4. Monitor heartbeat ──────────────────────────────────────────────────
    hb_path = Path("/Users/mac/openalgo/ic_heartbeat.json")
    if hb_path.exists():
        try:
            hb    = json.loads(hb_path.read_text())
            age_s = time.time() - hb.get("epoch", 0)
            result["monitor"] = {
                "status":  "alive" if age_s < 120 else ("stale" if age_s < 300 else "dead"),
                "age_s":   round(age_s),
                "mtm":     hb.get("mtm"),
                "nifty":   hb.get("nifty"),
                "pid":     hb.get("pid"),
                "closed":  hb.get("closed"),
            }
        except Exception:
            result["monitor"] = {"status": "error"}
    else:
        result["monitor"] = {"status": "not_running"}

    return result


# ─── HTTP HANDLER ─────────────────────────────────────────────────────────────
class RemoteHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass   # suppress default access log (we use our own)

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth_ok(self) -> bool:
        token = self.headers.get("X-Remote-Token", "")
        return token == REMOTE_TOKEN

    def do_GET(self):
        if self.path == "/health":
            resp = {
                "status": "ok",
                "port":    PORT,
                "time":    datetime.now(IST).strftime("%H:%M IST"),
                "skills":  list(SKILL_MAP.keys()),
            }
            # 2.3: Check ic_monitor heartbeat file for liveness
            hb_path = Path("/Users/mac/openalgo/ic_heartbeat.json")
            if hb_path.exists():
                try:
                    hb = json.loads(hb_path.read_text())
                    age_s = time.time() - hb.get("epoch", 0)
                    if age_s < 120:
                        monitor_status = "alive"
                    elif age_s < 300:
                        monitor_status = "stale"
                    else:
                        monitor_status = "dead"
                    resp["monitor"] = {
                        "status":    monitor_status,
                        "age_s":     round(age_s),
                        "pid":       hb.get("pid"),
                        "mtm":       hb.get("mtm"),
                        "nifty":     hb.get("nifty"),
                        "closed":    hb.get("closed"),
                        "iteration": hb.get("iteration"),
                    }
                except Exception:
                    resp["monitor"] = {"status": "error", "detail": "heartbeat parse failed"}
            else:
                resp["monitor"] = {"status": "not_running"}
            self._send_json(200, resp)
            return

        if self.path == "/positions":
            data = get_live_positions()
            self._send_json(200, data)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in SKILL_MAP:
            self._send_json(404, {"error": f"Unknown skill path: {self.path}"})
            return

        if not self._auth_ok():
            log(f"AUTH FAIL from {self.client_address[0]} for {self.path}")
            self._send_json(401, {"error": "Invalid or missing X-Remote-Token header"})
            return

        log(f"REQUEST {self.path} from {self.client_address[0]}")

        # Run skill in background thread so we can stream response
        result = run_skill(self.path)

        code = 200 if result["status"] in ("ok", "busy") else 500
        self._send_json(code, result)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log(f"Claude Remote Control starting on {HOST}:{PORT}")
    log(f"Auth token: {REMOTE_TOKEN}")
    log(f"Skills: {list(SKILL_MAP.keys())}")
    log(f"Health check: http://{HOST}:{PORT}/health")
    log("-" * 60)

    server = http.server.ThreadingHTTPServer((HOST, PORT), RemoteHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped.")
        server.shutdown()
