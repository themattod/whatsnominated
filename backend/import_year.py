import argparse
import hashlib
from pathlib import Path

from db import connect, init_db
from year_data_utils import load_year_payload, validate_year_payload


def _record_import_run(year, source_path, data_hash, schema_version, status, details=''):
    conn = connect()
    conn.execute(
        '''
        INSERT INTO year_import_runs(year, source_path, data_hash, schema_version, status, details)
        VALUES(?, ?, ?, ?, ?, ?)
        ''',
        (year, source_path, data_hash, schema_version, status, details),
    )
    conn.commit()
    conn.close()


def _resolve_canonical_film_id(cur, source_film_id, title, external_id):
    external_id = (external_id or '').strip()
    if external_id:
        row = cur.execute(
            'SELECT id FROM films WHERE external_id = ?',
            (external_id,),
        ).fetchone()
        if row:
            return row['id']

        row = cur.execute(
            'SELECT id FROM films WHERE title = ?',
            (title,),
        ).fetchone()
        if row:
            cur.execute(
                '''
                UPDATE films
                SET external_id = ?
                WHERE id = ? AND (external_id IS NULL OR external_id = '' OR external_id = ?)
                ''',
                (external_id, row['id'], row['id']),
            )
            return row['id']

        return external_id

    return source_film_id


def _import_year(cur, year, payload, prune=False):
    cur.execute(
        '''
        INSERT INTO years(year, label)
        VALUES(?, ?)
        ON CONFLICT(year) DO UPDATE SET
          label=excluded.label
        ''',
        (year, payload['label']),
    )

    categories = payload.get('categories') or []
    films = payload.get('films') or []
    nominations = payload.get('nominations') or []
    default_seen = payload.get('defaultSeenFilmIds') or []

    category_id_by_name = {}
    imported_category_names = set()
    for category in categories:
        name = category['name']
        imported_category_names.add(name)
        cur.execute(
            '''
            INSERT INTO categories(year, name, year_started, year_ended)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(year, name) DO UPDATE SET
              year_started=excluded.year_started,
              year_ended=excluded.year_ended
            ''',
            (year, name, category.get('yearStarted'), category.get('yearEnded')),
        )
        row = cur.execute(
            'SELECT id FROM categories WHERE year = ? AND name = ?',
            (year, name),
        ).fetchone()
        category_id_by_name[name] = row['id']

    source_to_canonical = {}
    imported_film_ids = set()
    for film in films:
        source_film_id = film['id']
        title = film['title']
        external_id = film.get('externalId')
        canonical_film_id = _resolve_canonical_film_id(cur, source_film_id, title, external_id)
        imported_film_ids.add(canonical_film_id)
        source_to_canonical[source_film_id] = canonical_film_id

        cur.execute(
            '''
            INSERT INTO films(id, title, external_id)
            VALUES(?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              external_id=COALESCE(NULLIF(films.external_id, ''), excluded.external_id)
            ''',
            (canonical_film_id, title, (external_id or canonical_film_id)),
        )

        availability = film.get('availability', {})
        cur.execute(
            '''
            INSERT INTO film_years(year, film_id, base_free, base_subscription, base_rent, base_theaters)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, film_id) DO UPDATE SET
              base_free=excluded.base_free,
              base_subscription=excluded.base_subscription,
              base_rent=excluded.base_rent,
              base_theaters=excluded.base_theaters
            ''',
            (
                year,
                canonical_film_id,
                availability.get('free', ''),
                availability.get('subscription', ''),
                availability.get('rent', ''),
                availability.get('theaters', ''),
            ),
        )

    cur.execute('DELETE FROM nominations WHERE year = ?', (year,))
    for nomination in nominations:
        cur.execute(
            'INSERT INTO nominations(year, category_id, film_id, nominee) VALUES(?, ?, ?, ?)',
            (
                year,
                category_id_by_name[nomination['category']],
                source_to_canonical[nomination['filmId']],
                nomination.get('nominee', ''),
            ),
        )

    cur.execute('DELETE FROM default_seen WHERE year = ?', (year,))
    for source_film_id in default_seen:
        cur.execute(
            'INSERT INTO default_seen(year, film_id) VALUES(?, ?)',
            (year, source_to_canonical[source_film_id]),
        )

    if prune:
        if imported_film_ids:
            placeholders = ','.join('?' for _ in imported_film_ids)
            cur.execute(
                f'''
                DELETE FROM film_years
                WHERE year = ?
                  AND film_id NOT IN ({placeholders})
                ''',
                (year, *sorted(imported_film_ids)),
            )
        else:
            cur.execute('DELETE FROM film_years WHERE year = ?', (year,))

        if imported_category_names:
            placeholders = ','.join('?' for _ in imported_category_names)
            cur.execute(
                f'''
                DELETE FROM categories
                WHERE year = ?
                  AND name NOT IN ({placeholders})
                ''',
                (year, *sorted(imported_category_names)),
            )
        else:
            cur.execute('DELETE FROM categories WHERE year = ?', (year,))


def main():
    parser = argparse.ArgumentParser(description='Import a nominee year into SQLite.')
    parser.add_argument('file', type=Path, help='Path to JSON payload (single-year or years bundle).')
    parser.add_argument('--year', type=int, default=None, help='Year key to import when file has multiple years.')
    parser.add_argument('--prune', action='store_true', help='Remove year rows no longer present in payload.')
    args = parser.parse_args()

    source_text = args.file.read_text()
    data_hash = hashlib.sha256(source_text.encode('utf-8')).hexdigest()

    year, payload, schema_version = load_year_payload(args.file, year=args.year)
    validation = validate_year_payload(year, payload)
    if validation['errors']:
        details = '; '.join(validation['errors'])
        _record_import_run(
            year=year,
            source_path=str(args.file),
            data_hash=data_hash,
            schema_version=schema_version,
            status='validation_failed',
            details=details,
        )
        print('Import aborted: validation failed.')
        for error in validation['errors']:
            print(f'ERROR: {error}')
        raise SystemExit(1)

    init_db()
    conn = connect()
    cur = conn.cursor()
    try:
        _import_year(cur, year=year, payload=payload, prune=args.prune)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        _record_import_run(
            year=year,
            source_path=str(args.file),
            data_hash=data_hash,
            schema_version=schema_version,
            status='failed',
            details=str(exc),
        )
        raise
    conn.close()

    _record_import_run(
        year=year,
        source_path=str(args.file),
        data_hash=data_hash,
        schema_version=schema_version,
        status='success',
        details='Imported successfully',
    )

    print(f'Imported year {year} from {args.file}')
    print(f'Counts: {validation["counts"]}')


if __name__ == '__main__':
    main()
