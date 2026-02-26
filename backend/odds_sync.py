import argparse
import csv
import io
import json
import re
import time
from datetime import datetime, timezone

from db import connect, init_db


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _normalize(value):
    text = (value or '').strip().lower()
    text = re.sub(r'&', ' and ', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_american(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        iv = int(value)
        return iv if iv != 0 else None
    text = str(value).strip()
    match = re.search(r'([+-]?\d{2,5})', text)
    if not match:
        return None
    iv = int(match.group(1))
    return iv if iv != 0 else None


def _implied_probability(american):
    if not american:
        return 0.0
    if american > 0:
        return 100.0 / (american + 100.0)
    abs_val = abs(float(american))
    return abs_val / (abs_val + 100.0)


def _weight_points(american):
    if not american:
        return 1.0
    if american > 0:
        return round(1.0 + (float(american) / 100.0), 4)
    return round(1.0 + (100.0 / abs(float(american))), 4)


def _category_aliases():
    return {
        'best director': 'Directing',
        'best directing': 'Directing',
        'best casting': 'Casting',
        'best cinematography': 'Cinematography',
        'best costume design': 'Costume Design',
        'best film editing': 'Film Editing',
        'best makeup and hairstyling': 'Makeup and Hairstyling',
        'best production design': 'Production Design',
        'best sound': 'Sound',
        'best picture': 'Best Picture',
        'best actor': 'Actor in a Leading Role',
        'best supporting actor': 'Actor in a Supporting Role',
        'best actress': 'Actress in a Leading Role',
        'best supporting actress': 'Actress in a Supporting Role',
        'best animated feature': 'Animated Feature Film',
        'best animated feature film': 'Animated Feature Film',
        'best animated short': 'Animated Short Film',
        'best animated short film': 'Animated Short Film',
        'best documentary feature': 'Documentary Feature Film',
        'best documentary feature film': 'Documentary Feature Film',
        'best documentary short': 'Documentary Short Film',
        'best documentary short film': 'Documentary Short Film',
        'best live action short': 'Live Action Short Film',
        'best live action short film': 'Live Action Short Film',
        'best international feature': 'International Feature Film',
        'best international feature film': 'International Feature Film',
        'best adapted screenplay': 'Writing (Adapted Screenplay)',
        'best original screenplay': 'Writing (Original Screenplay)',
        'best screenplay': 'Writing (Original Screenplay)',
        'best original score': 'Music (Original Score)',
        'best original song': 'Music (Original Song)',
        'best visual effects': 'Visual Effects',
    }


def _category_candidates(raw_name):
    norm = _normalize(raw_name)
    if not norm:
        return []
    candidates = [norm]
    stripped = re.sub(r'^best\s+', '', norm).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    stripped_odds = re.sub(r'\s+odds$', '', norm).strip()
    if stripped_odds and stripped_odds not in candidates:
        candidates.append(stripped_odds)
    stripped_both = re.sub(r'^best\s+', '', stripped_odds).strip()
    if stripped_both and stripped_both not in candidates:
        candidates.append(stripped_both)
    return candidates


def _build_mapping(conn, year):
    category_rows = conn.execute(
        'SELECT id, name FROM categories WHERE year = ?',
        (int(year),),
    ).fetchall()
    film_rows = conn.execute(
        '''
        SELECT n.category_id, n.film_id, f.title
        FROM nominations n
        JOIN films f ON f.id = n.film_id
        WHERE n.year = ?
        ''',
        (int(year),),
    ).fetchall()

    category_by_norm = {}
    for row in category_rows:
        category_by_norm[_normalize(row['name'])] = {'id': int(row['id']), 'name': row['name']}
    for alias_norm, real in _category_aliases().items():
        real_norm = _normalize(real)
        if real_norm in category_by_norm:
            category_by_norm[alias_norm] = category_by_norm[real_norm]

    films_by_category = {}
    for row in film_rows:
        cat_id = int(row['category_id'])
        films_by_category.setdefault(cat_id, {})
        films_by_category[cat_id][_normalize(row['title'])] = {
            'filmId': row['film_id'],
            'title': row['title'],
        }

    return category_by_norm, films_by_category


def _match_category(category_by_norm, raw_name):
    candidates = _category_candidates(raw_name)
    if not candidates:
        return None
    for norm in candidates:
        if norm in category_by_norm:
            return category_by_norm[norm]
    for norm in candidates:
        for key, value in category_by_norm.items():
            if key in norm or norm in key:
                return value
    return None


def _match_film(films_map, raw_name):
    norm = _normalize(raw_name)
    if not norm:
        return None
    if norm in films_map:
        return films_map[norm]
    for key, value in films_map.items():
        if key in norm or norm in key:
            return value
    return None


def _map_raw_rows(conn, year, raw_rows):
    category_by_norm, films_by_category = _build_mapping(conn, year)
    mapped_rows = []
    unmapped_rows = []
    for row in raw_rows:
        category = _match_category(category_by_norm, row.get('categoryName', ''))
        if not category:
            unmapped_rows.append({**row, 'reason': 'category_unmapped'})
            continue
        film = _match_film(films_by_category.get(category['id'], {}), row.get('outcomeName', ''))
        if not film:
            unmapped_rows.append({**row, 'reason': 'film_unmapped', 'categoryId': category['id']})
            continue

        american = int(row['americanOdds'])
        mapped_rows.append(
            {
                'categoryId': category['id'],
                'filmId': film['filmId'],
                'americanOdds': american,
                'impliedProbability': _implied_probability(american),
                'weightPoints': _weight_points(american),
            }
        )
    dedup = {}
    for row in mapped_rows:
        dedup[(row['categoryId'], row['filmId'])] = row
    return list(dedup.values()), unmapped_rows


def _persist_snapshot(conn, year, source, now, raw_count, mapped_rows, unmapped_rows, source_meta=None):
    status = 'ok'
    failure_reason = ''
    if not mapped_rows:
        status = 'failed'
        if not raw_count:
            failure_reason = 'No odds rows provided.'
        else:
            failure_reason = 'Odds provided but none mapped to current nominees/categories.'
    elif unmapped_rows:
        status = 'partial'

    raw_payload_obj = {
        'source': source,
        'rawCount': int(raw_count),
        'mappedCount': len(mapped_rows),
        'unmappedCount': len(unmapped_rows),
        'sampleUnmapped': unmapped_rows[:40],
    }
    if source_meta:
        raw_payload_obj['meta'] = source_meta
    raw_payload = json.dumps(raw_payload_obj, ensure_ascii=True)

    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO odds_snapshots(year, source, captured_at, status, raw_payload)
        VALUES(?, ?, ?, ?, ?)
        ''',
        (year, source, now, status, raw_payload),
    )
    snapshot_id = int(cur.lastrowid)
    for row in mapped_rows:
        cur.execute(
            '''
            INSERT INTO odds_snapshot_items(
              snapshot_id, category_id, film_id, american_odds, implied_probability, weight_points
            )
            VALUES(?, ?, ?, ?, ?, ?)
            ''',
            (
                snapshot_id,
                row['categoryId'],
                row['filmId'],
                row['americanOdds'],
                row['impliedProbability'],
                row['weightPoints'],
            ),
        )
    previous_state = conn.execute(
        'SELECT active_snapshot_id, last_success_at FROM odds_sync_state WHERE year = ?',
        (year,),
    ).fetchone()
    previous_active = (
        int(previous_state['active_snapshot_id'])
        if previous_state and previous_state['active_snapshot_id']
        else None
    )
    next_active_snapshot_id = snapshot_id if status in {'ok', 'partial'} else previous_active
    cur.execute(
        '''
        INSERT INTO odds_sync_state(
          year, source, active_snapshot_id, last_success_at, last_attempt_at, last_status,
          mapped_items, unmapped_items, last_error
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(year) DO UPDATE SET
          source=excluded.source,
          active_snapshot_id=excluded.active_snapshot_id,
          last_success_at=excluded.last_success_at,
          last_attempt_at=excluded.last_attempt_at,
          last_status=excluded.last_status,
          mapped_items=excluded.mapped_items,
          unmapped_items=excluded.unmapped_items,
          last_error=excluded.last_error
        ''',
        (
            year,
            source,
            next_active_snapshot_id,
            now if status in {'ok', 'partial'} else (previous_state['last_success_at'] if previous_state else None),
            now,
            status,
            len(mapped_rows),
            len(unmapped_rows),
            failure_reason[:1000],
        ),
    )
    conn.commit()
    return {
        'ok': status in {'ok', 'partial'},
        'year': year,
        'snapshotId': snapshot_id,
        'status': status,
        'rawCount': int(raw_count),
        'mappedCount': len(mapped_rows),
        'unmappedCount': len(unmapped_rows),
        'error': failure_reason,
    }


def parse_manual_rows(text):
    raw_text = (text or '').strip()
    if not raw_text:
        return []

    if raw_text.startswith('['):
        parsed = json.loads(raw_text)
        rows = []
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                category = item.get('categoryName') or item.get('category') or item.get('market') or ''
                outcome = item.get('outcomeName') or item.get('film') or item.get('title') or item.get('selection') or ''
                american = _parse_american(item.get('americanOdds') or item.get('odds') or item.get('price'))
                if category and outcome and american:
                    rows.append(
                        {
                            'categoryName': str(category).strip(),
                            'outcomeName': str(outcome).strip(),
                            'americanOdds': int(american),
                        }
                    )
        return rows

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return []

    rows = []
    if len(lines) >= 2 and ',' in lines[0]:
        try:
            reader = csv.DictReader(io.StringIO('\n'.join(lines)))
            for item in reader:
                if not isinstance(item, dict):
                    continue
                keys = {str(k or '').strip().lower(): v for k, v in item.items()}
                category = (
                    keys.get('category')
                    or keys.get('categoryname')
                    or keys.get('market')
                    or keys.get('marketname')
                    or ''
                )
                outcome = (
                    keys.get('film')
                    or keys.get('title')
                    or keys.get('outcome')
                    or keys.get('outcomename')
                    or keys.get('selection')
                    or ''
                )
                american = _parse_american(
                    keys.get('americanodds') or keys.get('odds') or keys.get('price') or keys.get('line')
                )
                if category and outcome and american:
                    rows.append(
                        {
                            'categoryName': str(category).strip(),
                            'outcomeName': str(outcome).strip(),
                            'americanOdds': int(american),
                        }
                    )
            if rows:
                return rows
        except Exception:
            pass

    for line in lines:
        parts = []
        if '\t' in line:
            parts = [part.strip() for part in line.split('\t')]
        elif '|' in line:
            parts = [part.strip() for part in line.split('|')]
        elif ';' in line:
            parts = [part.strip() for part in line.split(';')]
        elif ',' in line:
            parts = [part.strip() for part in line.split(',')]
        if len(parts) >= 3:
            category, outcome = parts[0], parts[1]
            american = _parse_american(parts[2])
            if category and outcome and american:
                rows.append(
                    {
                        'categoryName': category,
                        'outcomeName': outcome,
                        'americanOdds': int(american),
                    }
                )
    return rows


def import_manual_odds(conn, year, text):
    year = int(year)
    now = _utcnow_iso()
    raw_rows = parse_manual_rows(text)
    mapped_rows, unmapped_rows = _map_raw_rows(conn, year, raw_rows)
    return _persist_snapshot(
        conn,
        year=year,
        source='manual_import',
        now=now,
        raw_count=len(raw_rows),
        mapped_rows=mapped_rows,
        unmapped_rows=unmapped_rows,
        source_meta={'format': 'admin_text'},
    )


def sync_external_odds(conn, year, rows=None, source='external_api'):
    year = int(year)
    now = _utcnow_iso()
    raw_rows = rows if isinstance(rows, list) else []
    try:
        normalized = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            category = str(row.get('categoryName') or row.get('category') or row.get('market') or '').strip()
            outcome = str(row.get('outcomeName') or row.get('film') or row.get('title') or '').strip()
            american = _parse_american(row.get('americanOdds') or row.get('odds') or row.get('price') or row.get('line'))
            if category and outcome and american:
                normalized.append(
                    {
                        'categoryName': category,
                        'outcomeName': outcome,
                        'americanOdds': int(american),
                    }
                )
        mapped_rows, unmapped_rows = _map_raw_rows(conn, year, normalized)
        return _persist_snapshot(
            conn,
            year=year,
            source=str(source or 'external_api')[:64],
            now=now,
            raw_count=len(normalized),
            mapped_rows=mapped_rows,
            unmapped_rows=unmapped_rows,
            source_meta={'format': 'structured_rows'},
        )
    except Exception as error:
        err = str(error)
        conn.execute(
            '''
            INSERT INTO odds_sync_state(
              year, source, active_snapshot_id, last_attempt_at, last_status, mapped_items, unmapped_items, last_error
            )
            VALUES(?, ?, NULL, ?, 'failed', 0, 0, ?)
            ON CONFLICT(year) DO UPDATE SET
              source=excluded.source,
              last_attempt_at=excluded.last_attempt_at,
              last_status='failed',
              last_error=excluded.last_error
            ''',
            (year, str(source or 'external_api')[:64], now, err[:1000]),
        )
        conn.commit()
        return {'ok': False, 'year': year, 'error': err}


def get_odds_status(conn, year):
    year = int(year)
    state_row = conn.execute(
        '''
        SELECT
          source,
          active_snapshot_id AS activeSnapshotId,
          last_success_at AS lastSuccessAt,
          last_attempt_at AS lastAttemptAt,
          last_status AS lastStatus,
          mapped_items AS mappedItems,
          unmapped_items AS unmappedItems,
          last_error AS lastError
        FROM odds_sync_state
        WHERE year = ?
        ''',
        (year,),
    ).fetchone()
    latest_snapshot = conn.execute(
        '''
        SELECT id, source, captured_at AS capturedAt, status
        FROM odds_snapshots
        WHERE year = ?
        ORDER BY id DESC
        LIMIT 1
        ''',
        (year,),
    ).fetchone()
    return {
        'year': year,
        'state': dict(state_row) if state_row else None,
        'latestSnapshot': dict(latest_snapshot) if latest_snapshot else None,
    }


def _default_year(conn):
    row = conn.execute('SELECT year FROM years ORDER BY year DESC LIMIT 1').fetchone()
    return int(row['year']) if row else 2026


def main():
    parser = argparse.ArgumentParser(description='Import odds rows from text into snapshot tables.')
    parser.add_argument('--year', type=int, default=0)
    parser.add_argument('--infile', default='')
    parser.add_argument('--loop-seconds', type=int, default=0)
    args = parser.parse_args()

    init_db()
    conn = connect()
    try:
        year = args.year or _default_year(conn)
        text = ''
        if args.infile:
            with open(args.infile, 'r', encoding='utf-8') as handle:
                text = handle.read()
        if args.loop_seconds and args.loop_seconds > 0:
            while True:
                result = import_manual_odds(conn, year=year, text=text)
                print(json.dumps(result, ensure_ascii=True), flush=True)
                time.sleep(args.loop_seconds)
        else:
            result = import_manual_odds(conn, year=year, text=text)
            print(json.dumps(result, ensure_ascii=True), flush=True)
            status = get_odds_status(conn, year)
            print(json.dumps(status, ensure_ascii=True), flush=True)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
