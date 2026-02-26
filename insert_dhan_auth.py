#!/usr/bin/env python3
"""
Insert Dhan authentication token from .env into the auth table.
This is needed because the auth table is empty, causing MCX quote requests to fail.
"""
import os
import sys

# Add openalgo directory to path
sys.path.insert(0, '/Users/mac/openalgo/openalgo')

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv('/Users/mac/openalgo/openalgo/.env')

# Now import the auth_db module
from database.auth_db import upsert_auth, init_db

# Get Dhan credentials from environment
dhan_client_id = os.getenv('DHAN_CLIENT_ID')
dhan_access_token = os.getenv('DHAN_ACCESS_TOKEN')

print(f"DHAN_CLIENT_ID: {dhan_client_id}")
print(f"DHAN_ACCESS_TOKEN length: {len(dhan_access_token) if dhan_access_token else 0}")

if not dhan_client_id or not dhan_access_token:
    print("ERROR: DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN not found in environment")
    sys.exit(1)

# Initialize database
init_db()

# Insert the auth token
print(f"\nInserting auth token for user: {dhan_client_id}")
upsert_auth(
    name=dhan_client_id,
    auth_token=dhan_access_token,
    broker='dhan',
    feed_token=None,
    user_id=dhan_client_id,
    revoke=False
)

print("Auth token inserted successfully!")

# Verify the insertion
from database.auth_db import get_auth_token_broker
token, broker = get_auth_token_broker(dhan_client_id)
print(f"\nVerification - Token retrieved: {token[:50] if token else 'None'}...")
print(f"Verification - Broker: {broker}")
