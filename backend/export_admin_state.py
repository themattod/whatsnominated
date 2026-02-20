#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path

TABLES = [
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


def table_columns(cur, table):
    rows = cur.execute(f'PRAGMA table_info({table})').fetchall()
    return [r[1] for r in rows]


def main():
    parser = argparse.ArgumentParser(description='Export admin-related table state to JSON.')
    parser.add_argument('--db', default='data/oscars.db')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    data = {
        'meta': {
            'db_path': str(db_path),
            'tables': TABLES,
        },
        'tables': {},
    }

    for table in TABLES:
        cols = table_columns(cur, table)
        rows = [dict(r) for r in cur.execute(f'SELECT * FROM {table}').fetchall()]
        data['tables'][table] = {
            'columns': cols,
            'rows': rows,
            'count': len(rows),
        }

    conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f'Exported admin state to {out_path}')


if __name__ == '__main__':
    main()
