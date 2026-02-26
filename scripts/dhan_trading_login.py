#!/usr/bin/env python3
"""
Dhan trading login check and optional sync from env for OpenAlgo.

- Validates existing Dhan auth in OpenAlgo DB (via Dhan funds API).
- If missing or invalid and DHAN_ACCESS_TOKEN is set in .env, upserts and re-validates.
- Intended for cron: run before market open so strategies have valid auth.

Usage:
  From repo root: python3 scripts/dhan_trading_login.py
  Or: ./scripts/dhan_trading_login.py

Env (from project .env or openalgo/.env):
  OPENALGO_USER   - OpenAlgo username whose auth to check (default: DHAN_CLIENT_ID)
  DHAN_CLIENT_ID   - Dhan client ID (required for validation)
  DHAN_ACCESS_TOKEN - Optional; if set and DB token invalid, script upserts this token
  DATABASE_URL, API_KEY_PEPPER - Required for DB access (from OpenAlgo .env)
"""
import os
import sys

# Project root = parent of scripts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OPENALGO_DIR = os.path.join(PROJECT_ROOT, "openalgo")

# Load .env from project root then openalgo (so openalgo/.env overrides)
for env_file in [os.path.join(PROJECT_ROOT, ".env"), os.path.join(OPENALGO_DIR, ".env")]:
    if os.path.isfile(env_file):
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
            break
        except ImportError:
            pass

sys.path.insert(0, OPENALGO_DIR)
os.chdir(PROJECT_ROOT)

# After path is set
from database.auth_db import get_auth_token, init_db, upsert_auth
from broker.dhan.api.funds import test_auth_token


def main():
    init_db()

    # Auth row is keyed by OpenAlgo username (for API trading) or Dhan client ID
    auth_name = os.getenv("OPENALGO_USER") or os.getenv("DHAN_CLIENT_ID")
    if not auth_name:
        print("ERROR: Set OPENALGO_USER or DHAN_CLIENT_ID in .env", file=sys.stderr)
        return 1

    dhan_token_from_env = (os.getenv("DHAN_ACCESS_TOKEN") or "").strip()
    token = get_auth_token(auth_name)

    # Validate current token
    if token:
        valid, err = test_auth_token(token)
        if valid:
            print("OK: Dhan auth valid")
            return 0
        # Invalid or expired
        if dhan_token_from_env:
            valid_env, _ = test_auth_token(dhan_token_from_env)
            if valid_env:
                upsert_auth(
                    name=auth_name,
                    auth_token=dhan_token_from_env,
                    broker="dhan",
                    feed_token=None,
                    user_id=auth_name,
                    revoke=False,
                )
                print("OK: Updated Dhan auth from DHAN_ACCESS_TOKEN and validated")
                return 0
            print("WARN: DHAN_ACCESS_TOKEN in .env is also invalid", file=sys.stderr)
        print("WARN: Dhan auth invalid or expired; update DHAN_ACCESS_TOKEN in .env and re-run", file=sys.stderr)
        return 1

    # No token in DB
    if dhan_token_from_env:
        valid_env, _ = test_auth_token(dhan_token_from_env)
        if valid_env:
            upsert_auth(
                name=auth_name,
                auth_token=dhan_token_from_env,
                broker="dhan",
                feed_token=None,
                user_id=auth_name,
                revoke=False,
            )
            print("OK: Inserted Dhan auth from DHAN_ACCESS_TOKEN and validated")
            return 0
        print("WARN: DHAN_ACCESS_TOKEN in .env is invalid", file=sys.stderr)
    print("ERROR: No Dhan auth in DB; set DHAN_ACCESS_TOKEN in .env and re-run", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
