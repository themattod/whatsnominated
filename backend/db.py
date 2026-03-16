import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'oscars.db'


def _resolve_db_path(db_path=None):
    if db_path:
        return Path(db_path)
    env_path = os.getenv('OSCAR_DB_PATH', '').strip()
    if env_path:
        return Path(env_path)
    return DB_PATH


def connect(db_path=None):
    conn = sqlite3.connect(_resolve_db_path(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db(db_path=None):
    conn = connect(db_path=db_path)
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
          nomination_id INTEGER NOT NULL REFERENCES nominations(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(year, category_id, nomination_id)
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

        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          display_name TEXT NOT NULL DEFAULT '',
          password_hash TEXT NOT NULL DEFAULT '',
          email_verified_at TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pools (
          id TEXT PRIMARY KEY,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          name TEXT NOT NULL,
          owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          description TEXT DEFAULT '',
          scoring_mode TEXT NOT NULL DEFAULT 'standard'
            CHECK (scoring_mode IN ('standard','odds_weighted')),
          entry_mode TEXT NOT NULL DEFAULT 'none'
            CHECK (entry_mode IN ('none','manual_transfer')),
          entry_fee_cents INTEGER,
          currency TEXT NOT NULL DEFAULT 'USD',
          payment_required_to_score INTEGER NOT NULL DEFAULT 1
            CHECK (payment_required_to_score IN (0,1)),
          allow_pool_overrides INTEGER NOT NULL DEFAULT 1
            CHECK (allow_pool_overrides IN (0,1)),
          tiebreaker_question TEXT DEFAULT '',
          invite_policy TEXT NOT NULL DEFAULT 'both'
            CHECK (invite_policy IN ('invite_only','share_link','both')),
          status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open','locked','finalized')),
          resolution_state TEXT NOT NULL DEFAULT 'open'
            CHECK (resolution_state IN ('open','locked','pending_tiebreak','finalized')),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pool_members (
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK (role IN ('owner','member')),
          display_name TEXT NOT NULL,
          joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(pool_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS pool_invites (
          id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          created_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          invite_type TEXT NOT NULL CHECK (invite_type IN ('email','share_link')),
          email TEXT DEFAULT '',
          token_hash TEXT NOT NULL UNIQUE,
          max_uses INTEGER,
          uses_count INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT,
          revoked_at TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pool_invite_acceptances (
          id TEXT PRIMARY KEY,
          invite_id TEXT NOT NULL REFERENCES pool_invites(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          accepted_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(invite_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS user_global_picks (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_id, year, category_id)
        );

        CREATE TABLE IF NOT EXISTS pool_pick_overrides (
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(pool_id, user_id, category_id)
        );

        CREATE TABLE IF NOT EXISTS odds_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          source TEXT NOT NULL DEFAULT 'external_api',
          captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
          status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','partial','failed')),
          raw_payload TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS odds_snapshot_items (
          snapshot_id INTEGER NOT NULL REFERENCES odds_snapshots(id) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          american_odds INTEGER NOT NULL,
          implied_probability REAL NOT NULL DEFAULT 0.0,
          weight_points REAL NOT NULL DEFAULT 1.0,
          PRIMARY KEY(snapshot_id, category_id, film_id)
        );

        CREATE TABLE IF NOT EXISTS odds_sync_state (
          year INTEGER PRIMARY KEY REFERENCES years(year) ON DELETE CASCADE,
          source TEXT NOT NULL DEFAULT 'external_api',
          active_snapshot_id INTEGER REFERENCES odds_snapshots(id) ON DELETE SET NULL,
          last_success_at TEXT,
          last_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_status TEXT NOT NULL DEFAULT 'never'
            CHECK (last_status IN ('never','ok','partial','failed')),
          mapped_items INTEGER NOT NULL DEFAULT 0,
          unmapped_items INTEGER NOT NULL DEFAULT 0,
          last_error TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pool_submissions (
          id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
          submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
          scoring_mode_snapshot TEXT NOT NULL CHECK (scoring_mode_snapshot IN ('standard','odds_weighted')),
          odds_snapshot_id INTEGER REFERENCES odds_snapshots(id) ON DELETE SET NULL,
          payment_required_to_score_snapshot INTEGER NOT NULL DEFAULT 1
            CHECK (payment_required_to_score_snapshot IN (0,1)),
          UNIQUE(pool_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS pool_submission_picks (
          submission_id TEXT NOT NULL REFERENCES pool_submissions(id) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          points_possible_snapshot REAL NOT NULL DEFAULT 1.0,
          PRIMARY KEY(submission_id, category_id)
        );

        CREATE TABLE IF NOT EXISTS pool_submission_tiebreaker_answers (
          submission_id TEXT PRIMARY KEY REFERENCES pool_submissions(id) ON DELETE CASCADE,
          answer_text TEXT NOT NULL DEFAULT '',
          submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pool_payment_methods (
          id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          method_type TEXT NOT NULL CHECK (method_type IN ('venmo','paypal','cashapp','zelle','other')),
          handle_or_link TEXT NOT NULL DEFAULT '',
          instructions TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pool_payments (
          id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          amount_cents INTEGER NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'USD',
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','self_reported','confirmed','rejected','waived')),
          proof_file_url TEXT DEFAULT '',
          proof_note TEXT DEFAULT '',
          reported_at TEXT,
          confirmed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          confirmed_at TEXT,
          rejection_reason TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(pool_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS pool_scores (
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          submission_id TEXT NOT NULL REFERENCES pool_submissions(id) ON DELETE CASCADE,
          total_points REAL NOT NULL DEFAULT 0.0,
          correct_count INTEGER NOT NULL DEFAULT 0,
          rank_position INTEGER NOT NULL DEFAULT 1,
          tied_count INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(pool_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS pool_score_breakdown (
          submission_id TEXT NOT NULL REFERENCES pool_submissions(id) ON DELETE CASCADE,
          category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
          picked_film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
          winner_film_id TEXT REFERENCES films(id) ON DELETE SET NULL,
          is_correct INTEGER CHECK (is_correct IN (0,1)),
          points_awarded REAL NOT NULL DEFAULT 0.0,
          PRIMARY KEY(submission_id, category_id)
        );

        CREATE TABLE IF NOT EXISTS pool_tiebreak_reviews (
          id TEXT PRIMARY KEY,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          reviewer_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          submission_id TEXT NOT NULL REFERENCES pool_submissions(id) ON DELETE CASCADE,
          result TEXT NOT NULL CHECK (result IN ('correct','incorrect')),
          notes TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS owner_notifications (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          pool_id TEXT NOT NULL REFERENCES pools(id) ON DELETE CASCADE,
          type TEXT NOT NULL CHECK (type IN ('tiebreak_required','payment_review_required','system')),
          payload_json TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          read_at TEXT
        );

        CREATE TABLE IF NOT EXISTS user_sessions (
          token TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL DEFAULT '',
          expires_at TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS system_flags (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        DROP TABLE IF EXISTS category_pick_locks;
        DROP TABLE IF EXISTS admin_availability;
        '''
    )
    try:
        cur.execute('ALTER TABLE admin_sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ""')
    except sqlite3.OperationalError:
        pass

    # Support nominee-instance picks/winners for categories where the same film
    # can appear more than once (for example multiple acting nominees).
    for table in ('user_picks', 'category_winners'):
        try:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN nomination_id INTEGER REFERENCES nominations(id) ON DELETE CASCADE')
        except sqlite3.OperationalError:
            pass

    cur.execute(
        '''
        UPDATE user_picks
        SET nomination_id = (
          SELECT n.id
          FROM nominations n
          WHERE n.year = user_picks.year
            AND n.category_id = user_picks.category_id
            AND n.film_id = user_picks.film_id
          GROUP BY n.year, n.category_id, n.film_id
          HAVING COUNT(*) = 1
        )
        WHERE nomination_id IS NULL
        '''
    )
    cur.execute(
        '''
        UPDATE category_winners
        SET nomination_id = (
          SELECT n.id
          FROM nominations n
          WHERE n.year = category_winners.year
            AND n.category_id = category_winners.category_id
            AND n.film_id = category_winners.film_id
          GROUP BY n.year, n.category_id, n.film_id
          HAVING COUNT(*) = 1
        )
        WHERE nomination_id IS NULL
        '''
    )
    # If a category/film pair has multiple nominee rows, leave legacy picks unresolved
    # so the user can explicitly choose the intended nominee after deploy.
    cur.execute(
        '''
        UPDATE user_picks
        SET nomination_id = NULL
        WHERE EXISTS (
          SELECT 1
          FROM nominations n
          WHERE n.year = user_picks.year
            AND n.category_id = user_picks.category_id
            AND n.film_id = user_picks.film_id
          GROUP BY n.year, n.category_id, n.film_id
          HAVING COUNT(*) > 1
        )
        '''
    )
    cur.executescript(
        '''
        CREATE INDEX IF NOT EXISTS idx_user_picks_nomination_id ON user_picks(nomination_id);
        CREATE INDEX IF NOT EXISTS idx_category_winners_nomination_id ON category_winners(nomination_id);
        '''
    )
    category_winner_info = cur.execute("PRAGMA table_info(category_winners)").fetchall()
    category_winner_pk = [row[1] for row in category_winner_info if row[5] > 0]
    if category_winner_pk == ['year', 'category_id']:
        cur.executescript(
            '''
            CREATE TABLE IF NOT EXISTS category_winners__new (
              year INTEGER NOT NULL REFERENCES years(year) ON DELETE CASCADE,
              category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
              film_id TEXT NOT NULL REFERENCES films(id) ON DELETE CASCADE,
              nomination_id INTEGER NOT NULL REFERENCES nominations(id) ON DELETE CASCADE,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(year, category_id, nomination_id)
            );
            INSERT OR IGNORE INTO category_winners__new(year, category_id, film_id, nomination_id, updated_at)
            SELECT year, category_id, film_id, nomination_id, updated_at
            FROM category_winners
            WHERE nomination_id IS NOT NULL;
            DROP TABLE category_winners;
            ALTER TABLE category_winners__new RENAME TO category_winners;
            CREATE INDEX IF NOT EXISTS idx_category_winners_nomination_id ON category_winners(nomination_id);
            '''
        )
    supporting_roles_reset_key = 'migration:2026-supporting-roles-repick-v2'
    reset_marker = cur.execute(
        'SELECT value FROM system_flags WHERE key = ?',
        (supporting_roles_reset_key,),
    ).fetchone()
    if not reset_marker:
        cur.execute(
            '''
            UPDATE user_picks
            SET nomination_id = NULL
            WHERE year = 2026
              AND category_id IN (
                SELECT id
                FROM categories
                WHERE year = 2026
                  AND name IN ('Actor in a Supporting Role', 'Actress in a Supporting Role')
              )
            '''
        )
        cur.execute(
            '''
            INSERT INTO system_flags(key, value)
            VALUES(?, 'done')
            ON CONFLICT(key) DO UPDATE SET
              value=excluded.value,
              updated_at=CURRENT_TIMESTAMP
            ''',
            (supporting_roles_reset_key,),
        )

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

    cur.executescript(
        '''
        CREATE INDEX IF NOT EXISTS idx_pools_year ON pools(year);
        CREATE INDEX IF NOT EXISTS idx_pools_owner ON pools(owner_user_id);
        CREATE INDEX IF NOT EXISTS idx_pools_status ON pools(status, resolution_state);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_pool_members_display_name_unique
        ON pool_members(pool_id, lower(display_name));
        CREATE INDEX IF NOT EXISTS idx_pool_members_user ON pool_members(user_id);

        CREATE INDEX IF NOT EXISTS idx_pool_invites_pool ON pool_invites(pool_id);
        CREATE INDEX IF NOT EXISTS idx_pool_invites_expires ON pool_invites(expires_at);

        CREATE INDEX IF NOT EXISTS idx_user_global_picks_year ON user_global_picks(year, user_id);
        CREATE INDEX IF NOT EXISTS idx_pool_pick_overrides_pool_user ON pool_pick_overrides(pool_id, user_id);

        CREATE INDEX IF NOT EXISTS idx_pool_submissions_pool ON pool_submissions(pool_id);
        CREATE INDEX IF NOT EXISTS idx_pool_submissions_user ON pool_submissions(user_id);
        CREATE INDEX IF NOT EXISTS idx_pool_submissions_year ON pool_submissions(year);

        CREATE INDEX IF NOT EXISTS idx_pool_payments_pool_status ON pool_payments(pool_id, status);
        CREATE INDEX IF NOT EXISTS idx_pool_payments_user ON pool_payments(user_id);

        CREATE INDEX IF NOT EXISTS idx_pool_scores_pool_rank ON pool_scores(pool_id, rank_position, total_points DESC);
        CREATE INDEX IF NOT EXISTS idx_pool_tiebreak_reviews_pool ON pool_tiebreak_reviews(pool_id);
        CREATE INDEX IF NOT EXISTS idx_owner_notifications_user ON owner_notifications(user_id, read_at, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_odds_snapshots_year_captured ON odds_snapshots(year, captured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_odds_items_category_film ON odds_snapshot_items(category_id, film_id);
        '''
    )

    conn.commit()
    conn.close()
