#!/usr/bin/env python3
"""
Claude Remote Control — ic_monitor skill trigger server
Port 18790 | Loopback only | Token auth

Lets you trigger any IC trading skill via HTTP POST from:
  - n8n cloud webhook relay
  - SSH from phone: ssh mac 'curl -s -X POST -H "X-Remote-Token: TOKEN" http://localhost:18790/wave1'
  - Tailscale (when enabled)

Endpoints:
  POST /wave1       → Run ic-wave1 skill  (Iron Condor Wave 1 entry)
  POST /wave2       → Run ic-wave2 skill  (Add lots at 11:30 AM)
  POST /wave3       → Run ic-wave3 skill  (Add lots at 2:00 PM)
  POST /close       → Run ic-close skill  (Close all positions)
  POST /emergency   → Run ic-emergency skill (Emergency exit now)
  POST /status      → Run ic-status skill (Session status)
  GET  /health      → Health check (no auth required)

Usage:
  python3 /Users/mac/openalgo/claude_remote.py
"""

import http.server
import json
import os
import subprocess
import threading
import time
from datetime import datetime
import pytz

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PORT          = 18790
HOST          = "127.0.0.1"   # loopback only — never expose to internet directly
REMOTE_TOKEN  = os.environ.get("CLAUDE_REMOTE_TOKEN", "ic-remote-2026")
CLAUDE_BIN    = "/Users/mac/.local/bin/claude"
LOG_FILE      = "/Users/mac/openalgo/claude_remote.log"
IST           = pytz.timezone("Asia/Kolkata")

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
            self._send_json(200, {
                "status": "ok",
                "port":    PORT,
                "time":    datetime.now(IST).strftime("%H:%M IST"),
                "skills":  list(SKILL_MAP.keys()),
            })
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
