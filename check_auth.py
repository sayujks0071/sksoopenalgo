#!/usr/bin/env python3
import sqlite3

# Check openalgo database in openalgo/openalgo/db/
conn = sqlite3.connect('openalgo/db/openalgo.db')
cursor = conn.cursor()

# Check auth table
print('=== Checking auth table in openalgo/db/openalgo.db ===')
try:
    cursor.execute('PRAGMA table_info(auth)')
    cols = cursor.fetchall()
    print('Columns:')
    for col in cols:
        print(f'  {col[1]} ({col[2]})')
    
    cursor.execute('SELECT * FROM auth')
    rows = cursor.fetchall()
    print(f'\nTotal Rows: {len(rows)}')
    
    if rows:
        col_names = [c[1] for c in cols]
        for row_idx, row in enumerate(rows):
            print(f'\n--- Row {row_idx + 1} ---')
            for i, name in enumerate(col_names):
                val = row[i] if i < len(row) else None
                if name in ['access_token', 'api_key', 'api_secret', 'password', 'totp_secret', 'token', 'auth', 'feed_token']:
                    if val:
                        print(f'  {name}: [HIDDEN - length: {len(str(val)) if val else 0}]')
                    else:
                        print(f'  {name}: None')
                else:
                    print(f'  {name}: {val}')
except Exception as e:
    print(f'Error: {e}')

conn.close()

# Also check the other database
print('\n\n=== Checking db/openalgo.db ===')
conn2 = sqlite3.connect('db/openalgo.db')
cursor2 = conn2.cursor()

try:
    cursor2.execute('SELECT COUNT(*) FROM auth')
    count = cursor2.fetchone()
    print(f'Auth rows in db/openalgo.db: {count[0]}')
except Exception as e:
    print(f'Error: {e}')

conn2.close()
