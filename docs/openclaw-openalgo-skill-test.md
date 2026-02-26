# OpenAlgo skill test results

## Run (plan: Test OpenAlgo skill in OpenClaw)

- **Skill install**: Verified. `~/.openclaw/workspace/skills/openalgo` contains `SKILL.md` and `README.md`.
- **OpenAlgo server**: Not running at test time (connection to `http://127.0.0.1:5000` failed). Start OpenAlgo (e.g. `uv run app.py` from openalgo) for the agent to reach the API.
- **Test message sent**: OpenClaw was opened with: “Ping OpenAlgo and tell me the result.” Check the app for the agent’s reply; it will use the OpenAlgo skill (exec + curl). If the agent says to set `OPENALGO_API_KEY` or reports a connection error, set the env for the OpenClaw gateway and ensure OpenAlgo is running, then try again.

## Full test checklist (for you)

1. Start OpenAlgo: from repo, `cd openalgo && uv run app.py` (or your usual run).
2. Set for OpenClaw gateway: `OPENALGO_API_KEY` (and `OPENALGO_BASE_URL` if not 127.0.0.1:5000). Restart the gateway after setting.
3. In OpenClaw, send: “Refresh skills” (or restart gateway).
4. In OpenClaw, send: “Ping OpenAlgo” or “Get my OpenAlgo positions.”
5. Confirm the agent runs curl and returns a clear success or error (and does not echo your API key).
