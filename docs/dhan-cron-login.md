# Automate Dhan Trading Login (Cron)

Use a cron job to validate and optionally sync Dhan auth for OpenAlgo before market open, so strategies have a valid session.

## What it does

- **Validates** existing Dhan auth in OpenAlgo’s DB (calls Dhan funds API).
- **Optional sync**: If the stored token is missing or invalid and `DHAN_ACCESS_TOKEN` is set in `.env`, the script upserts it and re-validates.
- Designed to run **before market open** (e.g. 8:45 AM IST on weekdays).

Dhan access tokens expire (typically daily). You can either:

1. **Manual refresh**: Log in to Dhan (browser or app), copy the new access token into `.env` as `DHAN_ACCESS_TOKEN`, and let the cron script push it into OpenAlgo.
2. **Web login**: Use OpenAlgo’s Dhan broker login once per day; the cron then only checks that the stored token is still valid.

## Setup

### 1. Environment

In your project `.env` (or `openalgo/.env`):

- `DHAN_CLIENT_ID` – your Dhan client ID (required).
- `OPENALGO_USER` – OpenAlgo username whose auth row to use. If unset, the script uses `DHAN_CLIENT_ID` as the auth name (same as `insert_dhan_auth.py`).
- `DHAN_ACCESS_TOKEN` – optional; if set and DB token is invalid, the script will upsert this token.
- `DATABASE_URL`, `API_KEY_PEPPER` – must be set for OpenAlgo DB access.

### 2. Install the cron job

From the repo root:

```bash
chmod +x scripts/cron_dhan_trading_login.sh
./scripts/install_cron_dhan_login.sh
```

Default schedule: **8:45 AM, Mon–Fri** (local time). To change it:

```bash
DHAN_LOGIN_CRON_SCHEDULE='30 8 * * 1-5' ./scripts/install_cron_dhan_login.sh
```

### 3. Logs

- Default log file: `log/cron_dhan_login.log`.
- Override: `OPENALGO_CRON_LOG=/path/to/log ./scripts/cron_dhan_trading_login.sh`

## Manual run

```bash
cd /path/to/openalgo
python3 scripts/dhan_trading_login.py
```

Exit code: `0` if Dhan auth is valid, `1` otherwise (e.g. token expired and no valid `DHAN_ACCESS_TOKEN` in `.env`).

## Order of cron jobs

If you also use a cron to start strategies (e.g. `start_strategies_cron.sh` at 9:15 AM):

1. Run **Dhan login** first (e.g. 8:45 AM).
2. Run **strategy start** at or after market open (e.g. 9:15 AM).

That way auth is validated (and optionally updated) before strategies start.

## Related

- [insert_dhan_auth.py](../insert_dhan_auth.py) – one-time or manual insert of Dhan token from `.env`.
- [start_strategies_cron.sh](../start_strategies_cron.sh) – cron to start OpenAlgo strategies.
- OpenAlgo broker login: Dhan OAuth flow via `/dhan/initiate-oauth` and callback.
