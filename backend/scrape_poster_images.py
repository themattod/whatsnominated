import argparse
import re
import socket
import time
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

from db import connect, init_db

TITLE_DB_BASE = 'https://www.imdb.com'
TITLE_DB_FIND = 'https://www.imdb.com/find/?q={query}&s=tt'
POSTER_CACHE_ROOT = Path(__file__).resolve().parent.parent / 'data' / 'poster_cache'
REQUIRED_HOSTS = ('www.imdb.com', 'm.media-amazon.com')


def fetch_html(url, timeout=8):
    req = Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'en-US,en;q=0.9',
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode('utf-8', errors='ignore')


def download_binary(url, timeout=8):
    req = Request(
        url,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': 'https://www.imdb.com/',
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def extract_first_title_url(find_html):
    # Prefer canonical title links like /title/tt1234567/
    match = re.search(r'href="(/title/tt\d+/[^"]*)"', find_html)
    if not match:
        return None
    return urljoin(TITLE_DB_BASE, unescape(match.group(1)).split('?')[0])


def extract_poster_url(title_html):
    # Title pages generally include og:image pointing at poster/artwork.
    og = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', title_html)
    if og:
        return unescape(og.group(1))

    # Fallback if markup changes.
    img = re.search(r'<img[^>]+src="(https://m\.media-amazon\.com/images/[^"]+)"', title_html)
    if img:
        return unescape(img.group(1))

    return None


def scrape_first_title_db_poster(title, timeout=8):
    find_url = TITLE_DB_FIND.format(query=quote_plus(title))
    find_html = fetch_html(find_url, timeout=timeout)
    title_url = extract_first_title_url(find_html)
    if not title_url:
        return None

    title_html = fetch_html(title_url, timeout=timeout)
    poster_url = extract_poster_url(title_html)
    return poster_url


def _can_resolve(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def cache_poster(year, film_id, poster_url, timeout=8):
    data = download_binary(poster_url, timeout=timeout)
    target = POSTER_CACHE_ROOT / str(year) / f'{film_id}.jpg'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def main():
    parser = argparse.ArgumentParser(description='Scrape poster URLs by film title.')
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--delay', type=float, default=0.4)
    parser.add_argument('--timeout', type=float, default=8)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()

    init_db()
    missing_hosts = [host for host in REQUIRED_HOSTS if not _can_resolve(host)]
    if missing_hosts:
        print(
            'FATAL network preflight failed: cannot resolve required hosts: '
            + ', '.join(missing_hosts),
            flush=True,
        )
        print(
            'No changes were made. Check DNS/network and rerun.',
            flush=True,
        )
        return 2

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
    missing = 0
    skipped = 0

    for row in films:
        year = row['year']
        film_id = row['film_id']
        title = row['title']

        existing = cur.execute(
            'SELECT url FROM scraped_posters WHERE year = ? AND film_id = ?',
            (year, film_id),
        ).fetchone()

        if existing and not args.force:
            skipped += 1
            print(f'SKIP  {film_id} {title}', flush=True)
            continue

        try:
            poster_url = scrape_first_title_db_poster(title, timeout=args.timeout)
        except Exception as exc:
            print(f'ERR   {film_id} {title}: {exc}', flush=True)
            # Network/provider errors should not delete existing cached posters.
            continue

        if poster_url:
            try:
                cache_poster(year, film_id, poster_url, timeout=args.timeout)
                cur.execute(
                    '''
                    INSERT INTO scraped_posters(year, film_id, url, source)
                    VALUES(?, ?, ?, 'lookup')
                    ON CONFLICT(year, film_id) DO UPDATE SET
                      url=excluded.url,
                      source=excluded.source,
                      updated_at=CURRENT_TIMESTAMP
                    ''',
                    (year, film_id, poster_url),
                )
                updated += 1
                print(f'OK    {film_id} {title} -> {poster_url[:90]}', flush=True)
            except Exception as exc:
                poster_url = None
                print(f'ERR   {film_id} {title}: cache failed ({exc})', flush=True)

        if not poster_url:
            target = POSTER_CACHE_ROOT / str(year) / f'{film_id}.jpg'
            if target.exists():
                target.unlink()
            cur.execute(
                'DELETE FROM scraped_posters WHERE year = ? AND film_id = ?',
                (year, film_id),
            )
            missing += 1
            print(f'NONE  {film_id} {title}', flush=True)

        conn.commit()
        time.sleep(args.delay)

    print('---', flush=True)
    print(f'Updated: {updated}', flush=True)
    print(f'Missing: {missing}', flush=True)
    print(f'Skipped: {skipped}', flush=True)

    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
