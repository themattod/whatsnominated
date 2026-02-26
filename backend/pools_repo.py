import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone


class PoolRepoError(Exception):
    pass


class PoolValidationError(PoolRepoError):
    pass


class PoolForbiddenError(PoolRepoError):
    pass


class PoolConflictError(PoolRepoError):
    pass


class PoolNotFoundError(PoolRepoError):
    pass


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _normalize_display_name(value):
    return (value or '').strip()


def _is_voting_locked(conn, year):
    row = conn.execute(
        'SELECT enabled FROM admin_voting_locks WHERE year = ?',
        (int(year),),
    ).fetchone()
    return bool(row and row['enabled'])


def _apply_effective_lock_state(pool_row, locked):
    payload = dict(pool_row)
    if payload.get('status') != 'finalized':
        if locked:
            payload['status'] = 'locked'
            if payload.get('resolutionState') == 'open':
                payload['resolutionState'] = 'locked'
        else:
            if payload.get('status') == 'locked':
                payload['status'] = 'open'
            if payload.get('resolutionState') == 'locked':
                payload['resolutionState'] = 'open'
    payload['votingLocked'] = bool(locked)
    return payload


def _ensure_pool_year(conn):
    row = conn.execute('SELECT year FROM years ORDER BY year DESC LIMIT 1').fetchone()
    if not row:
        raise PoolValidationError('No nominee year is available.')
    return int(row['year'])


def _ensure_user(conn, user_id):
    row = conn.execute(
        'SELECT id, email, display_name FROM users WHERE id = ?',
        (user_id,),
    ).fetchone()
    if not row:
        raise PoolValidationError('User not found.')
    return row


def _pool_member_row(conn, pool_id, user_id):
    return conn.execute(
        '''
        SELECT pm.pool_id, pm.user_id, pm.role, pm.display_name
        FROM pool_members pm
        WHERE pm.pool_id = ? AND pm.user_id = ?
        ''',
        (pool_id, user_id),
    ).fetchone()


def _require_owner(conn, pool_id, user_id):
    row = _pool_member_row(conn, pool_id, user_id)
    if not row:
        raise PoolNotFoundError('Pool membership not found.')
    if row['role'] != 'owner':
        raise PoolForbiddenError('Only the pool owner can perform this action.')
    return row


def create_pool(
    conn,
    owner_user_id,
    name,
    description='',
    scoring_mode='standard',
    entry_mode='none',
    entry_fee_cents=None,
    currency='USD',
    payment_required_to_score=True,
    allow_pool_overrides=True,
    tiebreaker_question='',
    invite_policy='both',
    owner_display_name='',
):
    name = (name or '').strip()
    if not name:
        raise PoolValidationError('Pool name is required.')
    if scoring_mode not in {'standard'}:
        raise PoolValidationError('Invalid scoring mode.')
    if entry_mode not in {'none', 'manual_transfer'}:
        raise PoolValidationError('Invalid entry mode.')
    if invite_policy not in {'invite_only', 'share_link', 'both'}:
        raise PoolValidationError('Invalid invite policy.')
    if entry_fee_cents is not None:
        try:
            entry_fee_cents = int(entry_fee_cents)
        except (TypeError, ValueError):
            raise PoolValidationError('Entry fee must be an integer amount in cents.')
        if entry_fee_cents < 0:
            raise PoolValidationError('Entry fee must be non-negative.')
    if entry_mode == 'none':
        entry_fee_cents = None

    user = _ensure_user(conn, owner_user_id)
    year = _ensure_pool_year(conn)
    locked = _is_voting_locked(conn, year)
    pool_id = secrets.token_hex(16)
    now = _utcnow_iso()

    display_name = _normalize_display_name(owner_display_name) or _normalize_display_name(user['display_name'])
    if not display_name:
        display_name = (user['email'] or 'Owner').split('@', 1)[0]

    conn.execute(
        '''
        INSERT INTO pools(
          id, year, name, owner_user_id, description,
          scoring_mode, entry_mode, entry_fee_cents, currency,
          payment_required_to_score, allow_pool_overrides, tiebreaker_question,
          invite_policy, status, resolution_state, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 'open', ?, ?)
        ''',
        (
            pool_id,
            year,
            name,
            owner_user_id,
            (description or '').strip(),
            scoring_mode,
            entry_mode,
            entry_fee_cents,
            (currency or 'USD').strip().upper()[:8],
            1 if payment_required_to_score else 0,
            1 if allow_pool_overrides else 0,
            (tiebreaker_question or '').strip(),
            invite_policy,
            now,
            now,
        ),
    )
    if locked:
        conn.execute(
            '''
            UPDATE pools
            SET status = 'locked',
                resolution_state = CASE
                    WHEN resolution_state = 'open' THEN 'locked'
                    ELSE resolution_state
                END,
                updated_at = ?
            WHERE id = ?
            ''',
            (now, pool_id),
        )
    conn.execute(
        '''
        INSERT INTO pool_members(pool_id, user_id, role, display_name, joined_at)
        VALUES(?, ?, 'owner', ?, ?)
        ''',
        (pool_id, owner_user_id, display_name, now),
    )
    conn.commit()
    return get_pool_for_member(conn, pool_id, owner_user_id)


