#!/usr/bin/env python3
"""
AO Webhook Receiver — port 8000
================================
Receives agent-orchestrator events (agent-finished, all-agents-finished, agent-failed)
and bridges them to the n8n Cloud IC alert workflow.

Usage:
  python3 /Users/mac/openalgo/webhook_receiver.py

Runs on: http://127.0.0.1:8000
Logs to: /Users/mac/openalgo/webhook_receiver.log
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytz
import requests
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Request, Response

# ── Config ────────────────────────────────────────────────────────────────────
IST            = pytz.timezone("Asia/Kolkata")
N8N_WEBHOOK    = "https://sayujks20417.app.n8n.cloud/webhook/ic-trading-alert"
AGENT_LOG_PATH = Path("/Users/mac/.openclaw/workspace/memory/trading/agent_log.jsonl")
LOG_FILE       = "/Users/mac/openalgo/webhook_receiver.log"
AO_SECRET      = "ao-trading-secret-2026"   # must match agent-orchestrator.yaml

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
log = logging.getLogger("ao-webhook")

app = FastAPI(title="AO Webhook Receiver", version="1.0.0")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_latest_agent_log() -> dict:
    """Read the most recent entry from agent_log.jsonl."""
    if not AGENT_LOG_PATH.exists():
        return {}
    lines = AGENT_LOG_PATH.read_text().strip().splitlines()
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}


def _post_to_n8n(event_type: str, payload: dict):
    """Forward event + latest agent_log entry to n8n IC alert webhook."""
    try:
        latest_log = _read_latest_agent_log()
        body = {
            "type": event_type,
            "timestamp": datetime.now(IST).isoformat(),
            "payload": payload,
            "latest_agent_log": latest_log,
        }
        r = requests.post(N8N_WEBHOOK, json=body, timeout=10)
        log.info(f"n8n notified: {event_type} → HTTP {r.status_code}")
    except Exception as e:
        log.error(f"n8n notify failed: {e}")


def _ao_send(session_id: str, message: str):
    """Send a message to a running ao session."""
    try:
        result = subprocess.run(
            ["ao", "send", session_id, message],
            capture_output=True, text=True, timeout=15
        )
        log.info(f"ao send → {session_id}: {result.stdout.strip()}")
    except Exception as e:
        log.error(f"ao send failed: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "ao-webhook-receiver", "time": datetime.now(IST).isoformat()}


@app.post("/webhook/ao-event")
async def handle_ao_event(request: Request, background_tasks: BackgroundTasks):
    """Main webhook endpoint — receives all agent-orchestrator events."""
    try:
        payload = await request.json()
    except Exception:
        return Response(content="invalid json", status_code=400)

    event   = payload.get("event", "unknown")
    session = payload.get("session", {})
    sid     = session.get("id", "")

    log.info(f"Event received: {event} | session={sid}")

    # ── Route events ──────────────────────────────────────────────────────────

    if event == "all-agents-finished":
        # All 3 overnight agents done → notify n8n (triggers Gmail summary)
        background_tasks.add_task(_post_to_n8n, "overnight_optimization_done", payload)
        log.info("All agents finished — n8n notification queued")

    elif event == "agent-finished":
        agent_name = session.get("name", "unknown")
        log.info(f"Agent '{agent_name}' finished")
        # Agent already wrote findings to agent_log.jsonl — nothing else to do

    elif event == "agent-failed":
        agent_name = session.get("name", "unknown")
        error_msg  = payload.get("error", "unknown error")
        log.error(f"Agent '{agent_name}' FAILED: {error_msg}")
        # Notify n8n of failure
        background_tasks.add_task(_post_to_n8n, "overnight_agent_failed", {
            "agent": agent_name, "error": error_msg
        })

    elif event == "ci-failed":
        # CI failure → send message back to agent to fix
        branch = session.get("branch", "")
        log.info(f"CI failed on branch '{branch}' — sending fix instruction")
        if sid:
            background_tasks.add_task(
                _ao_send, sid,
                "CI tests failed. Read the error output, fix the issue, and push a new commit."
            )

    else:
        log.info(f"Unhandled event type: {event}")

    return {"ok": True, "event": event, "session": sid}


@app.get("/agent-log/latest")
def get_latest_agent_log():
    """Return the latest entry from agent_log.jsonl (useful for debugging)."""
    entry = _read_latest_agent_log()
    return {"entry": entry, "path": str(AGENT_LOG_PATH)}


@app.get("/agent-log/all")
def get_all_agent_logs(limit: int = 10):
    """Return last N entries from agent_log.jsonl."""
    if not AGENT_LOG_PATH.exists():
        return {"entries": [], "count": 0}
    lines = AGENT_LOG_PATH.read_text().strip().splitlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return {"entries": entries, "count": len(entries)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting AO Webhook Receiver on http://127.0.0.1:8000")
    log.info(f"Logging to: {LOG_FILE}")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
