import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'oscars.db'


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.executescript(
        '''
        CREATE TABLE IF NOT EXISTS years (
          year INTEGER PRIMARY KEY,
          label TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          name TEXT NOT NULL,
          year_started INTEGER,
          year_ended INTEGER,
          UNIQUE(year, name)
        );

        CREATE TABLE IF NOT EXISTS films (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          external_id TEXT
        );

        CREATE TABLE IF NOT EXISTS film_years (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          base_free TEXT DEFAULT '',
          base_subscription TEXT DEFAULT '',
          base_rent TEXT DEFAULT '',
          base_theaters TEXT DEFAULT '',
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS nominations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          nominee TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS default_seen (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS user_seen (
          user_key TEXT NOT NULL,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          seen INTEGER NOT NULL CHECK (seen IN (0,1)),
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_key, year, film_id)
        );

        CREATE TABLE IF NOT EXISTS user_picks (
          user_key TEXT NOT NULL,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_key, year, category_id)
        );

        CREATE TABLE IF NOT EXISTS category_winners (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, category_id)
        );

        CREATE TABLE IF NOT EXISTS admin_watch_links (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS admin_watch_labels (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          free_to_watch INTEGER NOT NULL CHECK (free_to_watch IN (0,1)) DEFAULT 0,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS admin_banners (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 1,
          text TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS admin_event_modes (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS admin_voting_locks (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          enabled INTEGER NOT NULL CHECK (enabled IN (0,1)) DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS scraped_posters (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          source TEXT DEFAULT 'google_images',
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS admin_posters (
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          url TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, film_id)
        );

        CREATE TABLE IF NOT EXISTS contact_submissions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL,
          topic TEXT DEFAULT '',
          message TEXT NOT NULL,
          sent INTEGER NOT NULL CHECK (sent IN (0,1)) DEFAULT 0,
          send_error TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_sessions (
          token TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL DEFAULT '',
          expires_at TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_password_resets (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
          expires_at TEXT NOT NULL,
          used_at TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_audit_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          admin_user_id INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
          action TEXT NOT NULL,
          success INTEGER NOT NULL CHECK (success IN (0,1)) DEFAULT 1,
          actor_email TEXT DEFAULT '',
          request_ip TEXT DEFAULT '',
          user_agent TEXT DEFAULT '',
          details TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS year_import_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL,
          source_path TEXT NOT NULL,
          data_hash TEXT NOT NULL,
          schema_version INTEGER,
          status TEXT NOT NULL,
          details TEXT DEFAULT '',
          imported_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        '''
    )

    # Backward-compatible migrations for existing DBs.
    try:
        cur.execute('ALTER TABLE films ADD COLUMN external_id TEXT')
    except sqlite3.OperationalError:
        pass

    cur.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_films_external_id
        ON films(external_id) WHERE external_id IS NOT NULL AND external_id <> ''
        '''
    )
    cur.execute(
        '''
        UPDATE films
        SET external_id = id
        WHERE external_id IS NULL OR external_id = ''
        '''
    )
    # Repair legacy admin sessions created before CSRF tokens were enforced.
    cur.execute(
        '''
        UPDATE admin_sessions
        SET csrf_token = lower(hex(randomblob(24)))
        WHERE csrf_token IS NULL OR trim(csrf_token) = ''
        '''
    )
    cur.executescript(
        '''
        DROP TABLE IF EXISTS user_sessions;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS category_pick_locks;
        DROP TABLE IF EXISTS admin_availability;
        '''
    )
    try:
        cur.execute('ALTER TABLE admin_sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ""')
    except sqlite3.OperationalError:
        pass

    reset_cols = [r[1] for r in cur.execute('PRAGMA table_info(admin_password_resets)').fetchall()]
    if reset_cols and 'token_hash' not in reset_cols:
        cur.executescript(
            '''
            DROP TABLE IF EXISTS admin_password_resets;
            CREATE TABLE IF NOT EXISTS admin_password_resets (
              token_hash TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
              expires_at TEXT NOT NULL,
              used_at TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            '''
        )

    conn.commit()
    conn.close()
