# OpenClaw cron: automate OpenAlgo Dhan login at 8 AM (trading days)

This sets up a **recurring OpenClaw cron job** that, at 8 AM IST on every trading day (Mon–Fri), sends a message to your agent. The agent uses **exec** to run the OpenAlgo Dhan trading login script we already created.

## Prerequisites

- OpenClaw gateway running and `openclaw` CLI configured (auth, gateway URL).
- OpenAlgo repo at `/Users/mac/openalgo` with `scripts/cron_dhan_trading_login.sh` and `scripts/dhan_trading_login.py` in place.

## One-time setup (run on your Mac)

From a terminal where `openclaw` is on PATH and points at your gateway, run:

```bash
openclaw cron add \
  --name "OpenAlgo Dhan login" \
  --cron "0 8 * * 1-5" \
  --tz "Asia/Kolkata" \
  --session isolated \
  --message "Run the OpenAlgo Dhan trading login script. Execute this command: cd /Users/mac/openalgo && ./scripts/cron_dhan_trading_login.sh" \
  --no-deliver
```

- **Schedule**: `0 8 * * 1-5` = 8:00 AM, Mon–Fri.
- **Timezone**: `Asia/Kolkata` (IST) so 8 AM is Indian market time.
- **Isolated session**: Agent runs in a dedicated turn and executes the command via **exec**.
- **--no-deliver**: No announcement to a channel (run is internal). Omit or use `--announce --channel ...` if you want a summary delivered.

If your OpenAlgo repo is elsewhere, change the path in `--message` (e.g. `cd /path/to/openalgo && ./scripts/cron_dhan_trading_login.sh`).

## Verify

```bash
openclaw cron list
openclaw cron run <job-id>   # optional: trigger once to test
```

## How it works

1. At 8 AM IST on Mon–Fri, the OpenClaw gateway fires the job.
2. It starts an **isolated** agent turn with the message above.
3. The agent uses **exec** to run `cd /Users/mac/openalgo && ./scripts/cron_dhan_trading_login.sh`.
4. That script runs `dhan_trading_login.py` (validates/syncs Dhan auth) and appends to `log/cron_dhan_login.log`.

No host cron is required; scheduling lives entirely in OpenClaw.

## Edit or remove

```bash
openclaw cron edit <job-id>   # e.g. change --message or --cron
openclaw cron remove <job-id>
```

## Related

- [Dhan cron login (host cron)](dhan-cron-login.md) – alternative: run the same script via system crontab.
- [OpenClaw cron jobs](https://docs.openclaw.ai/cron-jobs) – schedule types, delivery, CLI.
