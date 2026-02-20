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


def _copy_tree(src: Path, dst: Path):
    if not src.exists():
        return False
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.rglob('*'):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return True


def _load_payload(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(
        description='Import deployable seed assets (watch links, labels, poster refs, winners, etc.).'
    )
    parser.add_argument('--db', default='data/oscars.db')
    parser.add_argument('--infile', default='seed_data/deploy_seed_assets.json')
    parser.add_argument('--poster-src', default='seed_data/poster_cache')
    parser.add_argument('--poster-out', default='data/poster_cache')
    args = parser.parse_args()

    db_path = Path(args.db)
    in_path = Path(args.infile)
    poster_src = Path(args.poster_src)
    poster_out = Path(args.poster_out)

    payload = _load_payload(in_path)
    years = payload.get('meta', {}).get('years') or []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = ON')

    for table in TABLES:
        table_data = payload.get('tables', {}).get(table, {})
        rows = table_data.get('rows', [])
        cols = table_data.get('columns') or (list(rows[0].keys()) if rows else [])

        if years:
            placeholders = ','.join('?' for _ in years)
            cur.execute(f'DELETE FROM {table} WHERE year IN ({placeholders})', tuple(years))
        else:
            cur.execute(f'DELETE FROM {table}')

        if rows and cols:
            col_sql = ','.join(cols)
            val_sql = ','.join('?' for _ in cols)
            cur.executemany(
                f'INSERT INTO {table} ({col_sql}) VALUES ({val_sql})',
                [tuple(row.get(c) for c in cols) for row in rows],
            )

    conn.commit()
    conn.close()

    copied = _copy_tree(poster_src, poster_out)
    print(f'Imported seed asset JSON: {in_path}')
    if copied:
        print(f'Copied poster cache: {poster_src} -> {poster_out}')
    else:
        print(f'Poster cache source not found: {poster_src}')


if __name__ == '__main__':
    main()
