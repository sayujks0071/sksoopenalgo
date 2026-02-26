# OpenClaw macOS App — Setup and Troubleshooting

This guide helps you configure the OpenClaw macOS app, connect to your gateway, and use agent keys and deep links. Use it together with the [skills reference](openclaw-skills-reference.md) to get the most out of your agent.

## Prerequisites

- OpenClaw macOS app installed (e.g. from the `.dmg`).
- A running OpenClaw gateway (see [Gateway](#gateway) below).
- Your agent key (issued by your gateway or OpenClaw Cloud; do not commit this to git).

## Gateway

The app talks to an OpenClaw **gateway**. Default port is **18789**.

- **Local**: If you run the gateway on this Mac, use `http://127.0.0.1:18789` (or `http://localhost:18789`).
- **Remote**: If you deploy to a server (e.g. with [deploy_openclaw.sh](../deploy_openclaw.sh)), use `http://YOUR_SERVER_IP:18789`. Ensure port 18789 is open in the server firewall.

Start the gateway (location depends on your install):

- From the OpenClaw app: use the in-app option to start the gateway if available.
- From terminal/CLI: run the gateway process as documented in [OpenClaw docs](https://docs.openclaw.ai/).

If the app shows **"cannot connect gateway 18789"** or **connection refused**:

1. Confirm the gateway process is running and listening on 18789.
2. In the app, check Settings/Preferences and set the gateway URL to match (e.g. `http://127.0.0.1:18789` or `http://YOUR_SERVER_IP:18789`).
3. Restart the app after changing the URL.

If you see **404** when opening a link or sending a message:

1. The gateway may be up but the path or agent key might be wrong. Ensure the gateway URL has no trailing path (e.g. `http://127.0.0.1:18789` not `http://127.0.0.1:18789/agent`).
2. In the app, confirm the agent key is set correctly (see [Agent key](#agent-key) below).

If you see **405 Method Not Allowed** when using the gateway HTTP API (e.g. `OPENCLAW_USE_GATEWAY=1` with the send-message script):

- The Chat Completions endpoint is **disabled by default**. Enable it so you can send messages via the gateway and capture the response in `log/openclaw_response.txt`:
  1. **CLI (recommended):** Run `openclaw config set gateway.http.endpoints.chatCompletions.enabled true`. Restart the gateway if it does not hot-reload.
  2. **Or edit config:** Open `~/.openclaw/openclaw.json` and add under `gateway`: `"http": { "endpoints": { "chatCompletions": { "enabled": true } } }`. Save and restart the gateway.
- See [OpenClaw gateway API](https://docs.openclaw.ai/gateway/openai-http-api). Until the endpoint is enabled, use the deep-link mode (no `OPENCLAW_USE_GATEWAY`) to send messages; you will see the response only in the app.

If you see **401 Unauthorized** when using `OPENCLAW_USE_GATEWAY=1`:

- The Chat Completions endpoint uses **gateway** auth, not the deep-link agent key alone. In `~/.openclaw/openclaw.json`, check `gateway.auth.mode`: if `"token"`, the Bearer token must match `gateway.auth.token` (or set `OPENCLAW_GATEWAY_TOKEN` in `.env.openclaw`); if `"password"`, use `gateway.auth.password` (or set `OPENCLAW_GATEWAY_PASSWORD`). The send-message script uses, in order: `OPENCLAW_GATEWAY_TOKEN`, then `OPENCLAW_GATEWAY_PASSWORD`, then `OPENCLAW_AGENT_KEY`. Ensure one of these in `.env.openclaw` matches your gateway auth.

If you see **"device token mismatch"** or **gateway closed (1008): unauthorized: device token mismatch** (in logs, `openclaw gateway status`, in the app, or when using the HTTP API):

- The gateway auth token is stored in **two** places; when they differ, the gateway rejects requests. Common after an OpenClaw update or config change (see [openclaw/openclaw#18590](https://github.com/openclaw/openclaw/issues/18590)).
  1. **Config:** `~/.openclaw/openclaw.json` → `gateway.auth.token` (and if `gateway.auth.mode` is `"password"`, also `gateway.auth.password` must match for HTTP Bearer auth)
  2. **Launchd (macOS):** `~/Library/LaunchAgents/ai.openclaw.gateway.plist` (or `com.openclaw.gateway.plist`) → `OPENCLAW_GATEWAY_TOKEN` environment variable
- **Fix:** Make all values the same (one token used everywhere):
  1. Run `./scripts/openclaw_check_gateway_token_sync.sh` to see if config and plist match (no secrets printed).
  2. If they don’t match: open the plist, set `OPENCLAW_GATEWAY_TOKEN` to the value of `gateway.auth.token` from `openclaw.json`, save, then run:
     ```bash
     launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
     launchctl load ~/Library/LaunchAgents/ai.openclaw.gateway.plist
     ```
  3. If your gateway uses **password** mode (`openclaw config get gateway.auth` shows `"mode": "password"`), set the same value as password so HTTP Bearer auth works: `openclaw config set gateway.auth.password 'YOUR_TOKEN'`.
  4. Put the **same** token in `.env.openclaw` as `OPENCLAW_GATEWAY_TOKEN=` so the send-message script can use it.
  5. Restart the gateway (unload/load plist above); then retry. In the OpenClaw app, ensure the agent key matches this token if the app uses it to talk to the gateway.
- **After any OpenClaw update:** run `./scripts/openclaw_check_gateway_token_sync.sh`; if it reports mismatch, re-sync as above.
- References: [OpenClaw gateway troubleshooting](https://docs.openclaw.ai/gateway/troubleshooting), [Quick fix (Travis Media)](https://travis.media/blog/openclaw-device-token-mismatch/).

## Agent key

Your agent is identified by a **key** (long alphanumeric string). Configure it in the OpenClaw macOS app:

1. Open the app’s Settings or Preferences.
2. Find the field for **Agent key** / **API key** / **Gateway token** (wording may vary).
3. Paste your key there. Do not commit this key to version control or share it in docs.

If you use a gateway deployed with [deploy_openclaw.sh](../deploy_openclaw.sh), the script prints a **gateway token** on first run; that token is used for gateway auth. The **agent key** you use in the app may be the same token or a separate key depending on your OpenClaw version and deployment.

## Deep links

The app supports a custom URL scheme for opening a session with a pre-filled message and agent key:

```text
openclaw://agent?message=<url-encoded-message>&key=<agent-key>
```

Example (use your own key):

- Message: "Hello from deep link"
- URL: `openclaw://agent?message=Hello%20from%20deep%20link&key=YOUR_AGENT_KEY`

Use this from other apps (e.g. browsers, launchers) to open OpenClaw and send that message to the agent. Replace `YOUR_AGENT_KEY` with your actual key and keep the key out of shared or committed files.

## Making the agent “best” for you

- **Skills**: See [OpenClaw skills reference](openclaw-skills-reference.md) for built-in capabilities (exec, browser, memory, web, subagents, etc.).
- **Memory and search**: Use [semantic memory with memsearch](openclaw-semantic-memory-memsearch.md) for meaning-based search over markdown memory.
- **Workflows**: Add [daily Reddit digest](openclaw-daily-reddit-digest.md) or [dynamic dashboard with sub-agents](openclaw-dynamic-dashboard-subagents.md) as needed.
- **Stability**: Keep the gateway running and the app’s gateway URL and agent key correct; reinstall from the `.dmg` if the app is misbehaving after an update.

## Security

- Do not commit agent keys, gateway tokens, or API keys to the repo. Use app settings or environment variables.
- Use `.env` or gitignored config for any scripts that need keys (e.g. deploy scripts); the deploy script already uses `KIMI_API_KEY` from the environment.

## Controlling OpenClaw from terminal / Cursor

You can trigger the app or send messages from the terminal (e.g. from Cursor):

1. **Open app with a message (deep link)**  
   ```bash
   OPENCLAW_AGENT_KEY=your_key ./scripts/openclaw_send_message.sh "Your message"
   ```
   Or without a key (message only):  
   `open "openclaw://agent?message=Hello%20world"`  
   The agent’s reply appears only in the OpenClaw app.

2. **Send via gateway and see the response**  
   If the gateway is running and the Chat Completions HTTP endpoint is enabled:
   ```bash
   OPENCLAW_USE_GATEWAY=1 ./scripts/openclaw_send_message.sh "Your message"
   ```
   The script prints the agent’s reply to the terminal and saves it so you can “see the response” from Cursor or scripts:
   - **Plain text reply**: `log/openclaw_response.txt` (or `OPENCLAW_RESPONSE_DIR` if set)
   - **Raw API JSON**: `log/openclaw_response.json`  
   The gateway must have `gateway.http.endpoints.chatCompletions.enabled: true` in config.

See [OpenClaw gateway API](https://docs.openclaw.ai/gateway/openai-http-api) for auth and options.

## Related

- [OpenClaw documentation](https://docs.openclaw.ai/)
- [OpenClaw skills reference](openclaw-skills-reference.md)
- [Deploy OpenClaw gateway](../deploy_openclaw.sh) (VPS, port 18789)
