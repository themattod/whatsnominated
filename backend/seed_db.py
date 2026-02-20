import json
from pathlib import Path

from db import connect, init_db

DATA_PATH = Path(__file__).resolve().parent.parent / 'data' / 'nominees.json'


def seed_year(cur, year_key, payload):
    year = int(year_key)
    cur.execute(
        '''
        INSERT INTO years(year, label)
        VALUES(?, ?)
        ON CONFLICT(year) DO UPDATE SET
          label=excluded.label
        ''',
        (year, payload['label']),
    )

    category_id_by_name = {}
    for category in payload['categories']:
        cur.execute(
            '''
            INSERT INTO categories(year, name, year_started, year_ended)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(year, name) DO UPDATE SET
              year_started=excluded.year_started,
              year_ended=excluded.year_ended
            ''',
            (year, category['name'], category.get('yearStarted'), category.get('yearEnded')),
        )
        row = cur.execute(
            'SELECT id FROM categories WHERE year = ? AND name = ?',
            (year, category['name']),
        ).fetchone()
        category_id_by_name[category['name']] = row['id']

    source_to_canonical = {}
    for film in payload['films']:
        source_film_id = film['id']
        external_id = (film.get('externalId') or '').strip()
        canonical_film_id = source_film_id

        if external_id:
            row = cur.execute(
                'SELECT id FROM films WHERE external_id = ?',
                (external_id,),
            ).fetchone()
            if row:
                canonical_film_id = row['id']
            else:
                row = cur.execute(
                    'SELECT id FROM films WHERE title = ?',
                    (film['title'],),
                ).fetchone()
                if row:
                    canonical_film_id = row['id']
            if canonical_film_id == source_film_id:
                canonical_film_id = external_id

        cur.execute(
            '''
            INSERT INTO films(id, title, external_id)
            VALUES(?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              external_id=COALESCE(NULLIF(films.external_id, ''), excluded.external_id)
            ''',
            (canonical_film_id, film['title'], external_id or canonical_film_id),
        )
        source_to_canonical[source_film_id] = canonical_film_id
        a = film.get('availability', {})
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
                a.get('free', ''),
                a.get('subscription', ''),
                a.get('rent', ''),
                a.get('theaters', ''),
            ),
        )

    cur.execute('DELETE FROM nominations WHERE year = ?', (year,))
    for nomination in payload['nominations']:
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
    for film_id in payload.get('defaultSeenFilmIds', []):
        cur.execute(
            'INSERT INTO default_seen(year, film_id) VALUES(?, ?)',
            (year, source_to_canonical.get(film_id, film_id)),
        )


def main():
    init_db()
    data = json.loads(DATA_PATH.read_text())

    conn = connect()
    cur = conn.cursor()

    for year_key, payload in data['years'].items():
        seed_year(cur, year_key, payload)

    conn.commit()
    conn.close()
    print('Seed complete')


if __name__ == '__main__':
    main()
