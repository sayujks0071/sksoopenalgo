# OpenAlgo skill for OpenClaw

This skill lets your OpenClaw agent trade and query market data via the OpenAlgo REST API (place orders, quotes, positions, funds, search symbols, etc.).

## Install into OpenClaw

1. **Copy the skill into OpenClaw’s workspace** (pick one):

   ```bash
   # From this repo root
   SKILL_SRC="$(pwd)/openalgo-openclaw-skill"
   OPENCLAW_SKILLS="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}/skills"
   mkdir -p "$OPENCLAW_SKILLS"
   cp -R "$SKILL_SRC" "$OPENCLAW_SKILLS/openalgo"
   ```

   Or symlink (so updates in repo are picked up):

   ```bash
   OPENCLAW_SKILLS="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}/skills"
   mkdir -p "$OPENCLAW_SKILLS"
   ln -sf "$(pwd)/openalgo-openclaw-skill" "$OPENCLAW_SKILLS/openalgo"
   ```

2. **Set environment variables** for the OpenClaw gateway (or the shell where the agent runs exec):

   - `OPENALGO_API_KEY` – Your OpenAlgo API key (from OpenAlgo UI → API Key).
   - `OPENALGO_BASE_URL` – Optional. Default `http://127.0.0.1:5000`. Use your OpenAlgo URL if different (e.g. ngrok or production).

   Where to set them depends on your OpenClaw setup (e.g. gateway config, systemd, launchd, or shell profile).

3. **Refresh skills** in OpenClaw: ask the agent to “refresh skills” or restart the OpenClaw gateway.

## Usage

Once installed and env is set, you can ask OpenClaw things like:

- “Get my OpenAlgo positions.”
- “What’s the quote for NSE RELIANCE?”
- “Search OpenAlgo for NIFTY option symbols.”
- “Place a market buy order for 1 share of SBIN on NSE using OpenAlgo.” (confirm before placing)

The agent will use **exec** to call the OpenAlgo API and return the result.

## Getting your API key (web UI login required)

OpenAlgo API keys are created from the web UI. You must log in first:

1. Open OpenAlgo in your browser (e.g. `http://127.0.0.1:5002` or `http://127.0.0.1:5000`).
2. Log in with your OpenAlgo username and password.
3. Go to the **API Key** page (e.g. `/apikey` in the app).
4. Generate or copy your API key and use it as `OPENALGO_API_KEY` (or in the `apikey` field for direct API calls).

The API key is tied to the user account you logged in as. Without logging in via the web UI at least once, you cannot obtain a valid key for the REST API.

## Requirements

- OpenAlgo server running and reachable at `OPENALGO_BASE_URL`.
- Valid OpenAlgo API key (obtained after web UI login) with the right broker connected (e.g. Dhan).

## Links

- [OpenAlgo API docs](https://docs.openalgo.in)  
- [OpenAlgo GitHub](https://github.com/marketcalls/openalgo)  
- [OpenClaw skills](https://docs.openclaw.ai/tools/creating-skills)
