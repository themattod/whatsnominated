#!/usr/bin/env python3
import tempfile
from pathlib import Path

from db import connect, init_db
from pools_repo import recompute_pool_scores


def main():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / 'odds_weighted.db'
        init_db(db_path=db_path)
        conn = connect(db_path=db_path)
        cur = conn.cursor()

        cur.execute("INSERT INTO years(year, label) VALUES(2026, '2026')")
        cur.execute("INSERT INTO categories(year, name) VALUES(2026, 'Best Picture')")
        category_id = int(cur.lastrowid)

        cur.execute("INSERT INTO films(id, title) VALUES('FilmA', 'Film A')")
        cur.execute("INSERT INTO films(id, title) VALUES('FilmB', 'Film B')")
        cur.execute(
            'INSERT INTO nominations(year, category_id, film_id, nominee) VALUES(2026, ?, ?, ?)',
            (category_id, 'FilmA', 'Producer A'),
        )
        nomination_a_id = int(cur.lastrowid)
        cur.execute(
            'INSERT INTO nominations(year, category_id, film_id, nominee) VALUES(2026, ?, ?, ?)',
            (category_id, 'FilmB', 'Producer B'),
        )

        cur.execute(
            "INSERT INTO users(id, email, display_name, password_hash) VALUES('U1', 'u1@example.com', 'U1', 'x')"
        )
        cur.execute(
            "INSERT INTO users(id, email, display_name, password_hash) VALUES('U2', 'u2@example.com', 'U2', 'x')"
        )

        cur.execute(
            '''
            INSERT INTO pools(
              id, year, name, owner_user_id, scoring_mode, entry_mode, payment_required_to_score, allow_pool_overrides
            )
            VALUES('P1', 2026, 'Pool 1', 'U1', 'odds_weighted', 'none', 1, 1)
            '''
        )
        cur.execute("INSERT INTO pool_members(pool_id, user_id, role, display_name) VALUES('P1', 'U1', 'owner', 'U1')")
        cur.execute("INSERT INTO pool_members(pool_id, user_id, role, display_name) VALUES('P1', 'U2', 'member', 'U2')")

        cur.execute(
            "INSERT INTO odds_snapshots(year, source, status, raw_payload) VALUES(2026, 'external_api', 'ok', '{}')"
        )
        snapshot_id = int(cur.lastrowid)
        cur.execute(
            '''
            INSERT INTO odds_snapshot_items(snapshot_id, category_id, film_id, american_odds, implied_probability, weight_points)
            VALUES(?, ?, ?, 250, 0.2857, 3.5)
            ''',
            (snapshot_id, category_id, 'FilmA'),
        )
        cur.execute(
            '''
            INSERT INTO odds_snapshot_items(snapshot_id, category_id, film_id, american_odds, implied_probability, weight_points)
            VALUES(?, ?, ?, -150, 0.6, 1.6667)
            ''',
            (snapshot_id, category_id, 'FilmB'),
        )
        cur.execute(
            '''
            INSERT INTO odds_sync_state(year, source, active_snapshot_id, last_status)
            VALUES(2026, 'external_api', ?, 'ok')
            ''',
            (snapshot_id,),
        )

        # Two submissions: U1 picks A, U2 picks B.
        cur.execute(
            '''
            INSERT INTO pool_submissions(
              id, pool_id, user_id, year, scoring_mode_snapshot, odds_snapshot_id, payment_required_to_score_snapshot
            )
            VALUES('S1', 'P1', 'U1', 2026, 'odds_weighted', ?, 1)
            ''',
            (snapshot_id,),
        )
        cur.execute(
            '''
            INSERT INTO pool_submissions(
              id, pool_id, user_id, year, scoring_mode_snapshot, odds_snapshot_id, payment_required_to_score_snapshot
            )
            VALUES('S2', 'P1', 'U2', 2026, 'odds_weighted', ?, 1)
            ''',
            (snapshot_id,),
        )
        cur.execute(
            '''
            INSERT INTO pool_submission_picks(submission_id, category_id, film_id, points_possible_snapshot)
            VALUES('S1', ?, 'FilmA', 3.5)
            ''',
            (category_id,),
        )
        cur.execute(
            '''
            INSERT INTO pool_submission_picks(submission_id, category_id, film_id, points_possible_snapshot)
            VALUES('S2', ?, 'FilmB', 1.6667)
            ''',
            (category_id,),
        )

        # Winner is FilmA.
        cur.execute(
            'INSERT INTO category_winners(year, category_id, film_id, nomination_id) VALUES(2026, ?, ?, ?)',
            (category_id, 'FilmA', nomination_a_id),
        )
        conn.commit()

        recompute_pool_scores(conn, 'P1')
        rows = cur.execute(
            'SELECT user_id, total_points, rank_position FROM pool_scores WHERE pool_id = ? ORDER BY rank_position',
            ('P1',),
        ).fetchall()
        assert len(rows) == 2, f'expected 2 rows, got {len(rows)}'
        assert rows[0]['user_id'] == 'U1', f'expected U1 rank1, got {rows[0]["user_id"]}'
        assert abs(float(rows[0]['total_points']) - 3.5) < 1e-6, rows[0]['total_points']
        assert float(rows[1]['total_points']) == 0.0, rows[1]['total_points']

        conn.close()
    print('odds weighted smoke test: OK')


if __name__ == '__main__':
    main()
