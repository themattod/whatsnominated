# Oscar Tracker (API + SQLite)

This app now runs as a small full-stack service:

- Backend: Python stdlib HTTP server + SQLite
- Frontend: static HTML/CSS/JS served by backend
- Seed data: `seed_data/nominees.json` (generated from your Excel export)

## Run

```bash
cd '/Users/mattod/Documents/Codex/Oscar Tracker'
# Recommended: safe migration wrapper (backs up + validates admin table integrity)
bash scripts/safe_migrate.sh python3 backend/seed_db.py
python3 backend/create_admin.py --email 'admin@example.com' --password 'use-a-strong-password'
python3 backend/server.py
```

Then open: [http://127.0.0.1:8000](http://127.0.0.1:8000)
Admin page: [http://127.0.0.1:8000/admin.html](http://127.0.0.1:8000/admin.html)
Admin login: [http://127.0.0.1:8000/admin-login.html](http://127.0.0.1:8000/admin-login.html)

## Admin Security Notes

- Admin APIs require authenticated admin session cookies.
- Admin write APIs require CSRF header (`X-CSRF-Token`) issued by `/api/admin-auth/session`.
- Password reset tokens are stored hashed (`sha256`) in DB.
- Login and reset endpoints are rate limited with temporary lockouts.
- For production HTTPS, set `OSCAR_COOKIE_SECURE=1` so admin cookies are marked `Secure`.
- Reset/contact mailer supports authenticated SMTP via:
  - `OSCAR_SMTP_HOST`, `OSCAR_SMTP_PORT`
  - `OSCAR_SMTP_USER`, `OSCAR_SMTP_PASS`
  - `OSCAR_SMTP_STARTTLS=1` (recommended for hosted SMTP)
  - `OSCAR_SUPPORT_EMAIL` (contact form recipient; default `matt@whatsnominated.com`)
- Audit logs auto-retain only recent entries (default `90` days). Override with `OSCAR_AUDIT_RETENTION_DAYS`.

## Key behavior

- Seen state is tracked by `film_id`, so one seen button updates all categories.
- Category view supports `All films` or a single nomination category.
- Browsing nominees is public; tracking (`Seen`, `My Pick`, stats) is enabled for anonymous users via a per-browser `userKey`.
- User view shows one `Where to Watch` link per film.
- Default `Where to Watch` is a JustWatch search URL for that film title.
- Admin page allows setting/clearing a per-film watch-link override in DB.
- Each film can show a poster thumbnail.
- If no poster URL exists (or image fails), the UI shows a red `X`.
- Admin page allows setting/clearing a per-film poster override URL.

## Backup DB (pre-launch)

```bash
bash scripts/backup_db.sh
```

Creates timestamped backups at `data/backups/`.

## Safe Migrations (Protect Admin Data)

Always run imports/migrations through the safe wrapper so a backup/export happens first.
Do not run `backend/seed_db.py` or `backend/import_year.py` directly unless debugging.

Use this wrapper for seed/import runs so admin data is snapshotted and validated:

```bash
bash scripts/safe_migrate.sh python3 backend/seed_db.py
bash scripts/safe_migrate.sh python3 backend/import_year.py seed_data/years/2027.json
```

Convenience wrappers (recommended):

```bash
bash scripts/seed_safe.sh
bash scripts/import_year_safe.sh seed_data/years/2027.json
```

Admin table export/import tools:

```bash
python3 backend/export_admin_state.py --out data/backups/admin-state-manual.json
python3 backend/import_admin_state.py --infile data/backups/admin-state-manual.json
```

## Deploy Seed Assets (No Production Rescrape)

To deploy with your **local curated** watch links and posters, export seed assets before push:

```bash
python3 backend/export_seed_assets.py
```

This writes:
- `seed_data/deploy_seed_assets.json` (watch links, labels, poster refs, winners, banner/mode state)
- `seed_data/poster_cache/` (copied local poster cache)

After deploying on Render, run:

```bash
cd /opt/render/project/src
python3 backend/seed_db.py
python3 backend/import_seed_assets.py
python3 backend/create_admin.py --email 'matt@whatsnominated.com' --password 'Marg0tL3onR155y'
```

This avoids re-scraping on Render and restores your local curated state.

## Year Import Workflow (Future + Backfill)

Validate first, then import:

```bash
python3 backend/validate_year.py seed_data/years/2027.json
bash scripts/import_year_safe.sh seed_data/years/2027.json
```

If your JSON is a multi-year bundle:

```bash
python3 backend/validate_year.py seed_data/nominees.json --year 2026
bash scripts/import_year_safe.sh seed_data/nominees.json --year 2026
```

Notes:
- `films.external_id` is now supported for stable global IDs (recommended: IMDb `tt...`).
- Import runs are logged in `year_import_runs`.
- Use `--prune` only when you explicitly want to remove stale year rows not present in payload.

## Poster Scrape

Scrape poster images for films:

```bash
python3 backend/scrape_poster_images.py --year 2026 --force
```
- Schema is year-based, so future years and backfills are supported.

## Watch-Link Scrape / Audit

```bash
python3 backend/scrape_watch_links.py --year 2026 --force
python3 backend/audit_watch_links.py --year 2026 --cutoff 2025
```

## Google Analytics (GA4)

The site is pre-wired for GA4. To enable:

1. Open `web/analytics-config.js`
2. Set:
   ```js
   window.GA_MEASUREMENT_ID = 'G-XXXXXXXXXX';
   ```
3. Refresh the site.

If the value is blank, analytics stays disabled.

## Files

- `backend/server.py`: API + static serving
- `backend/db.py`: schema and DB connection
- `backend/seed_db.py`: imports normalized JSON into SQLite
- `backend/validate_year.py`: validates single-year payloads before import
- `backend/import_year.py`: imports validated year payloads with run tracking
- `backend/year_data_utils.py`: shared load/validation helpers for year payloads
- `backend/export_seed_assets.py`: exports deploy seed assets from local DB/cache
- `backend/import_seed_assets.py`: imports deploy seed assets into deployed DB/cache
- `data/oscars.db`: SQLite database
- `web/index.html`, `web/user.js`, `web/styles.css`: user-facing frontend
- `web/admin.html`, `web/admin.js`: admin frontend
- `web/analytics-config.js`, `web/analytics.js`: GA4 configuration and loader
- `scripts/extract_oscars_data.rb`: Excel-to-JSON generator
