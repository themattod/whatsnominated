#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path

TABLE_ORDER = [
    'admin_users',
    'admin_sessions',
    'admin_password_resets',
    'admin_watch_links',
    'admin_watch_labels',
    'admin_posters',
    'admin_banners',
    'admin_event_modes',
    'admin_voting_locks',
    'admin_audit_logs',
]


def main():
    parser = argparse.ArgumentParser(description='Restore admin-related table state from JSON export.')
    parser.add_argument('--db', default='data/oscars.db')
    parser.add_argument('--infile', required=True)
    args = parser.parse_args()

    db_path = Path(args.db)
    in_path = Path(args.infile)
    payload = json.loads(in_path.read_text(encoding='utf-8'))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = OFF')

    for table in TABLE_ORDER:
        table_data = payload.get('tables', {}).get(table, {})
        rows = table_data.get('rows', [])
        if not rows:
            cur.execute(f'DELETE FROM {table}')
            continue

        cols = table_data.get('columns') or list(rows[0].keys())
        placeholders = ','.join('?' for _ in cols)
        col_sql = ','.join(cols)

        cur.execute(f'DELETE FROM {table}')
        cur.executemany(
            f'INSERT INTO {table} ({col_sql}) VALUES ({placeholders})',
            [tuple(row.get(c) for c in cols) for row in rows],
        )

    cur.execute('PRAGMA foreign_keys = ON')
    conn.commit()
    conn.close()
    print(f'Restored admin state from {in_path}')


if __name__ == '__main__':
    main()
