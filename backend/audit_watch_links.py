import argparse
import re
from urllib.request import Request, urlopen

from db import connect, init_db


def fetch_html(url, timeout=12):
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


def extract_year_from_title_tag(html):
    # Provider page titles commonly contain: "Title (2025) - ...".
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, flags=re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None

    title_text = title_match.group(1)
    year_match = re.search(r'\((\d{4})\)', title_text)
    if not year_match:
        return None
    return int(year_match.group(1))


def extract_year_from_payload(html):
    m = re.search(r'"originalReleaseYear":(\d{4})', html)
    if not m:
        return None
    return int(m.group(1))


def main():
    parser = argparse.ArgumentParser(
        description='Audit watch-link overrides and remove any pointing to releases before cutoff year.'
    )
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--cutoff', type=int, default=2025)
    parser.add_argument('--timeout', type=float, default=12)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    init_db()
    conn = connect()
    cur = conn.cursor()

    rows = cur.execute(
        '''
        SELECT awl.year, awl.film_id, f.title, awl.url
        FROM admin_watch_links awl
        JOIN films f ON f.id = awl.film_id
        WHERE awl.year = ?
        ORDER BY f.title
        ''',
        (args.year,),
    ).fetchall()

    removed = 0
    kept = 0
    unknown = 0

    for row in rows:
        film_id = row['film_id']
        title = row['title']
        url = row['url']

        try:
            html = fetch_html(url, timeout=args.timeout)
            release_year = extract_year_from_title_tag(html)
            if release_year is None:
                release_year = extract_year_from_payload(html)
        except Exception as exc:
            release_year = None
            print(f'WARN  {film_id} {title}: fetch failed ({exc})', flush=True)

        if release_year is None:
            unknown += 1
            kept += 1
            print(f'KEEP  {film_id} {title}: unknown year -> {url}', flush=True)
            continue

        if release_year < args.cutoff:
            removed += 1
            print(f'REMOVE {film_id} {title}: linked year {release_year} < {args.cutoff} -> {url}', flush=True)
            if not args.dry_run:
                cur.execute(
                    'DELETE FROM admin_watch_links WHERE year = ? AND film_id = ?',
                    (args.year, film_id),
                )
                conn.commit()
        else:
            kept += 1
            print(f'KEEP  {film_id} {title}: linked year {release_year} -> {url}', flush=True)

    print('---', flush=True)
    print(f'Total: {len(rows)}', flush=True)
    print(f'Kept: {kept}', flush=True)
    print(f'Removed: {removed}', flush=True)
    print(f'Unknown year kept: {unknown}', flush=True)
    if args.dry_run:
        print('Dry run only; no deletions committed.', flush=True)

    conn.close()


if __name__ == '__main__':
    main()
