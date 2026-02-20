#!/usr/bin/env python3
import argparse
import json
import shutil
import sqlite3
from pathlib import Path

TABLES = [
    'admin_watch_links',
    'admin_watch_labels',
    'admin_posters',
    'scraped_posters',
    'admin_banners',
    'admin_event_modes',
    'admin_voting_locks',
    'category_winners',
]


def _table_columns(cur, table):
    rows = cur.execute(f'PRAGMA table_info({table})').fetchall()
    return [r[1] for r in rows]


def _copy_tree(src: Path, dst: Path):
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main():
    parser = argparse.ArgumentParser(
        description='Export deployable seed assets (watch links, labels, poster refs, winners, etc.).'
    )
    parser.add_argument('--db', default='data/oscars.db')
    parser.add_argument('--out', default='seed_data/deploy_seed_assets.json')
    parser.add_argument('--poster-src', default='data/poster_cache')
    parser.add_argument('--poster-out', default='seed_data/poster_cache')
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)
    poster_src = Path(args.poster_src)
    poster_out = Path(args.poster_out)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    years = sorted(
        r['year'] for r in cur.execute('SELECT DISTINCT year FROM film_years ORDER BY year').fetchall()
    )

    payload = {
        'meta': {
            'source_db': str(db_path),
            'years': years,
            'tables': TABLES,
        },
        'tables': {},
    }

    for table in TABLES:
        cols = _table_columns(cur, table)
        rows = [dict(r) for r in cur.execute(f'SELECT * FROM {table}').fetchall()]
        payload['tables'][table] = {
            'columns': cols,
            'rows': rows,
            'count': len(rows),
        }

    conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    _copy_tree(poster_src, poster_out)

    print(f'Exported seed asset JSON: {out_path}')
    print(f'Copied poster cache: {poster_src} -> {poster_out}')


if __name__ == '__main__':
    main()
