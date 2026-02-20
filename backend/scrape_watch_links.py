import argparse
import re
import time
from html import unescape
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from db import connect, init_db

WATCH_BASE = 'https://www.justwatch.com'
WATCH_SEARCH = 'https://www.justwatch.com/us/search?q={query}'


def fetch_html(url, timeout=10):
    req = Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode('utf-8', errors='ignore')


def extract_first_result_url(search_html):
    patterns = [
        r'href="(/us/(?:movie|tv-show)/[^"#?]+)"',
        r'"url":"(\\/us\\/(?:movie|tv-show)\\/[^"\\]+)"',
        r'"fullPath":"(\\/us\\/(?:movie|tv-show)\\/[^"\\]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, search_html)
        if not match:
            continue
        path = unescape(match.group(1)).replace('\\/', '/')
        if not path.startswith('/us/'):
            continue
        return f'{WATCH_BASE}{path}'

    return None


def scrape_first_watch_result(title, timeout=10):
    url = WATCH_SEARCH.format(query=quote_plus(title))
    html = fetch_html(url, timeout=timeout)
    return extract_first_result_url(html)


def main():
    parser = argparse.ArgumentParser(
        description='Scrape first watch-provider search result URL for each film and store as watch-link override.'
    )
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--delay', type=float, default=0.35)
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    init_db()
    conn = connect()
    cur = conn.cursor()

    films = cur.execute(
        '''
        SELECT fy.year, f.id AS film_id, f.title
        FROM film_years fy
        JOIN films f ON f.id = fy.film_id
        WHERE fy.year = ?
        ORDER BY f.title
        ''',
        (args.year,),
    ).fetchall()

    updated = 0
    skipped = 0
    missing = 0

    for row in films:
        year = row['year']
        film_id = row['film_id']
        title = row['title']

        existing = cur.execute(
            'SELECT url FROM admin_watch_links WHERE year = ? AND film_id = ?',
            (year, film_id),
        ).fetchone()
        if existing and not args.force:
            skipped += 1
            print(f'SKIP  {film_id} {title} (has override)', flush=True)
            continue

        try:
            result_url = scrape_first_watch_result(title, timeout=args.timeout)
        except Exception as exc:
            result_url = None
            print(f'ERR   {film_id} {title}: {exc}', flush=True)

        if result_url:
            cur.execute(
                '''
                INSERT INTO admin_watch_links(year, film_id, url)
                VALUES(?, ?, ?)
                ON CONFLICT(year, film_id) DO UPDATE SET
                  url=excluded.url,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (year, film_id, result_url),
            )
            conn.commit()
            updated += 1
            print(f'OK    {film_id} {title} -> {result_url}', flush=True)
        else:
            missing += 1
            print(f'NONE  {film_id} {title}', flush=True)

        time.sleep(args.delay)

    print('---', flush=True)
    print(f'Updated: {updated}', flush=True)
    print(f'Skipped: {skipped}', flush=True)
    print(f'Missing: {missing}', flush=True)
    conn.close()


if __name__ == '__main__':
    main()