def list_pools_for_member(conn, user_id, year=None):
    _ensure_user(conn, user_id)
    params = [user_id]
    year_clause = ''
    if year is not None:
        year_clause = 'AND p.year = ?'
        params.append(int(year))
    rows = conn.execute(
        f'''
        SELECT
          p.id,
          p.year,
          p.name,
          p.description,
          p.scoring_mode AS scoringMode,
          p.entry_mode AS entryMode,
          p.entry_fee_cents AS entryFeeCents,
          p.currency,
          p.payment_required_to_score AS paymentRequiredToScore,
          p.allow_pool_overrides AS allowPoolOverrides,
          p.tiebreaker_question AS tiebreakerQuestion,
          p.invite_policy AS invitePolicy,
          p.status,
          p.resolution_state AS resolutionState,
          p.owner_user_id AS ownerUserId,
          pm.role AS memberRole,
          pm.display_name AS displayName,
          pm.joined_at AS joinedAt
        FROM pool_members pm
        JOIN pools p ON p.id = pm.pool_id
        WHERE pm.user_id = ?
          {year_clause}
        ORDER BY p.created_at DESC, p.name ASC
        ''',
        tuple(params),
    ).fetchall()
    result = []
    for row in rows:
        result.append(_apply_effective_lock_state(row, _is_voting_locked(conn, row['year'])))
    return result


def get_pool_for_member(conn, pool_id, user_id):
    row = conn.execute(
        '''
        SELECT
          p.id,
          p.year,
          p.name,
          p.description,
          p.scoring_mode AS scoringMode,
          p.entry_mode AS entryMode,
          p.entry_fee_cents AS entryFeeCents,
          p.currency,
          p.payment_required_to_score AS paymentRequiredToScore,
          p.allow_pool_overrides AS allowPoolOverrides,
          p.tiebreaker_question AS tiebreakerQuestion,
          p.invite_policy AS invitePolicy,
          p.status,
          p.resolution_state AS resolutionState,
          p.owner_user_id AS ownerUserId,
          pm.role AS memberRole,
          pm.display_name AS displayName,
          pm.joined_at AS joinedAt
        FROM pools p
        JOIN pool_members pm ON pm.pool_id = p.id
        WHERE p.id = ? AND pm.user_id = ?
        ''',
        (pool_id, user_id),
    ).fetchone()
    if not row:
        raise PoolNotFoundError('Pool not found.')
    return _apply_effective_lock_state(row, _is_voting_locked(conn, row['year']))


def update_pool(conn, pool_id, owner_user_id, updates):
    _require_owner(conn, pool_id, owner_user_id)
    pool_row = conn.execute('SELECT year FROM pools WHERE id = ?', (pool_id,)).fetchone()
    if not pool_row:
        raise PoolNotFoundError('Pool not found.')
    if _is_voting_locked(conn, pool_row['year']):
        raise PoolForbiddenError('Pool settings are locked.')
    allowed = {
        'name',
        'description',
        'scoring_mode',
        'entry_mode',
        'entry_fee_cents',
        'currency',
        'payment_required_to_score',
        'allow_pool_overrides',
        'tiebreaker_question',
        'invite_policy',
    }
    values = {}
    for key, value in (updates or {}).items():
        if key in allowed:
            values[key] = value
    if not values:
        return get_pool_for_member(conn, pool_id, owner_user_id)

    if 'scoring_mode' in values and values['scoring_mode'] not in {'standard'}:
        raise PoolValidationError('Invalid scoring mode.')
    if 'entry_mode' in values and values['entry_mode'] not in {'none', 'manual_transfer'}:
        raise PoolValidationError('Invalid entry mode.')
    if 'invite_policy' in values and values['invite_policy'] not in {'invite_only', 'share_link', 'both'}:
        raise PoolValidationError('Invalid invite policy.')
    if values.get('entry_mode') == 'none':
        values['entry_fee_cents'] = None

    setters = []
    params = []
    for key, value in values.items():
        col = key
        if key == 'payment_required_to_score':
            value = 1 if bool(value) else 0
        if key == 'allow_pool_overrides':
            value = 1 if bool(value) else 0
        if key == 'currency':
            value = (value or 'USD').strip().upper()[:8]
        if key in {'name', 'description', 'tiebreaker_question'}:
            value = (value or '').strip()
        setters.append(f'{col} = ?')
        params.append(value)

    setters.append('updated_at = ?')
    params.append(_utcnow_iso())
    params.append(pool_id)
    conn.execute(
        f'''
        UPDATE pools
        SET {', '.join(setters)}
        WHERE id = ?
        ''',
        tuple(params),
    )
    conn.commit()
    return get_pool_for_member(conn, pool_id, owner_user_id)


