# OpenAlgo skill for OpenClaw

Add OpenAlgo as a skill so your OpenClaw agent can place orders, fetch quotes, positions, funds, and search symbols via the OpenAlgo REST API.

## What it does

The skill teaches the agent to call OpenAlgo’s API using **exec** (curl). The agent can:

- Get quotes, positions, order book, trade book, funds, holdings
- Search symbols and fetch option chain / history
- Place or cancel orders (with user confirmation when appropriate)

## Install

1. **Run the install script** (from repo root):

   ```bash
   chmod +x scripts/install_openalgo_skill_in_openclaw.sh
   ./scripts/install_openalgo_skill_in_openclaw.sh
   ```

   This copies `openalgo-openclaw-skill/` to `~/.openclaw/workspace/skills/openalgo`.

2. **Set environment variables** for the OpenClaw gateway process:

   - `OPENALGO_API_KEY` – Your OpenAlgo API key. OpenAlgo requires web UI login: open the app in a browser (e.g. http://127.0.0.1:5002), log in, then get the key from the API Key page.
   - `OPENALGO_BASE_URL` – Optional; default `http://127.0.0.1:5000`.

3. **Refresh skills**: Ask OpenClaw to “refresh skills” or restart the gateway.

## Manual install

See [openalgo-openclaw-skill/README.md](../openalgo-openclaw-skill/README.md) for copy/symlink steps and where OpenClaw looks for skills.

## Related

- [OpenClaw macOS app setup](openclaw-macos-app-setup.md)
- [OpenClaw skills reference](openclaw-skills-reference.md)
- [OpenAlgo API](https://docs.openalgo.in) · [OpenAlgo GitHub](https://github.com/marketcalls/openalgo)