def list_pool_members(conn, pool_id, requester_user_id):
    _ = get_pool_for_member(conn, pool_id, requester_user_id)
    rows = conn.execute(
        '''
        SELECT
          pm.pool_id AS poolId,
          pm.user_id AS userId,
          pm.role,
          pm.display_name AS displayName,
          pm.joined_at AS joinedAt,
          u.email
        FROM pool_members pm
        JOIN users u ON u.id = pm.user_id
        WHERE pm.pool_id = ?
        ORDER BY CASE WHEN pm.role = 'owner' THEN 0 ELSE 1 END, lower(pm.display_name), pm.joined_at
        ''',
        (pool_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_member_display_name(conn, pool_id, target_user_id, actor_user_id, display_name):
    display_name = _normalize_display_name(display_name)
    if not display_name:
        raise PoolValidationError('Display name is required.')
    actor = _pool_member_row(conn, pool_id, actor_user_id)
    if not actor:
        raise PoolNotFoundError('Pool not found.')
    if actor_user_id != target_user_id and actor['role'] != 'owner':
        raise PoolForbiddenError('Only the owner can change another member display name.')
    try:
        row = conn.execute(
            '''
            UPDATE pool_members
            SET display_name = ?
            WHERE pool_id = ? AND user_id = ?
            ''',
            (display_name, pool_id, target_user_id),
        )
    except sqlite3.IntegrityError:
        raise PoolConflictError('Display name already used in this pool.')
    if row.rowcount == 0:
        raise PoolNotFoundError('Member not found in pool.')
    conn.commit()
    return list_pool_members(conn, pool_id, actor_user_id)


def remove_pool_member(conn, pool_id, target_user_id, owner_user_id):
    _require_owner(conn, pool_id, owner_user_id)
    target = _pool_member_row(conn, pool_id, target_user_id)
    if not target:
        raise PoolNotFoundError('Member not found in pool.')
    if target['role'] == 'owner':
        raise PoolValidationError('Owner cannot be removed from pool.')
    conn.execute(
        'DELETE FROM pool_members WHERE pool_id = ? AND user_id = ?',
        (pool_id, target_user_id),
    )
    conn.commit()
    return {'ok': True}


def create_pool_invite(
    conn,
    pool_id,
    owner_user_id,
    invite_type,
    email='',
    max_uses=None,
    expires_at=None,
):
    _require_owner(conn, pool_id, owner_user_id)
    if invite_type not in {'email', 'share_link'}:
        raise PoolValidationError('Invalid invite type.')
    if invite_type == 'email':
        email = (email or '').strip().lower()
        if not email or '@' not in email:
            raise PoolValidationError('Valid invite email is required.')
    else:
        email = ''
    if max_uses is not None:
        try:
            max_uses = int(max_uses)
        except (TypeError, ValueError):
            raise PoolValidationError('max_uses must be an integer.')
        if max_uses < 1:
            raise PoolValidationError('max_uses must be >= 1.')
    invite_id = secrets.token_hex(16)
    raw_token = secrets.token_urlsafe(32)
    conn.execute(
        '''
        INSERT INTO pool_invites(
          id, pool_id, created_by_user_id, invite_type, email,
          token_hash, max_uses, uses_count, expires_at, revoked_at, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?)
        ''',
        (
            invite_id,
            pool_id,
            owner_user_id,
            invite_type,
            email,
            _token_hash(raw_token),
            max_uses,
            expires_at,
            _utcnow_iso(),
        ),
    )
    conn.commit()
    invite = conn.execute(
        '''
        SELECT
          id, pool_id AS poolId, created_by_user_id AS createdByUserId,
          invite_type AS inviteType, email, max_uses AS maxUses, uses_count AS usesCount,
          expires_at AS expiresAt, revoked_at AS revokedAt, created_at AS createdAt
        FROM pool_invites
        WHERE id = ?
        ''',
        (invite_id,),
    ).fetchone()
    payload = dict(invite)
    payload['token'] = raw_token
    return payload


def list_pool_invites(conn, pool_id, owner_user_id):
    _require_owner(conn, pool_id, owner_user_id)
    rows = conn.execute(
        '''
        SELECT
          id, pool_id AS poolId, created_by_user_id AS createdByUserId,
          invite_type AS inviteType, email, max_uses AS maxUses, uses_count AS usesCount,
          expires_at AS expiresAt, revoked_at AS revokedAt, created_at AS createdAt
        FROM pool_invites
        WHERE pool_id = ?
        ORDER BY created_at DESC
        ''',
        (pool_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def revoke_pool_invite(conn, pool_id, invite_id, owner_user_id):
    _require_owner(conn, pool_id, owner_user_id)
    row = conn.execute(
        '''
        UPDATE pool_invites
        SET revoked_at = COALESCE(revoked_at, ?)
        WHERE id = ? AND pool_id = ?
        ''',
        (_utcnow_iso(), invite_id, pool_id),
    )
    if row.rowcount == 0:
        raise PoolNotFoundError('Invite not found.')
    conn.commit()
    return {'ok': True}


def accept_pool_invite(conn, raw_token, user_id, display_name=''):
    _ensure_user(conn, user_id)
    if not raw_token:
        raise PoolValidationError('Invite token is required.')
    token_hash = _token_hash(raw_token)
    invite = conn.execute(
        '''
        SELECT *
        FROM pool_invites
        WHERE token_hash = ?
        ''',
        (token_hash,),
    ).fetchone()
    if not invite:
        raise PoolNotFoundError('Invite not found.')
    if invite['revoked_at']:
        raise PoolForbiddenError('Invite has been revoked.')
    if invite['expires_at']:
        now_iso = _utcnow_iso()
        if str(invite['expires_at']) < now_iso:
            raise PoolForbiddenError('Invite has expired.')
    if invite['max_uses'] is not None and invite['uses_count'] >= invite['max_uses']:
        raise PoolForbiddenError('Invite usage limit reached.')

    member = _pool_member_row(conn, invite['pool_id'], user_id)
    if member:
        return get_pool_for_member(conn, invite['pool_id'], user_id)

    user = _ensure_user(conn, user_id)
    final_display_name = _normalize_display_name(display_name) or _normalize_display_name(user['display_name'])
    if not final_display_name:
        final_display_name = (user['email'] or 'member').split('@', 1)[0]

    acceptance_id = secrets.token_hex(16)
    now = _utcnow_iso()
    conn.execute(
        '''
        INSERT INTO pool_members(pool_id, user_id, role, display_name, joined_at)
        VALUES(?, ?, 'member', ?, ?)
        ''',
        (invite['pool_id'], user_id, final_display_name, now),
    )
    conn.execute(
        '''
        INSERT INTO pool_invite_acceptances(id, invite_id, user_id, accepted_at)
        VALUES(?, ?, ?, ?)
        ''',
        (acceptance_id, invite['id'], user_id, now),
    )
    conn.execute(
        '''
        UPDATE pool_invites
        SET uses_count = uses_count + 1
        WHERE id = ?
        ''',
        (invite['id'],),
    )
    conn.commit()
    return get_pool_for_member(conn, invite['pool_id'], user_id)


def _resolve_category_id(conn, year, category_id=None, category_name=''):
    if category_id is not None:
        row = conn.execute(
            'SELECT id, name FROM categories WHERE year = ? AND id = ?',
            (year, int(category_id)),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT id, name FROM categories WHERE year = ? AND name = ?',
            (year, (category_name or '').strip()),
        ).fetchone()
    if not row:
        raise PoolValidationError('Invalid category.')
    return int(row['id']), row['name']


def _ensure_nominated_pick(conn, year, category_id, film_id):
    row = conn.execute(
        '''
        SELECT 1
        FROM nominations
        WHERE year = ? AND category_id = ? AND film_id = ?
        LIMIT 1
        ''',
        (year, category_id, film_id),
    ).fetchone()
    if not row:
        raise PoolValidationError('Pick must be a nominated film in that category.')


def get_global_picks(conn, user_id, year):
    _ensure_user(conn, user_id)
    year = int(year)
    rows = conn.execute(
        '''
        SELECT
          c.id AS categoryId,
          c.name AS category,
          ugp.film_id AS filmId
        FROM categories c
        LEFT JOIN user_global_picks ugp
          ON ugp.user_id = ? AND ugp.year = c.year AND ugp.category_id = c.id
        WHERE c.year = ?
        ORDER BY c.id
        ''',
        (user_id, year),
    ).fetchall()
    return {
        'year': year,
        'picks': [dict(row) for row in rows],
    }


def upsert_global_pick(conn, user_id, year, category_id=None, category_name='', film_id=''):
    _ensure_user(conn, user_id)
    year = int(year)
    if not film_id:
        raise PoolValidationError('filmId is required.')
    resolved_category_id, resolved_category_name = _resolve_category_id(
        conn,
        year,
        category_id=category_id,
        category_name=category_name,
    )
    _ensure_nominated_pick(conn, year, resolved_category_id, film_id)
    conn.execute(
        '''
        INSERT INTO user_global_picks(user_id, year, category_id, film_id, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(user_id, year, category_id) DO UPDATE SET
          film_id = excluded.film_id,
          updated_at = excluded.updated_at
        ''',
        (user_id, year, resolved_category_id, film_id, _utcnow_iso()),
    )
    conn.commit()
    return {
        'year': year,
        'categoryId': resolved_category_id,
        'category': resolved_category_name,
        'filmId': film_id,
    }


def get_pool_effective_picks(conn, pool_id, user_id):
    pool = get_pool_for_member(conn, pool_id, user_id)
    year = int(pool['year'])
    categories = conn.execute(
        'SELECT id, name FROM categories WHERE year = ? ORDER BY id',
        (year,),
    ).fetchall()
    global_rows = conn.execute(
        'SELECT category_id, film_id FROM user_global_picks WHERE user_id = ? AND year = ?',
        (user_id, year),
    ).fetchall()
    override_rows = conn.execute(
        'SELECT category_id, film_id FROM pool_pick_overrides WHERE pool_id = ? AND user_id = ?',
        (pool_id, user_id),
    ).fetchall()
    global_map = {int(r['category_id']): r['film_id'] for r in global_rows}
    override_map = {int(r['category_id']): r['film_id'] for r in override_rows}

    picks = []
    complete = 0
    for category in categories:
        cat_id = int(category['id'])
        film_id = override_map.get(cat_id, global_map.get(cat_id))
        source = 'override' if cat_id in override_map else ('global' if cat_id in global_map else 'none')
        if film_id:
            complete += 1
        picks.append(
            {
                'categoryId': cat_id,
                'category': category['name'],
                'filmId': film_id or '',
                'source': source,
            }
        )
    return {
        'pool': pool,
        'totalCategories': len(categories),
        'completeCount': complete,
        'picks': picks,
    }


def upsert_pool_override_pick(conn, pool_id, user_id, category_id=None, category_name='', film_id=''):
    pool = get_pool_for_member(conn, pool_id, user_id)
    if pool.get('votingLocked'):
        raise PoolForbiddenError('Pool voting is locked.')
    if not bool(pool.get('allowPoolOverrides')):
        raise PoolForbiddenError('Pool overrides are disabled.')
    year = int(pool['year'])
    resolved_category_id, _ = _resolve_category_id(
        conn,
        year,
        category_id=category_id,
        category_name=category_name,
    )
    if film_id:
        _ensure_nominated_pick(conn, year, resolved_category_id, film_id)
        conn.execute(
            '''
            INSERT INTO pool_pick_overrides(pool_id, user_id, category_id, film_id, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(pool_id, user_id, category_id) DO UPDATE SET
              film_id = excluded.film_id,
              updated_at = excluded.updated_at
            ''',
            (pool_id, user_id, resolved_category_id, film_id, _utcnow_iso()),
        )
    else:
        conn.execute(
            '''
            DELETE FROM pool_pick_overrides
            WHERE pool_id = ? AND user_id = ? AND category_id = ?
            ''',
            (pool_id, user_id, resolved_category_id),
        )
    conn.commit()
    return get_pool_effective_picks(conn, pool_id, user_id)


def get_pool_submission_status(conn, pool_id, user_id):
    pool = get_pool_for_member(conn, pool_id, user_id)
    effective = get_pool_effective_picks(conn, pool_id, user_id)
    submission = conn.execute(
        '''
        SELECT id, submitted_at
        FROM pool_submissions
        WHERE pool_id = ? AND user_id = ?
        ''',
        (pool_id, user_id),
    ).fetchone()
    return {
        'poolId': pool_id,
        'submitted': bool(submission),
        'submissionId': submission['id'] if submission else '',
        'submittedAt': submission['submitted_at'] if submission else '',
        'completeCount': effective['completeCount'],
        'totalCategories': effective['totalCategories'],
        'canSubmit': (not submission) and (effective['completeCount'] == effective['totalCategories']) and (not pool.get('votingLocked')),
    }


def submit_pool_ballot(conn, pool_id, user_id, tiebreaker_answer=''):
    pool = get_pool_for_member(conn, pool_id, user_id)
    if pool.get('votingLocked'):
        raise PoolForbiddenError('Pool voting is locked.')
    existing = conn.execute(
        'SELECT id FROM pool_submissions WHERE pool_id = ? AND user_id = ?',
        (pool_id, user_id),
    ).fetchone()
    if existing:
        raise PoolConflictError('Pool ballot already submitted.')
    effective = get_pool_effective_picks(conn, pool_id, user_id)
    if effective['completeCount'] != effective['totalCategories']:
        raise PoolValidationError('Complete all categories before submitting.')
    if (pool.get('tiebreakerQuestion') or '').strip() and not (tiebreaker_answer or '').strip():
        raise PoolValidationError('Tiebreaker answer is required.')

    odds_snapshot_id = None
    odds_weights = {}
    if pool.get('scoringMode') == 'odds_weighted':
        odds_snapshot_id = _active_odds_snapshot_id(conn, int(pool['year']))
        if not odds_snapshot_id:
            raise PoolValidationError('Odds snapshot unavailable. Try again in a moment.')
        odds_weights = _odds_weight_map(conn, odds_snapshot_id)

    submission_id = secrets.token_hex(16)
    now = _utcnow_iso()
    conn.execute(
        '''
        INSERT INTO pool_submissions(
          id, pool_id, user_id, year, submitted_at,
          scoring_mode_snapshot, odds_snapshot_id, payment_required_to_score_snapshot
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            submission_id,
            pool_id,
            user_id,
            int(pool['year']),
            now,
            pool['scoringMode'],
            odds_snapshot_id,
            1 if bool(pool.get('paymentRequiredToScore')) else 0,
        ),
    )
    for pick in effective['picks']:
        points_possible = 1.0
        if pool.get('scoringMode') == 'odds_weighted':
            points_possible = float(
                odds_weights.get((int(pick['categoryId']), pick['filmId']), 1.0)
            )
        conn.execute(
            '''
            INSERT INTO pool_submission_picks(submission_id, category_id, film_id, points_possible_snapshot)
            VALUES(?, ?, ?, ?)
            ''',
            (submission_id, pick['categoryId'], pick['filmId'], points_possible),
        )
    conn.execute(
        '''
        INSERT INTO pool_submission_tiebreaker_answers(submission_id, answer_text, submitted_at)
        VALUES(?, ?, ?)
        ''',
        (submission_id, (tiebreaker_answer or '').strip(), now),
    )
    conn.commit()
    recompute_pool_scores(conn, pool_id)
    return {
        'ok': True,
        'submissionId': submission_id,
        'submittedAt': now,
    }


def _submission_payment_status(conn, pool_id, user_id):
    row = conn.execute(
        '''
        SELECT status
        FROM pool_payments
        WHERE pool_id = ? AND user_id = ?
        ''',
        (pool_id, user_id),
    ).fetchone()
    if not row:
        return 'pending'
    return row['status']


def _active_odds_snapshot_id(conn, year):
    row = conn.execute(
        '''
        SELECT active_snapshot_id
        FROM odds_sync_state
        WHERE year = ?
        ''',
        (int(year),),
    ).fetchone()
    if row and row['active_snapshot_id']:
        return int(row['active_snapshot_id'])
    latest = conn.execute(
        '''
        SELECT id
        FROM odds_snapshots
        WHERE year = ? AND status IN ('ok', 'partial')
        ORDER BY id DESC
        LIMIT 1
        ''',
        (int(year),),
    ).fetchone()
    return int(latest['id']) if latest else None


def _odds_weight_map(conn, snapshot_id):
    if not snapshot_id:
        return {}
    rows = conn.execute(
        '''
        SELECT category_id, film_id, weight_points
        FROM odds_snapshot_items
        WHERE snapshot_id = ?
        ''',
        (int(snapshot_id),),
    ).fetchall()
    return {(int(r['category_id']), r['film_id']): float(r['weight_points']) for r in rows}


def recompute_pool_scores(conn, pool_id):
    pool = conn.execute('SELECT * FROM pools WHERE id = ?', (pool_id,)).fetchone()
    if not pool:
        raise PoolNotFoundError('Pool not found.')
    year = int(pool['year'])
    winner_by_category = {
        int(r['category_id']): r['film_id']
        for r in conn.execute(
            '''
            SELECT category_id, film_id
            FROM category_winners
            WHERE year = ?
            ''',
            (year,),
        ).fetchall()
    }

    submission_rows = conn.execute(
        '''
        SELECT
          id,
          user_id,
          scoring_mode_snapshot,
          odds_snapshot_id,
          payment_required_to_score_snapshot,
          submitted_at
        FROM pool_submissions
        WHERE pool_id = ?
        ''',
        (pool_id,),
    ).fetchall()

    submission_ids = [row['id'] for row in submission_rows]
    if submission_ids:
        placeholders = ','.join('?' for _ in submission_ids)
        conn.execute(
            f'''
            DELETE FROM pool_score_breakdown
            WHERE submission_id IN ({placeholders})
            ''',
            tuple(submission_ids),
        )
    conn.execute('DELETE FROM pool_scores WHERE pool_id = ?', (pool_id,))

    eligible_scores = []
    odds_cache = {}
    for submission in submission_rows:
        picks = conn.execute(
            '''
            SELECT category_id, film_id, points_possible_snapshot
            FROM pool_submission_picks
            WHERE submission_id = ?
            ''',
            (submission['id'],),
        ).fetchall()
        total_points = 0.0
        correct_count = 0
        submission_odds = {}
        if submission['scoring_mode_snapshot'] == 'odds_weighted':
            snapshot_id = submission['odds_snapshot_id'] or _active_odds_snapshot_id(conn, year)
            if snapshot_id:
                snapshot_id = int(snapshot_id)
                if snapshot_id not in odds_cache:
                    odds_cache[snapshot_id] = _odds_weight_map(conn, snapshot_id)
                submission_odds = odds_cache[snapshot_id]
        for pick in picks:
            category_id = int(pick['category_id'])
            picked_film_id = pick['film_id']
            winner_film_id = winner_by_category.get(category_id)
            is_correct = 1 if winner_film_id and picked_film_id == winner_film_id else 0
            points_possible = float(pick['points_possible_snapshot'])
            if submission['scoring_mode_snapshot'] == 'odds_weighted':
                points_possible = float(submission_odds.get((category_id, picked_film_id), points_possible))
            awarded = points_possible if is_correct else 0.0
            total_points += awarded
            correct_count += is_correct
            conn.execute(
                '''
                INSERT INTO pool_score_breakdown(
                  submission_id, category_id, picked_film_id, winner_film_id, is_correct, points_awarded
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ''',
                (
                    submission['id'],
                    category_id,
                    picked_film_id,
                    winner_film_id,
                    is_correct,
                    awarded,
                ),
            )

        payment_required = bool(submission['payment_required_to_score_snapshot'])
        payment_status = _submission_payment_status(conn, pool_id, submission['user_id'])
        if payment_required and pool['entry_mode'] != 'none' and payment_status not in {'confirmed', 'waived'}:
            continue

        eligible_scores.append(
            {
                'submissionId': submission['id'],
                'userId': submission['user_id'],
                'totalPoints': total_points,
                'correctCount': correct_count,
                'submittedAt': submission['submitted_at'] or '',
            }
        )

    eligible_scores.sort(
        key=lambda item: (-item['totalPoints'], -item['correctCount'], item['submittedAt'], item['userId'])
    )

    idx = 0
    while idx < len(eligible_scores):
        start = idx
        key = (
            eligible_scores[idx]['totalPoints'],
            eligible_scores[idx]['correctCount'],
        )
        while idx + 1 < len(eligible_scores):
            next_key = (
                eligible_scores[idx + 1]['totalPoints'],
                eligible_scores[idx + 1]['correctCount'],
            )
            if next_key != key:
                break
            idx += 1
        tie_count = idx - start + 1
        rank_position = start + 1
        for j in range(start, idx + 1):
            row = eligible_scores[j]
            conn.execute(
                '''
                INSERT INTO pool_scores(
                  pool_id, user_id, submission_id, total_points, correct_count, rank_position, tied_count, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    pool_id,
                    row['userId'],
                    row['submissionId'],
                    row['totalPoints'],
                    row['correctCount'],
                    rank_position,
                    tie_count,
                    _utcnow_iso(),
                ),
            )
        idx += 1
    conn.commit()


def get_pool_leaderboard(conn, pool_id, user_id):
    pool = get_pool_for_member(conn, pool_id, user_id)
    recompute_pool_scores(conn, pool_id)
    members = list_pool_members(conn, pool_id, user_id)
    score_rows = conn.execute(
        '''
        SELECT
          ps.user_id AS userId,
          ps.total_points AS totalPoints,
          ps.correct_count AS correctCount,
          ps.rank_position AS rankPosition,
          ps.tied_count AS tiedCount
        FROM pool_scores ps
        WHERE ps.pool_id = ?
        ORDER BY ps.rank_position ASC, ps.user_id ASC
        ''',
        (pool_id,),
    ).fetchall()
    score_map = {row['userId']: dict(row) for row in score_rows}

    rows = []
    for member in members:
        payment_status = _submission_payment_status(conn, pool_id, member['userId'])
        score = score_map.get(member['userId'])
        rows.append(
            {
                'userId': member['userId'],
                'displayName': member['displayName'],
                'role': member['role'],
                'paymentStatus': payment_status,
                'eligible': bool(score),
                'rankPosition': score['rankPosition'] if score else None,
                'tiedCount': score['tiedCount'] if score else None,
                'totalPoints': score['totalPoints'] if score else None,
                'correctCount': score['correctCount'] if score else None,
            }
        )
    rows.sort(
        key=lambda item: (
            item['rankPosition'] if item['rankPosition'] is not None else 10**9,
            (item['displayName'] or '').lower(),
        )
    )
    return {
        'pool': pool,
        'leaderboard': rows,
    }


def get_pool_results(conn, pool_id, requester_user_id, target_user_id=None):
    _ = get_pool_for_member(conn, pool_id, requester_user_id)
    recompute_pool_scores(conn, pool_id)
    target_ids = []
    if target_user_id:
        if not _pool_member_row(conn, pool_id, target_user_id):
            raise PoolNotFoundError('Requested member not found in pool.')
        target_ids = [target_user_id]
    else:
        target_ids = [row['userId'] for row in list_pool_members(conn, pool_id, requester_user_id)]

    submissions = conn.execute(
        f'''
        SELECT id, user_id
        FROM pool_submissions
        WHERE pool_id = ?
          AND user_id IN ({','.join('?' for _ in target_ids)})
        ''',
        (pool_id, *target_ids),
    ).fetchall()
    submission_map = {row['user_id']: row['id'] for row in submissions}

    out = []
    for user_id in target_ids:
        submission_id = submission_map.get(user_id)
        breakdown = []
        if submission_id:
            rows = conn.execute(
                '''
                SELECT
                  c.id AS categoryId,
                  c.name AS category,
                  b.picked_film_id AS pickedFilmId,
                  b.winner_film_id AS winnerFilmId,
                  b.is_correct AS isCorrect,
                  b.points_awarded AS pointsAwarded
                FROM pool_score_breakdown b
                JOIN categories c ON c.id = b.category_id
                WHERE b.submission_id = ?
                ORDER BY c.id
                ''',
                (submission_id,),
            ).fetchall()
            breakdown = [dict(row) for row in rows]
        out.append(
            {
                'userId': user_id,
                'submissionId': submission_id or '',
                'paymentStatus': _submission_payment_status(conn, pool_id, user_id),
                'breakdown': breakdown,
            }
        )
    return {'results': out}


def get_pool_public_leaderboard(conn, pool_id):
    pool = conn.execute(
        '''
        SELECT
          id,
          year,
          name,
          scoring_mode AS scoringMode,
          status,
          resolution_state AS resolutionState
        FROM pools
        WHERE id = ?
        ''',
        (pool_id,),
    ).fetchone()
    if not pool:
        raise PoolNotFoundError('Pool not found.')
    recompute_pool_scores(conn, pool_id)
    rows = conn.execute(
        '''
        SELECT
          pm.display_name AS displayName,
          pm.role,
          ps.rank_position AS rankPosition,
          ps.tied_count AS tiedCount,
          ps.total_points AS totalPoints,
          ps.correct_count AS correctCount
        FROM pool_members pm
        LEFT JOIN pool_scores ps
          ON ps.pool_id = pm.pool_id AND ps.user_id = pm.user_id
        WHERE pm.pool_id = ?
        ORDER BY
          CASE WHEN ps.rank_position IS NULL THEN 1 ELSE 0 END,
          ps.rank_position ASC,
          lower(pm.display_name) ASC
        ''',
        (pool_id,),
    ).fetchall()
    return {
        'pool': _apply_effective_lock_state(pool, _is_voting_locked(conn, pool['year'])),
        'leaderboard': [dict(row) for row in rows],
    }
