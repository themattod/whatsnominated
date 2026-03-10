import json
import mimetypes
import os
import re
import smtplib
import sqlite3
import hmac
import hashlib
import secrets
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen

from db import connect, init_db
from odds_sync import get_odds_status, import_manual_odds, sync_external_odds
from pools_repo import (
    PoolConflictError,
    PoolForbiddenError,
    PoolNotFoundError,
    PoolValidationError,
    accept_pool_invite,
    create_pool_invite,
    get_global_picks,
    get_pool_effective_picks,
    get_pool_leaderboard,
    get_pool_public_leaderboard,
    get_pool_results,
    get_pool_submission_status,
    list_pool_invites,
    list_pool_members,
    remove_pool_member,
    revoke_pool_invite,
    submit_pool_ballot,
    recompute_pool_scores,
    upsert_global_pick,
    upsert_pool_override_pick,
    update_member_display_name,
    create_pool,
    get_pool_for_member,
    list_pools_for_member,
    update_pool,
)

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / 'web'
POSTER_CACHE_ROOT = ROOT / 'data' / 'poster_cache'
ODDS_FEATURE_ENABLED = False
DEFAULT_USER_KEY = 'local-default-user'
DEFAULT_BANNER_TEXT = (
    'MAKE YOUR PICKS BY SUNDAY, MARCH 15, 2026, 7PM PST - '
    'VOTING CLOSES AT THE BEGINNING OF THE OSCARS BROADCAST'
)
SUPPORT_EMAIL = os.getenv('OSCAR_SUPPORT_EMAIL', 'matt@whatsnominated.com')
CONTACT_FROM_EMAIL = os.getenv('OSCAR_CONTACT_FROM', 'no-reply@whatsnominated.com')
SMTP_HOST = os.getenv('OSCAR_SMTP_HOST', '127.0.0.1')
SMTP_PORT = int(os.getenv('OSCAR_SMTP_PORT', '25'))
SMTP_USER = os.getenv('OSCAR_SMTP_USER', '').strip()
SMTP_PASS = os.getenv('OSCAR_SMTP_PASS', '').strip()
SMTP_STARTTLS = os.getenv('OSCAR_SMTP_STARTTLS', '').lower() in {'1', 'true', 'yes'}
APP_BUILD_VERSION = os.getenv('OSCAR_BUILD_VERSION', '20260310-2')
ADMIN_SESSION_COOKIE = 'oscars_admin_session'
ADMIN_SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
USER_SESSION_COOKIE = 'oscars_user_session'
USER_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 10
LOGIN_LOCKOUT_SECONDS = 15 * 60
REGISTER_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
REGISTER_RATE_LIMIT_MAX_ATTEMPTS = 10
INVITE_ACCEPT_RATE_LIMIT_WINDOW_SECONDS = 10 * 60
INVITE_ACCEPT_RATE_LIMIT_MAX_ATTEMPTS = 30
RESET_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
RESET_RATE_LIMIT_MAX_ATTEMPTS = 5
MAX_JSON_BODY_BYTES = 1024 * 1024
AUDIT_LOG_RETENTION_DAYS = max(1, int(os.getenv('OSCAR_AUDIT_RETENTION_DAYS', '90')))


def slugify_title(title):
    slug = (title or '').strip().lower()
    slug = slug.replace('&', ' and ')
    slug = re.sub(r"[^\w\s-]", '', slug)
    slug = re.sub(r"[\s_]+", '-', slug).strip('-')
    return slug


class OscarHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    _login_attempts_by_key = {}
    _login_lockouts = {}
    _user_login_attempts_by_key = {}
    _user_login_lockouts = {}
    _user_register_attempts_by_key = {}
    _invite_accept_attempts_by_key = {}
    _reset_attempts_by_key = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    @staticmethod
    def _poster_cache_path(year, film_id):
        return POSTER_CACHE_ROOT / str(year) / f'{film_id}.jpg'

    def _read_json_body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._json({'ok': False, 'error': 'Invalid Content-Length header.'}, status=HTTPStatus.BAD_REQUEST)
            return None
        if length < 0:
            self._json({'ok': False, 'error': 'Invalid request size.'}, status=HTTPStatus.BAD_REQUEST)
            return None
        if length > MAX_JSON_BODY_BYTES:
            self._json({'ok': False, 'error': 'Request body too large.'}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            self._json({'ok': False, 'error': 'Invalid JSON body.'}, status=HTTPStatus.BAD_REQUEST)
            return None

    def _json(self, payload, status=HTTPStatus.OK, extra_headers=None):
        encoded = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location, status=HTTPStatus.FOUND):
        self.send_response(status)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _parse_cookies(self):
        raw = self.headers.get('Cookie', '')
        result = {}
        if not raw:
            return result
        for part in raw.split(';'):
            if '=' not in part:
                continue
            key, value = part.split('=', 1)
            result[key.strip()] = value.strip()
        return result

    @staticmethod
    def _password_hash(password, salt=None, iterations=180000):
        salt_bytes = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt_bytes, iterations)
        return f'pbkdf2_sha256${iterations}${salt_bytes.hex()}${digest.hex()}'

    @staticmethod
    def _verify_password(password, encoded):
        try:
            algorithm, iterations, salt_hex, digest_hex = encoded.split('$')
            if algorithm != 'pbkdf2_sha256':
                return False
            computed = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                bytes.fromhex(salt_hex),
                int(iterations),
            ).hex()
            return hmac.compare_digest(computed, digest_hex)
        except Exception:
            return False

    def _current_admin(self):
        token = self._parse_cookies().get(ADMIN_SESSION_COOKIE)
        if not token:
            return None
        conn = connect()
        row = conn.execute(
            '''
            SELECT au.id, au.email, s.csrf_token
            FROM admin_sessions s
            JOIN admin_users au ON au.id = s.user_id
            WHERE s.token = ? AND datetime(s.expires_at) > datetime('now')
            ''',
            (token,),
        ).fetchone()
        if not row:
            conn.close()
            return None
        admin = dict(row)
        if not (admin.get('csrf_token') or '').strip():
            new_csrf = secrets.token_urlsafe(24)
            conn.execute(
                'UPDATE admin_sessions SET csrf_token = ? WHERE token = ?',
                (new_csrf, token),
            )
            conn.commit()
            admin['csrf_token'] = new_csrf
        conn.close()
        return admin

    def _require_admin_api(self, require_csrf=False):
        admin = self._current_admin()
        if not admin:
            self._audit_admin(
                'admin_api_unauthorized',
                success=False,
                details={'path': self.path, 'reason': 'no_session'},
            )
            self._json({'ok': False, 'error': 'Admin login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return False
        if require_csrf:
            csrf_header = (self.headers.get('X-CSRF-Token') or '').strip()
            if not csrf_header or csrf_header != (admin.get('csrf_token') or ''):
                self._audit_admin(
                    'admin_api_forbidden',
                    success=False,
                    admin=admin,
                    details={'path': self.path, 'reason': 'csrf_mismatch'},
                )
                self._json({'ok': False, 'error': 'Invalid CSRF token.'}, status=HTTPStatus.FORBIDDEN)
                return False
        return True

    def _current_user(self):
        token = self._parse_cookies().get(USER_SESSION_COOKIE)
        if not token:
            return None
        conn = connect()
        row = conn.execute(
            '''
            SELECT u.id, u.email, u.display_name, s.csrf_token
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND datetime(s.expires_at) > datetime('now')
            ''',
            (token,),
        ).fetchone()
        if not row:
            conn.close()
            return None
        user = dict(row)
        if not (user.get('csrf_token') or '').strip():
            new_csrf = secrets.token_urlsafe(24)
            conn.execute(
                'UPDATE user_sessions SET csrf_token = ? WHERE token = ?',
                (new_csrf, token),
            )
            conn.commit()
            user['csrf_token'] = new_csrf
        conn.close()
        return user

    def _require_user_api(self, require_csrf=False):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return False
        if require_csrf:
            csrf_header = (self.headers.get('X-CSRF-Token') or '').strip()
            if not csrf_header or csrf_header != (user.get('csrf_token') or ''):
                self._json({'ok': False, 'error': 'Invalid CSRF token.'}, status=HTTPStatus.FORBIDDEN)
                return False
        return True

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def _cookie_attrs(self):
        secure_cookie = (
            os.getenv('OSCAR_COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'}
            or (self.headers.get('X-Forwarded-Proto', '').lower() == 'https')
        )
        attrs = 'Path=/; HttpOnly; SameSite=Strict'
        if secure_cookie:
            attrs += '; Secure'
        return attrs

    @staticmethod
    def _rate_limit_prune(buckets, now_ts, window_seconds):
        for key in list(buckets.keys()):
            buckets[key] = [ts for ts in buckets[key] if now_ts - ts <= window_seconds]
            if not buckets[key]:
                buckets.pop(key, None)

    def _client_ip(self):
        forwarded_for = self.headers.get('X-Forwarded-For', '')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return self.client_address[0] if self.client_address else 'unknown'

    def _is_login_locked(self, email):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'email:{email.lower()}', f'ip:{ip}']
        for key in keys:
            locked_until = self._login_lockouts.get(key, 0)
            if locked_until > now_ts:
                return True
            if locked_until:
                self._login_lockouts.pop(key, None)
        return False

    def _record_login_attempt(self, email, success):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'email:{email.lower()}', f'ip:{ip}']
        self._rate_limit_prune(self._login_attempts_by_key, now_ts, LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        if success:
            for key in keys:
                self._login_attempts_by_key.pop(key, None)
                self._login_lockouts.pop(key, None)
            return True
        for key in keys:
            attempts = self._login_attempts_by_key.setdefault(key, [])
            attempts.append(now_ts)
            if len(attempts) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
                self._login_lockouts[key] = now_ts + LOGIN_LOCKOUT_SECONDS
        return False

    def _is_user_login_locked(self, email):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'user-email:{email.lower()}', f'user-ip:{ip}']
        for key in keys:
            locked_until = self._user_login_lockouts.get(key, 0)
            if locked_until > now_ts:
                return True
            if locked_until:
                self._user_login_lockouts.pop(key, None)
        return False

    def _record_user_login_attempt(self, email, success):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'user-email:{email.lower()}', f'user-ip:{ip}']
        self._rate_limit_prune(
            self._user_login_attempts_by_key,
            now_ts,
            LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
        if success:
            for key in keys:
                self._user_login_attempts_by_key.pop(key, None)
                self._user_login_lockouts.pop(key, None)
            return True
        for key in keys:
            attempts = self._user_login_attempts_by_key.setdefault(key, [])
            attempts.append(now_ts)
            if len(attempts) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
                self._user_login_lockouts[key] = now_ts + LOGIN_LOCKOUT_SECONDS
        return False

    def _is_user_register_rate_limited(self):
        now_ts = time.time()
        ip = self._client_ip()
        key = f'register-ip:{ip}'
        self._rate_limit_prune(
            self._user_register_attempts_by_key,
            now_ts,
            REGISTER_RATE_LIMIT_WINDOW_SECONDS,
        )
        attempts = self._user_register_attempts_by_key.setdefault(key, [])
        if len(attempts) >= REGISTER_RATE_LIMIT_MAX_ATTEMPTS:
            return True
        attempts.append(now_ts)
        return False

    def _is_invite_accept_rate_limited(self, user_id=''):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'invite-ip:{ip}']
        if user_id:
            keys.append(f'invite-user:{user_id}')
        self._rate_limit_prune(
            self._invite_accept_attempts_by_key,
            now_ts,
            INVITE_ACCEPT_RATE_LIMIT_WINDOW_SECONDS,
        )
        limited = False
        for key in keys:
            attempts = self._invite_accept_attempts_by_key.setdefault(key, [])
            if len(attempts) >= INVITE_ACCEPT_RATE_LIMIT_MAX_ATTEMPTS:
                limited = True
            else:
                attempts.append(now_ts)
        return limited

    def _is_reset_rate_limited(self, email):
        now_ts = time.time()
        ip = self._client_ip()
        keys = [f'reset-email:{email.lower()}', f'reset-ip:{ip}']
        self._rate_limit_prune(self._reset_attempts_by_key, now_ts, RESET_RATE_LIMIT_WINDOW_SECONDS)
        limited = False
        for key in keys:
            attempts = self._reset_attempts_by_key.setdefault(key, [])
            if len(attempts) >= RESET_RATE_LIMIT_MAX_ATTEMPTS:
                limited = True
            else:
                attempts.append(now_ts)
        return limited

    def _create_admin_session(self, user_id):
        self._prune_admin_auth_artifacts()
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        conn = connect()
        conn.execute(
            '''
            INSERT INTO admin_sessions(token, user_id, csrf_token, expires_at)
            VALUES(?, ?, ?, datetime('now', '+14 days'))
            ''',
            (token, user_id, csrf_token),
        )
        conn.commit()
        conn.close()
        return token, csrf_token

    def _create_user_session(self, user_id):
        self._prune_user_auth_artifacts()
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        conn = connect()
        conn.execute(
            '''
            INSERT INTO user_sessions(token, user_id, csrf_token, expires_at)
            VALUES(?, ?, ?, datetime('now', '+30 days'))
            ''',
            (token, user_id, csrf_token),
        )
        conn.commit()
        conn.close()
        return token, csrf_token

    def _prune_admin_auth_artifacts(self):
        conn = connect()
        conn.execute(
            '''
            DELETE FROM admin_sessions
            WHERE datetime(expires_at) <= datetime('now')
            '''
        )
        conn.execute(
            '''
            DELETE FROM admin_password_resets
            WHERE used_at IS NOT NULL OR datetime(expires_at) <= datetime('now')
            '''
        )
        conn.commit()
        conn.close()

    def _prune_user_auth_artifacts(self):
        conn = connect()
        conn.execute(
            '''
            DELETE FROM user_sessions
            WHERE datetime(expires_at) <= datetime('now')
            '''
        )
        conn.commit()
        conn.close()

    def _prune_admin_audit_logs(self):
        conn = connect()
        conn.execute(
            '''
            DELETE FROM admin_audit_logs
            WHERE datetime(created_at) < datetime('now', ?)
            ''',
            (f'-{AUDIT_LOG_RETENTION_DAYS} days',),
        )
        conn.commit()
        conn.close()

    def _clear_admin_session(self):
        token = self._parse_cookies().get(ADMIN_SESSION_COOKIE)
        if not token:
            return
        conn = connect()
        conn.execute('DELETE FROM admin_sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()

    def _clear_user_session(self):
        token = self._parse_cookies().get(USER_SESSION_COOKIE)
        if not token:
            return
        conn = connect()
        conn.execute('DELETE FROM user_sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()

    def _base_url(self):
        host = self.headers.get('Host', '127.0.0.1:8000')
        proto = self.headers.get('X-Forwarded-Proto', '').strip().lower()
        scheme = 'https' if proto == 'https' else 'http'
        return f'{scheme}://{host}'

    def _audit_admin(self, action, success=True, admin=None, actor_email='', details=None):
        try:
            self._prune_admin_audit_logs()
            admin_id = None
            if admin and admin.get('id'):
                admin_id = admin['id']
                actor_email = actor_email or admin.get('email', '')
            payload = details if isinstance(details, dict) else {'note': str(details or '')}
            conn = connect()
            conn.execute(
                '''
                INSERT INTO admin_audit_logs(
                  admin_user_id, action, success, actor_email, request_ip, user_agent, details
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    admin_id,
                    action,
                    1 if success else 0,
                    actor_email or '',
                    self._client_ip(),
                    self.headers.get('User-Agent', ''),
                    json.dumps(payload, separators=(',', ':'), ensure_ascii=True),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    @staticmethod
    def _smtp_send_message(email_message):
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=8) as smtp:
            if SMTP_STARTTLS:
                smtp.starttls()
            if SMTP_USER and SMTP_PASS:
                smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(email_message)

    @staticmethod
    def _first_watch_result_url(title):
        search_url = f'https://www.justwatch.com/us/search?q={quote_plus(title)}'

        try:
            req = Request(
                search_url,
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/122.0.0.0 Safari/537.36'
                    ),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
            )
            with urlopen(req, timeout=12) as response:
                html = response.read().decode('utf-8', errors='ignore')
        except Exception:
            slug = slugify_title(title)
            if slug:
                return f'https://www.justwatch.com/us/movie/{slug}'
            return search_url

        patterns = [
            r'href="(/us/(?:movie|tv-show)/[^"#?]+)"',
            r'"url":"(\\/us\\/(?:movie|tv-show)\\/[^"\\]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if not match:
                continue
            path = match.group(1).replace('\\/', '/')
            if not path.startswith('/us/'):
                continue
            return f'https://www.justwatch.com{path}'

        slug = slugify_title(title)
        if slug:
            return f'https://www.justwatch.com/us/movie/{slug}'
        return search_url

    @staticmethod
    def _is_public_pool_api_path(path):
        return bool(re.match(r'^/api/pools/[^/]+/(public|recap/public)(?:/.*)?$', path or ''))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {'/admin.html', '/admin-audit.html'} and not self._current_admin():
            return self._redirect('/admin-login.html')
        if parsed.path == '/where-to-watch':
            return self._handle_where_to_watch_redirect(parsed)
        if parsed.path.startswith('/api/'):
            return self._handle_api_get(parsed)
        return super().do_GET()

    def _handle_where_to_watch_redirect(self, parsed):
        query = parse_qs(parsed.query)
        title = (query.get('title', [''])[0] or '').strip()
        if not title:
            return self._redirect('https://www.justwatch.com/us')
        target = self._first_watch_result_url(title)
        return self._redirect(target)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            return self._handle_api_put(parsed)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            return self._handle_api_post(parsed)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            return self._handle_api_patch(parsed)
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/'):
            return self._handle_api_delete(parsed)
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_get(self, parsed):
        query = parse_qs(parsed.query)
        if parsed.path == '/api/admin-auth/session':
            return self._get_admin_auth_session()
        if parsed.path == '/api/auth/session':
            return self._get_user_auth_session()
        if parsed.path == '/api/years':
            return self._get_years()
        if parsed.path == '/api/app-version':
            return self._json({'version': APP_BUILD_VERSION})
        if parsed.path.startswith('/api/picks'):
            if not self._require_user_api():
                return
        if (
            (parsed.path.startswith('/api/pools') or parsed.path.startswith('/api/invites'))
            and not self._is_public_pool_api_path(parsed.path)
        ):
            if not self._require_user_api():
                return
        if parsed.path.startswith('/api/admin/audit'):
            if not self._require_admin_api():
                return
            return self._get_admin_audit_logs(query)
        if parsed.path == '/api/admin/pools/troubleshoot':
            if not self._require_admin_api():
                return
            return self._get_admin_pools_troubleshoot(query)
        admin_pool_detail_match = re.match(r'^/api/admin/pools/([^/]+)/troubleshoot$', parsed.path)
        if admin_pool_detail_match:
            if not self._require_admin_api():
                return
            return self._get_admin_pool_troubleshoot_detail(admin_pool_detail_match.group(1))
        if parsed.path == '/api/admin/dashboard':
            if not self._require_admin_api():
                return
            year = int(query.get('year', ['2026'])[0])
            return self._get_admin_dashboard(year)
        if parsed.path == '/api/admin/odds/status':
            if not self._require_admin_api():
                return
            if not ODDS_FEATURE_ENABLED:
                self._json({'ok': False, 'error': 'Odds feature is disabled.'}, status=HTTPStatus.GONE)
                return
            year = int(query.get('year', ['2026'])[0])
            return self._get_admin_odds_status(year)
        if parsed.path == '/api/nominees':
            year = int(query.get('year', ['2026'])[0])
            category = query.get('category', ['__ALL__'])[0]
            return self._get_nominees(year, category)
        if parsed.path == '/api/picks/global':
            year_value = query.get('year', [''])[0].strip()
            if not year_value:
                self._json({'ok': False, 'error': 'year is required.'}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                year = int(year_value)
            except ValueError:
                self._json({'ok': False, 'error': 'Invalid year.'}, status=HTTPStatus.BAD_REQUEST)
                return
            return self._get_global_picks_api(year)
        if parsed.path == '/api/pools':
            year_value = query.get('year', [''])[0].strip()
            year = None
            if year_value:
                try:
                    year = int(year_value)
                except ValueError:
                    self._json({'ok': False, 'error': 'Invalid year.'}, status=HTTPStatus.BAD_REQUEST)
                    return
            return self._get_pools(year=year)
        pool_members_match = re.match(r'^/api/pools/([^/]+)/members$', parsed.path)
        if pool_members_match:
            return self._get_pool_members(pool_members_match.group(1))
        pool_picks_match = re.match(r'^/api/pools/([^/]+)/picks$', parsed.path)
        if pool_picks_match:
            return self._get_pool_picks(pool_picks_match.group(1))
        pool_submission_status_match = re.match(r'^/api/pools/([^/]+)/submission-status$', parsed.path)
        if pool_submission_status_match:
            return self._get_pool_submission_status(pool_submission_status_match.group(1))
        pool_leaderboard_match = re.match(r'^/api/pools/([^/]+)/leaderboard$', parsed.path)
        if pool_leaderboard_match:
            return self._get_pool_leaderboard_api(pool_leaderboard_match.group(1))
        pool_results_user_match = re.match(r'^/api/pools/([^/]+)/results/([^/]+)$', parsed.path)
        if pool_results_user_match:
            return self._get_pool_results_api(pool_results_user_match.group(1), pool_results_user_match.group(2))
        pool_results_match = re.match(r'^/api/pools/([^/]+)/results$', parsed.path)
        if pool_results_match:
            return self._get_pool_results_api(pool_results_match.group(1), '')
        pool_invites_match = re.match(r'^/api/pools/([^/]+)/invites$', parsed.path)
        if pool_invites_match:
            return self._get_pool_invites(pool_invites_match.group(1))
        pool_public_match = re.match(r'^/api/pools/([^/]+)/public$', parsed.path)
        if pool_public_match:
            return self._get_pool_public_api(pool_public_match.group(1))
        pool_id_match = re.match(r'^/api/pools/([^/]+)$', parsed.path)
        if pool_id_match:
            return self._get_pool(pool_id_match.group(1))
        if parsed.path == '/api/user-state':
            year = int(query.get('year', ['2026'])[0])
            user_key = query.get('userKey', [''])[0]
            return self._get_user_state(year, user_key)
        if parsed.path == '/api/poster-image':
            year = int(query.get('year', ['2026'])[0])
            film_id = query.get('filmId', [''])[0]
            return self._get_poster_image(year, film_id)

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_put(self, parsed):
        if parsed.path.startswith('/api/picks'):
            if not self._require_user_api(require_csrf=True):
                return
        if parsed.path.startswith('/api/pools'):
            if not self._require_user_api(require_csrf=True):
                return
        if parsed.path == '/api/user-state':
            body = self._read_json_body()
            if body is None:
                return
            return self._put_user_state(body)
        if parsed.path == '/api/user-pick':
            body = self._read_json_body()
            if body is None:
                return
            return self._put_user_pick(body)
        if parsed.path == '/api/picks/global':
            body = self._read_json_body()
            if body is None:
                return
            return self._put_global_pick_api(body)
        pool_picks_match = re.match(r'^/api/pools/([^/]+)/picks$', parsed.path)
        if pool_picks_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._put_pool_pick_api(pool_picks_match.group(1), body)
        if parsed.path == '/api/admin/where-to-watch':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_where_to_watch(body)
        if parsed.path == '/api/admin/banner':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_banner(body)
        if parsed.path == '/api/admin/event-mode':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_event_mode(body)
        if parsed.path == '/api/admin/voting-lock':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_voting_lock(body)
        if parsed.path == '/api/admin/poster':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_poster(body)
        if parsed.path == '/api/admin/winner':
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_winner(body)
        admin_pool_payment_match = re.match(r'^/api/admin/pools/([^/]+)/payments$', parsed.path)
        if admin_pool_payment_match:
            if not self._require_admin_api(require_csrf=True):
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._put_admin_pool_payment_status(admin_pool_payment_match.group(1), body)

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_post(self, parsed):
        if parsed.path == '/api/auth/register':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_user_auth_register(body)
        if parsed.path == '/api/auth/login':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_user_auth_login(body)
        if parsed.path == '/api/auth/logout':
            return self._post_user_auth_logout()
        if (
            (parsed.path.startswith('/api/pools') or parsed.path.startswith('/api/invites'))
            and not self._is_public_pool_api_path(parsed.path)
        ):
            if not self._require_user_api(require_csrf=True):
                return
        if parsed.path == '/api/admin-auth/login':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_admin_auth_login(body)
        if parsed.path == '/api/admin-auth/logout':
            return self._post_admin_auth_logout()
        if parsed.path == '/api/admin-auth/request-reset':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_admin_auth_request_reset(body)
        if parsed.path == '/api/admin-auth/reset':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_admin_auth_reset(body)
        if parsed.path == '/api/contact':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_contact(body)
        if parsed.path == '/api/admin/odds/sync':
            if not self._require_admin_api(require_csrf=True):
                return
            if not ODDS_FEATURE_ENABLED:
                self._json({'ok': False, 'error': 'Odds feature is disabled.'}, status=HTTPStatus.GONE)
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._post_admin_odds_sync(body)
        if parsed.path == '/api/admin/odds/import':
            if not self._require_admin_api(require_csrf=True):
                return
            if not ODDS_FEATURE_ENABLED:
                self._json({'ok': False, 'error': 'Odds feature is disabled.'}, status=HTTPStatus.GONE)
                return
            body = self._read_json_body()
            if body is None:
                return
            return self._post_admin_odds_import(body)
        admin_pool_recompute_match = re.match(r'^/api/admin/pools/([^/]+)/recompute-scores$', parsed.path)
        if admin_pool_recompute_match:
            if not self._require_admin_api(require_csrf=True):
                return
            return self._post_admin_pool_recompute_scores(admin_pool_recompute_match.group(1))
        if parsed.path == '/api/pools':
            body = self._read_json_body()
            if body is None:
                return
            return self._post_pool(body)
        pool_submit_match = re.match(r'^/api/pools/([^/]+)/submit$', parsed.path)
        if pool_submit_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._post_pool_submit(pool_submit_match.group(1), body)
        pool_invite_email_match = re.match(r'^/api/pools/([^/]+)/invites/email$', parsed.path)
        if pool_invite_email_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._post_pool_invite_email(pool_invite_email_match.group(1), body)
        pool_invite_link_match = re.match(r'^/api/pools/([^/]+)/invites/link$', parsed.path)
        if pool_invite_link_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._post_pool_invite_link(pool_invite_link_match.group(1), body)
        invite_accept_match = re.match(r'^/api/invites/([^/]+)/accept$', parsed.path)
        if invite_accept_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._post_pool_invite_accept(invite_accept_match.group(1), body)
        pool_invite_revoke_match = re.match(r'^/api/pools/([^/]+)/invites/([^/]+)/revoke$', parsed.path)
        if pool_invite_revoke_match:
            return self._post_pool_invite_revoke(
                pool_invite_revoke_match.group(1),
                pool_invite_revoke_match.group(2),
            )
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_patch(self, parsed):
        if (
            (parsed.path.startswith('/api/pools') or parsed.path.startswith('/api/invites'))
            and not self._is_public_pool_api_path(parsed.path)
        ):
            if not self._require_user_api(require_csrf=True):
                return
        pool_id_match = re.match(r'^/api/pools/([^/]+)$', parsed.path)
        if pool_id_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._patch_pool(pool_id_match.group(1), body)
        member_display_name_match = re.match(
            r'^/api/pools/([^/]+)/members/([^/]+)/display-name$',
            parsed.path,
        )
        if member_display_name_match:
            body = self._read_json_body()
            if body is None:
                return
            return self._patch_pool_member_display_name(
                member_display_name_match.group(1),
                member_display_name_match.group(2),
                body,
            )
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_delete(self, parsed):
        if (
            (parsed.path.startswith('/api/pools') or parsed.path.startswith('/api/invites'))
            and not self._is_public_pool_api_path(parsed.path)
        ):
            if not self._require_user_api(require_csrf=True):
                return
        pool_member_match = re.match(r'^/api/pools/([^/]+)/members/([^/]+)$', parsed.path)
        if pool_member_match:
            return self._delete_pool_member(
                pool_member_match.group(1),
                pool_member_match.group(2),
            )
        self.send_error(HTTPStatus.NOT_FOUND)

    def _pool_error_json(self, error):
        if isinstance(error, PoolValidationError):
            self._json({'ok': False, 'error': str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        if isinstance(error, PoolForbiddenError):
            self._json({'ok': False, 'error': str(error)}, status=HTTPStatus.FORBIDDEN)
            return
        if isinstance(error, PoolConflictError):
            self._json({'ok': False, 'error': str(error)}, status=HTTPStatus.CONFLICT)
            return
        if isinstance(error, PoolNotFoundError):
            self._json({'ok': False, 'error': str(error)}, status=HTTPStatus.NOT_FOUND)
            return
        self._json({'ok': False, 'error': 'Unexpected pool error.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _get_admin_auth_session(self):
        admin = self._current_admin()
        if not admin:
            self._json({'loggedIn': False})
            return
        self._json(
            {
                'loggedIn': True,
                'admin': {'id': admin['id'], 'email': admin['email']},
                'csrfToken': admin.get('csrf_token') or '',
            }
        )

    def _get_user_auth_session(self):
        user = self._current_user()
        if not user:
            self._json({'loggedIn': False})
            return
        self._json(
            {
                'loggedIn': True,
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'displayName': user.get('display_name') or '',
                },
                'csrfToken': user.get('csrf_token') or '',
            }
        )

    def _post_user_auth_register(self, body):
        if self._is_user_register_rate_limited():
            self._json(
                {'ok': False, 'error': 'Too many signup attempts. Try again later.'},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        email = (body.get('email') or '').strip().lower()
        password = body.get('password') or ''
        display_name = (body.get('displayName') or '').strip()
        if not email or '@' not in email:
            self._json({'ok': False, 'error': 'Valid email is required.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if len(password) < 8:
            self._json({'ok': False, 'error': 'Password must be at least 8 characters.'}, status=HTTPStatus.BAD_REQUEST)
            return
        user_id = secrets.token_hex(16)
        password_hash = self._password_hash(password)
        conn = connect()
        try:
            conn.execute(
                '''
                INSERT INTO users(id, email, display_name, password_hash)
                VALUES(?, ?, ?, ?)
                ''',
                (user_id, email, display_name, password_hash),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            self._json({'ok': False, 'error': 'An account with that email already exists.'}, status=HTTPStatus.CONFLICT)
            return
        conn.close()

        token, csrf_token = self._create_user_session(user_id)
        self._json(
            {
                'ok': True,
                'loggedIn': True,
                'user': {'id': user_id, 'email': email, 'displayName': display_name},
                'csrfToken': csrf_token,
            },
            extra_headers={
                'Set-Cookie': (
                    f'{USER_SESSION_COOKIE}={token}; {self._cookie_attrs()}; '
                    f'Max-Age={USER_SESSION_TTL_SECONDS}'
                )
            },
        )

    def _post_user_auth_login(self, body):
        email = (body.get('email') or '').strip().lower()
        password = body.get('password') or ''
        if self._is_user_login_locked(email):
            self._json(
                {'ok': False, 'error': 'Too many attempts. Try again later.'},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        conn = connect()
        row = conn.execute(
            'SELECT id, email, display_name, password_hash FROM users WHERE lower(email) = ?',
            (email,),
        ).fetchone()
        conn.close()

        if not row or not self._verify_password(password, row['password_hash']):
            self._record_user_login_attempt(email, False)
            self._json({'ok': False, 'error': 'Invalid email or password.'}, status=HTTPStatus.UNAUTHORIZED)
            return

        self._record_user_login_attempt(email, True)
        token, csrf_token = self._create_user_session(row['id'])
        self._json(
            {
                'ok': True,
                'loggedIn': True,
                'user': {
                    'id': row['id'],
                    'email': row['email'],
                    'displayName': row['display_name'] or '',
                },
                'csrfToken': csrf_token,
            },
            extra_headers={
                'Set-Cookie': (
                    f'{USER_SESSION_COOKIE}={token}; {self._cookie_attrs()}; '
                    f'Max-Age={USER_SESSION_TTL_SECONDS}'
                )
            },
        )

    def _post_user_auth_logout(self):
        user = self._current_user()
        if user and not self._require_user_api(require_csrf=True):
            return
        self._clear_user_session()
        self._json(
            {'ok': True},
            extra_headers={
                'Set-Cookie': (
                    f'{USER_SESSION_COOKIE}=; {self._cookie_attrs()}; Max-Age=0'
                )
            },
        )

    def _post_admin_auth_login(self, body):
        email = (body.get('email') or '').strip().lower()
        password = body.get('password') or ''
        if self._is_login_locked(email):
            self._audit_admin(
                'admin_login',
                success=False,
                actor_email=email,
                details={'reason': 'rate_limited'},
            )
            self._json(
                {'ok': False, 'error': 'Too many attempts. Try again later.'},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        conn = connect()
        row = conn.execute(
            'SELECT id, email, password_hash FROM admin_users WHERE lower(email) = ?',
            (email,),
        ).fetchone()
        conn.close()

        if not row or not self._verify_password(password, row['password_hash']):
            self._record_login_attempt(email, False)
            self._audit_admin(
                'admin_login',
                success=False,
                actor_email=email,
                details={'reason': 'invalid_credentials'},
            )
            self._json(
                {'ok': False, 'error': 'Invalid email or password.'},
                status=HTTPStatus.UNAUTHORIZED,
            )
            return

        self._record_login_attempt(email, True)
        token, csrf_token = self._create_admin_session(row['id'])
        self._audit_admin(
            'admin_login',
            success=True,
            admin={'id': row['id'], 'email': row['email']},
            actor_email=row['email'],
            details={'reason': 'success'},
        )
        self._json(
            {
                'ok': True,
                'loggedIn': True,
                'admin': {'id': row['id'], 'email': row['email']},
                'csrfToken': csrf_token,
            },
            extra_headers={
                'Set-Cookie': (
                    f'{ADMIN_SESSION_COOKIE}={token}; {self._cookie_attrs()}; '
                    f'Max-Age={ADMIN_SESSION_TTL_SECONDS}'
                )
            },
        )

    def _post_admin_auth_logout(self):
        admin = self._current_admin()
        if admin and not self._require_admin_api(require_csrf=True):
            return
        if admin:
            self._audit_admin('admin_logout', success=True, admin=admin, details={'reason': 'manual'})
        self._clear_admin_session()
        self._json(
            {'ok': True, 'loggedIn': False},
            extra_headers={
                'Set-Cookie': (
                    f'{ADMIN_SESSION_COOKIE}=; {self._cookie_attrs()}; Max-Age=0'
                )
            },
        )

    def _send_admin_reset_email(self, target_email, token):
        reset_url = f"{self._base_url()}/admin-reset.html?token={quote_plus(token)}"
        email_message = EmailMessage()
        email_message['Subject'] = 'whatsnominated admin password reset'
        email_message['From'] = CONTACT_FROM_EMAIL
        email_message['To'] = target_email
        email_message.set_content(
            '\n'.join(
                [
                    'Password reset requested for whatsnominated admin.',
                    '',
                    f'Account name: {target_email}',
                    f'Reset link: {reset_url}',
                    '',
                    'If you did not request this, you can ignore this email.',
                ]
            )
        )
        self._smtp_send_message(email_message)

    def _post_admin_auth_request_reset(self, body):
        email = (body.get('email') or '').strip().lower()
        if not email:
            self._audit_admin(
                'admin_password_reset_request',
                success=False,
                actor_email=email,
                details={'reason': 'missing_email'},
            )
            self._json({'ok': False, 'error': 'Email is required.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if self._is_reset_rate_limited(email):
            self._audit_admin(
                'admin_password_reset_request',
                success=False,
                actor_email=email,
                details={'reason': 'rate_limited'},
            )
            self._json(
                {'ok': False, 'error': 'Too many reset requests. Try again later.'},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
            return

        conn = connect()
        row = conn.execute(
            'SELECT id, email FROM admin_users WHERE lower(email) = ?',
            (email,),
        ).fetchone()
        sent = False
        if row:
            token = secrets.token_urlsafe(48)
            token_hash = self._token_hash(token)
            conn.execute(
                '''
                INSERT INTO admin_password_resets(token_hash, user_id, expires_at)
                VALUES(?, ?, datetime('now', '+60 minutes'))
                ''',
                (token_hash, row['id']),
            )
            conn.commit()
            try:
                self._send_admin_reset_email(row['email'], token)
                sent = True
            except Exception:
                pass
        conn.close()
        self._audit_admin(
            'admin_password_reset_request',
            success=True,
            actor_email=email,
            details={'accountFound': bool(row), 'emailSent': bool(sent)},
        )

        self._json(
            {
                'ok': True,
                'message': 'If the account exists, a reset email has been sent.',
            }
        )

    def _post_admin_auth_reset(self, body):
        token = (body.get('token') or '').strip()
        password = body.get('password') or ''
        if not token:
            self._audit_admin(
                'admin_password_reset_submit',
                success=False,
                details={'reason': 'missing_token'},
            )
            self._json({'ok': False, 'error': 'Reset token is required.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if len(password) < 10:
            self._audit_admin(
                'admin_password_reset_submit',
                success=False,
                details={'reason': 'password_too_short'},
            )
            self._json(
                {'ok': False, 'error': 'Password must be at least 10 characters.'},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        conn = connect()
        token_hash = self._token_hash(token)
        reset_row = conn.execute(
            '''
            SELECT token_hash, user_id
            FROM admin_password_resets
            WHERE token_hash = ? AND used_at IS NULL AND datetime(expires_at) > datetime('now')
            ''',
            (token_hash,),
        ).fetchone()
        if not reset_row:
            conn.close()
            self._audit_admin(
                'admin_password_reset_submit',
                success=False,
                details={'reason': 'invalid_or_expired_token'},
            )
            self._json({'ok': False, 'error': 'Invalid or expired reset token.'}, status=HTTPStatus.BAD_REQUEST)
            return

        password_hash = self._password_hash(password)
        conn.execute(
            '''
            UPDATE admin_users
            SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (password_hash, reset_row['user_id']),
        )
        conn.execute(
            '''
            UPDATE admin_password_resets
            SET used_at = CURRENT_TIMESTAMP
            WHERE token_hash = ?
            ''',
            (token_hash,),
        )
        conn.execute('DELETE FROM admin_sessions WHERE user_id = ?', (reset_row['user_id'],))
        conn.commit()
        admin_row = conn.execute(
            'SELECT id, email FROM admin_users WHERE id = ?',
            (reset_row['user_id'],),
        ).fetchone()
        conn.close()

        new_token, csrf_token = self._create_admin_session(reset_row['user_id'])
        self._audit_admin(
            'admin_password_reset_submit',
            success=True,
            admin=(dict(admin_row) if admin_row else None),
            actor_email=(admin_row['email'] if admin_row else ''),
            details={'reason': 'success'},
        )
        self._json(
            {'ok': True, 'message': 'Password reset complete.', 'csrfToken': csrf_token},
            extra_headers={
                'Set-Cookie': (
                    f'{ADMIN_SESSION_COOKIE}={new_token}; {self._cookie_attrs()}; '
                    f'Max-Age={ADMIN_SESSION_TTL_SECONDS}'
                )
            },
        )

    def _get_years(self):
        conn = connect()
        rows = conn.execute('SELECT year, label FROM years ORDER BY year DESC').fetchall()
        conn.close()
        self._json({'years': [dict(row) for row in rows]})

    def _get_pools(self, year=None):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            pools = list_pools_for_member(conn, user['id'], year=year)
            self._json({'ok': True, 'pools': pools})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            pool = get_pool_for_member(conn, pool_id, user['id'])
            self._json({'ok': True, 'pool': pool})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_members(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            members = list_pool_members(conn, pool_id, user['id'])
            self._json({'ok': True, 'members': members})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_invites(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            invites = list_pool_invites(conn, pool_id, user['id'])
            self._json({'ok': True, 'invites': invites})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_global_picks_api(self, year):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            picks = get_global_picks(conn, user['id'], year)
            self._json({'ok': True, **picks})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _put_global_pick_api(self, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        year_raw = body.get('year')
        if year_raw in (None, ''):
            self._json({'ok': False, 'error': 'year is required.'}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            self._json({'ok': False, 'error': 'Invalid year.'}, status=HTTPStatus.BAD_REQUEST)
            return
        conn = connect()
        try:
            picks = upsert_global_pick(
                conn,
                user_id=user['id'],
                year=year,
                category_id=body.get('categoryId'),
                category_name=body.get('categoryName', ''),
                film_id=body.get('filmId', ''),
            )
            self._json({'ok': True, **picks})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_picks(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            picks = get_pool_effective_picks(conn, pool_id, user['id'])
            self._json({'ok': True, **picks})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _put_pool_pick_api(self, pool_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            picks = upsert_pool_override_pick(
                conn,
                pool_id=pool_id,
                user_id=user['id'],
                category_id=body.get('categoryId'),
                category_name=body.get('categoryName', ''),
                film_id=body.get('filmId', ''),
            )
            self._json({'ok': True, **picks})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_submission_status(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            status = get_pool_submission_status(conn, pool_id, user['id'])
            self._json({'ok': True, **status})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool_submit(self, pool_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            result = submit_pool_ballot(
                conn,
                pool_id=pool_id,
                user_id=user['id'],
                tiebreaker_answer=body.get('tiebreakerAnswer', ''),
            )
            self._json(result, status=HTTPStatus.CREATED)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_leaderboard_api(self, pool_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            payload = get_pool_leaderboard(conn, pool_id, user['id'])
            self._json({'ok': True, **payload})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_results_api(self, pool_id, target_user_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            payload = get_pool_results(
                conn,
                pool_id=pool_id,
                requester_user_id=user['id'],
                target_user_id=(target_user_id or ''),
            )
            self._json({'ok': True, **payload})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_pool_public_api(self, pool_id):
        conn = connect()
        try:
            payload = get_pool_public_leaderboard(conn, pool_id)
            self._json({'ok': True, **payload})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool(self, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            pool = create_pool(
                conn,
                owner_user_id=user['id'],
                name=body.get('name'),
                description=body.get('description', ''),
                scoring_mode=body.get('scoringMode', 'standard'),
                entry_mode=body.get('entryMode', 'none'),
                entry_fee_cents=body.get('entryFeeCents'),
                currency=body.get('currency', 'USD'),
                payment_required_to_score=body.get('paymentRequiredToScore', True),
                allow_pool_overrides=body.get('allowPoolOverrides', True),
                tiebreaker_question=body.get('tiebreakerQuestion', ''),
                invite_policy=body.get('invitePolicy', 'both'),
                owner_display_name=body.get('ownerDisplayName', ''),
            )
            self._json({'ok': True, 'pool': pool}, status=HTTPStatus.CREATED)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool_invite_email(self, pool_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            invite = create_pool_invite(
                conn,
                pool_id=pool_id,
                owner_user_id=user['id'],
                invite_type='email',
                email=body.get('email', ''),
                max_uses=body.get('maxUses'),
                expires_at=body.get('expiresAt'),
            )
            self._json({'ok': True, 'invite': invite}, status=HTTPStatus.CREATED)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool_invite_link(self, pool_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            invite = create_pool_invite(
                conn,
                pool_id=pool_id,
                owner_user_id=user['id'],
                invite_type='share_link',
                max_uses=body.get('maxUses'),
                expires_at=body.get('expiresAt'),
            )
            self._json({'ok': True, 'invite': invite}, status=HTTPStatus.CREATED)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool_invite_accept(self, token, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        if self._is_invite_accept_rate_limited(user_id=user['id']):
            self._json(
                {'ok': False, 'error': 'Too many invite attempts. Try again later.'},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        conn = connect()
        try:
            pool = accept_pool_invite(
                conn,
                raw_token=token,
                user_id=user['id'],
                display_name=body.get('displayName', ''),
            )
            self._json({'ok': True, 'pool': pool})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _post_pool_invite_revoke(self, pool_id, invite_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            result = revoke_pool_invite(
                conn,
                pool_id=pool_id,
                invite_id=invite_id,
                owner_user_id=user['id'],
            )
            self._json(result)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _patch_pool_member_display_name(self, pool_id, target_user_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            members = update_member_display_name(
                conn,
                pool_id=pool_id,
                target_user_id=target_user_id,
                actor_user_id=user['id'],
                display_name=body.get('displayName', ''),
            )
            self._json({'ok': True, 'members': members})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _delete_pool_member(self, pool_id, target_user_id):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        conn = connect()
        try:
            result = remove_pool_member(
                conn,
                pool_id=pool_id,
                target_user_id=target_user_id,
                owner_user_id=user['id'],
            )
            self._json(result)
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _patch_pool(self, pool_id, body):
        user = self._current_user()
        if not user:
            self._json({'ok': False, 'error': 'Login required.'}, status=HTTPStatus.UNAUTHORIZED)
            return
        updates = {}
        field_map = {
            'name': 'name',
            'description': 'description',
            'scoringMode': 'scoring_mode',
            'entryMode': 'entry_mode',
            'entryFeeCents': 'entry_fee_cents',
            'currency': 'currency',
            'paymentRequiredToScore': 'payment_required_to_score',
            'allowPoolOverrides': 'allow_pool_overrides',
            'tiebreakerQuestion': 'tiebreaker_question',
            'invitePolicy': 'invite_policy',
        }
        for key, repo_key in field_map.items():
            if key in body:
                updates[repo_key] = body.get(key)

        conn = connect()
        try:
            pool = update_pool(conn, pool_id, user['id'], updates)
            self._json({'ok': True, 'pool': pool})
        except Exception as error:
            self._pool_error_json(error)
        finally:
            conn.close()

    def _get_admin_pools_troubleshoot(self, query):
        admin = self._current_admin()
        pool_id = (query.get('poolId', [''])[0] or '').strip()
        user_email = (query.get('userEmail', [''])[0] or '').strip().lower()
        year_value = (query.get('year', [''])[0] or '').strip()
        limit_value = (query.get('limit', ['25'])[0] or '25').strip()
        try:
            limit = max(1, min(100, int(limit_value)))
        except ValueError:
            limit = 25

        conn = connect()
        try:
            user_id_filter = ''
            if user_email:
                row = conn.execute(
                    'SELECT id FROM users WHERE lower(email) = ?',
                    (user_email,),
                ).fetchone()
                if row:
                    user_id_filter = row['id']

            sql = '''
                SELECT
                  p.id AS poolId,
                  p.year AS year,
                  p.name AS name,
                  p.status AS status,
                  p.resolution_state AS resolutionState,
                  p.entry_mode AS entryMode,
                  p.payment_required_to_score AS paymentRequiredToScore,
                  p.allow_pool_overrides AS allowPoolOverrides,
                  p.owner_user_id AS ownerUserId,
                  ou.email AS ownerEmail,
                  COALESCE(member_stats.memberCount, 0) AS memberCount,
                  COALESCE(sub_stats.submissionCount, 0) AS submissionCount,
                  COALESCE(pay_stats.exceptionCount, 0) AS paymentExceptionCount,
                  p.created_at AS createdAt,
                  p.updated_at AS updatedAt
                FROM pools p
                LEFT JOIN users ou ON ou.id = p.owner_user_id
                LEFT JOIN (
                  SELECT pool_id, COUNT(*) AS memberCount
                  FROM pool_members
                  GROUP BY pool_id
                ) member_stats ON member_stats.pool_id = p.id
                LEFT JOIN (
                  SELECT pool_id, COUNT(*) AS submissionCount
                  FROM pool_submissions
                  GROUP BY pool_id
                ) sub_stats ON sub_stats.pool_id = p.id
                LEFT JOIN (
                  SELECT pool_id, COUNT(*) AS exceptionCount
                  FROM pool_payments
                  WHERE status IN ('pending', 'self_reported', 'rejected')
                  GROUP BY pool_id
                ) pay_stats ON pay_stats.pool_id = p.id
                WHERE 1 = 1
            '''
            params = []
            if pool_id:
                sql += ' AND p.id = ?'
                params.append(pool_id)
            if year_value:
                try:
                    year = int(year_value)
                    sql += ' AND p.year = ?'
                    params.append(year)
                except ValueError:
                    pass
            if user_id_filter:
                sql += '''
                  AND (
                    p.owner_user_id = ?
                    OR EXISTS(
                      SELECT 1
                      FROM pool_members pmf
                      WHERE pmf.pool_id = p.id AND pmf.user_id = ?
                    )
                  )
                '''
                params.extend([user_id_filter, user_id_filter])
            elif user_email:
                sql += ' AND 1 = 0'

            sql += ' ORDER BY p.updated_at DESC, p.created_at DESC LIMIT ?'
            params.append(limit)

            rows = [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
            self._audit_admin(
                'admin_pool_troubleshoot_search',
                success=True,
                admin=admin,
                details={'poolId': pool_id, 'userEmail': user_email, 'year': year_value, 'rows': len(rows)},
            )
            self._json({'ok': True, 'pools': rows})
        except Exception as error:
            self._audit_admin(
                'admin_pool_troubleshoot_search',
                success=False,
                admin=admin,
                details={'poolId': pool_id, 'userEmail': user_email, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Unable to load pool troubleshooting results.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _get_admin_pool_troubleshoot_detail(self, pool_id):
        admin = self._current_admin()
        conn = connect()
        try:
            pool = conn.execute(
                '''
                SELECT
                  p.id AS poolId,
                  p.year AS year,
                  p.name AS name,
                  p.description AS description,
                  p.scoring_mode AS scoringMode,
                  p.entry_mode AS entryMode,
                  p.entry_fee_cents AS entryFeeCents,
                  p.currency AS currency,
                  p.payment_required_to_score AS paymentRequiredToScore,
                  p.allow_pool_overrides AS allowPoolOverrides,
                  p.tiebreaker_question AS tiebreakerQuestion,
                  p.invite_policy AS invitePolicy,
                  p.status AS status,
                  p.resolution_state AS resolutionState,
                  p.owner_user_id AS ownerUserId,
                  ou.email AS ownerEmail,
                  p.created_at AS createdAt,
                  p.updated_at AS updatedAt
                FROM pools p
                LEFT JOIN users ou ON ou.id = p.owner_user_id
                WHERE p.id = ?
                ''',
                (pool_id,),
            ).fetchone()
            if not pool:
                self._json({'ok': False, 'error': 'Pool not found.'}, status=HTTPStatus.NOT_FOUND)
                return

            members = [
                dict(row) for row in conn.execute(
                    '''
                    SELECT
                      pm.user_id AS userId,
                      pm.role AS role,
                      pm.display_name AS displayName,
                      pm.joined_at AS joinedAt,
                      u.email AS email
                    FROM pool_members pm
                    LEFT JOIN users u ON u.id = pm.user_id
                    WHERE pm.pool_id = ?
                    ORDER BY CASE WHEN pm.role = 'owner' THEN 0 ELSE 1 END, lower(pm.display_name) ASC
                    ''',
                    (pool_id,),
                ).fetchall()
            ]

            invites = [
                dict(row) for row in conn.execute(
                    '''
                    SELECT
                      pi.id AS inviteId,
                      pi.invite_type AS inviteType,
                      pi.email AS email,
                      pi.max_uses AS maxUses,
                      pi.uses_count AS usesCount,
                      pi.expires_at AS expiresAt,
                      pi.revoked_at AS revokedAt,
                      pi.created_at AS createdAt,
                      u.email AS createdByEmail
                    FROM pool_invites pi
                    LEFT JOIN users u ON u.id = pi.created_by_user_id
                    WHERE pi.pool_id = ?
                    ORDER BY pi.created_at DESC
                    ''',
                    (pool_id,),
                ).fetchall()
            ]

            submissions = [
                dict(row) for row in conn.execute(
                    '''
                    SELECT
                      ps.id AS submissionId,
                      ps.user_id AS userId,
                      pm.display_name AS displayName,
                      u.email AS email,
                      ps.submitted_at AS submittedAt,
                      ps.scoring_mode_snapshot AS scoringModeSnapshot,
                      ps.payment_required_to_score_snapshot AS paymentRequiredToScoreSnapshot,
                      COALESCE(pick_count.pickCount, 0) AS pickCount
                    FROM pool_submissions ps
                    LEFT JOIN users u ON u.id = ps.user_id
                    LEFT JOIN pool_members pm ON pm.pool_id = ps.pool_id AND pm.user_id = ps.user_id
                    LEFT JOIN (
                      SELECT submission_id, COUNT(*) AS pickCount
                      FROM pool_submission_picks
                      GROUP BY submission_id
                    ) pick_count ON pick_count.submission_id = ps.id
                    WHERE ps.pool_id = ?
                    ORDER BY ps.submitted_at ASC
                    ''',
                    (pool_id,),
                ).fetchall()
            ]

            payments = [
                dict(row) for row in conn.execute(
                    '''
                    SELECT
                      pp.id AS paymentId,
                      pp.user_id AS userId,
                      pm.display_name AS displayName,
                      u.email AS email,
                      pp.amount_cents AS amountCents,
                      pp.currency AS currency,
                      pp.status AS status,
                      pp.proof_file_url AS proofFileUrl,
                      pp.proof_note AS proofNote,
                      pp.reported_at AS reportedAt,
                      pp.confirmed_at AS confirmedAt,
                      pp.rejection_reason AS rejectionReason,
                      pp.created_at AS createdAt
                    FROM pool_payments pp
                    LEFT JOIN users u ON u.id = pp.user_id
                    LEFT JOIN pool_members pm ON pm.pool_id = pp.pool_id AND pm.user_id = pp.user_id
                    WHERE pp.pool_id = ?
                    ORDER BY pp.created_at DESC
                    ''',
                    (pool_id,),
                ).fetchall()
            ]

            scores = [
                dict(row) for row in conn.execute(
                    '''
                    SELECT
                      ps.user_id AS userId,
                      pm.display_name AS displayName,
                      u.email AS email,
                      ps.total_points AS totalPoints,
                      ps.correct_count AS correctCount,
                      ps.rank_position AS rankPosition,
                      ps.tied_count AS tiedCount,
                      ps.updated_at AS updatedAt
                    FROM pool_scores ps
                    LEFT JOIN users u ON u.id = ps.user_id
                    LEFT JOIN pool_members pm ON pm.pool_id = ps.pool_id AND pm.user_id = ps.user_id
                    WHERE ps.pool_id = ?
                    ORDER BY ps.rank_position ASC, lower(pm.display_name) ASC
                    ''',
                    (pool_id,),
                ).fetchall()
            ]

            submitted_user_ids = {row['userId'] for row in submissions}
            missing_submissions = [
                {'userId': row['userId'], 'displayName': row['displayName'], 'email': row['email']}
                for row in members
                if row['userId'] not in submitted_user_ids
            ]
            payment_exceptions = [
                row for row in payments
                if row['status'] in {'pending', 'self_reported', 'rejected'}
            ]

            self._audit_admin(
                'admin_pool_troubleshoot_detail',
                success=True,
                admin=admin,
                details={
                    'poolId': pool_id,
                    'members': len(members),
                    'submissions': len(submissions),
                    'paymentExceptions': len(payment_exceptions),
                },
            )
            self._json(
                {
                    'ok': True,
                    'pool': dict(pool),
                    'members': members,
                    'invites': invites,
                    'submissions': submissions,
                    'payments': payments,
                    'scores': scores,
                    'issues': {
                        'missingSubmissions': missing_submissions,
                        'paymentExceptions': payment_exceptions,
                    },
                }
            )
        except Exception as error:
            self._audit_admin(
                'admin_pool_troubleshoot_detail',
                success=False,
                admin=admin,
                details={'poolId': pool_id, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Unable to load pool detail.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _put_admin_pool_payment_status(self, pool_id, body):
        admin = self._current_admin()
        user_id = (body.get('userId') or '').strip()
        status = (body.get('status') or '').strip().lower()
        rejection_reason = (body.get('rejectionReason') or '').strip()
        valid_statuses = {'pending', 'self_reported', 'confirmed', 'rejected', 'waived'}
        if not user_id:
            self._json({'ok': False, 'error': 'userId is required.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if status not in valid_statuses:
            self._json({'ok': False, 'error': 'Invalid payment status.'}, status=HTTPStatus.BAD_REQUEST)
            return

        conn = connect()
        try:
            pool = conn.execute(
                'SELECT id, entry_fee_cents, currency FROM pools WHERE id = ?',
                (pool_id,),
            ).fetchone()
            if not pool:
                self._json({'ok': False, 'error': 'Pool not found.'}, status=HTTPStatus.NOT_FOUND)
                return
            member = conn.execute(
                'SELECT 1 FROM pool_members WHERE pool_id = ? AND user_id = ?',
                (pool_id, user_id),
            ).fetchone()
            if not member:
                self._json({'ok': False, 'error': 'Member not found in pool.'}, status=HTTPStatus.NOT_FOUND)
                return

            payment = conn.execute(
                'SELECT id, amount_cents, currency FROM pool_payments WHERE pool_id = ? AND user_id = ?',
                (pool_id, user_id),
            ).fetchone()
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            if payment:
                conn.execute(
                    '''
                    UPDATE pool_payments
                    SET
                      status = ?,
                      rejection_reason = ?,
                      confirmed_at = CASE WHEN ? IN ('confirmed', 'waived') THEN ? ELSE NULL END
                    WHERE pool_id = ? AND user_id = ?
                    ''',
                    (status, rejection_reason, status, now, pool_id, user_id),
                )
            else:
                payment_id = secrets.token_hex(16)
                amount = pool['entry_fee_cents'] if pool['entry_fee_cents'] is not None else 0
                currency = (pool['currency'] or 'USD').upper()
                conn.execute(
                    '''
                    INSERT INTO pool_payments(
                      id, pool_id, user_id, amount_cents, currency, status, rejection_reason, confirmed_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IN ('confirmed', 'waived') THEN ? ELSE NULL END)
                    ''',
                    (payment_id, pool_id, user_id, amount, currency, status, rejection_reason, status, now),
                )

            recompute_pool_scores(conn, pool_id)
            self._audit_admin(
                'admin_pool_payment_update',
                success=True,
                admin=admin,
                details={'poolId': pool_id, 'userId': user_id, 'status': status},
            )
            self._json({'ok': True})
        except Exception as error:
            self._audit_admin(
                'admin_pool_payment_update',
                success=False,
                admin=admin,
                details={'poolId': pool_id, 'userId': user_id, 'status': status, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Unable to update payment status.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _post_admin_pool_recompute_scores(self, pool_id):
        admin = self._current_admin()
        conn = connect()
        try:
            exists = conn.execute('SELECT 1 FROM pools WHERE id = ?', (pool_id,)).fetchone()
            if not exists:
                self._json({'ok': False, 'error': 'Pool not found.'}, status=HTTPStatus.NOT_FOUND)
                return
            recompute_pool_scores(conn, pool_id)
            self._audit_admin(
                'admin_pool_recompute_scores',
                success=True,
                admin=admin,
                details={'poolId': pool_id},
            )
            self._json({'ok': True})
        except Exception as error:
            self._audit_admin(
                'admin_pool_recompute_scores',
                success=False,
                admin=admin,
                details={'poolId': pool_id, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Unable to recompute pool scores.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _get_admin_dashboard(self, year):
        admin = self._current_admin()
        conn = connect()
        unique_users_row = conn.execute(
            'SELECT COUNT(DISTINCT user_key) AS count FROM user_picks WHERE year = ?',
            (year,),
        ).fetchone()
        total_picks_row = conn.execute(
            'SELECT COUNT(*) AS count FROM user_picks WHERE year = ?',
            (year,),
        ).fetchone()
        winner_categories_row = conn.execute(
            'SELECT COUNT(*) AS count FROM category_winners WHERE year = ?',
            (year,),
        ).fetchone()
        user_scores_row = conn.execute(
            '''
            WITH winner_categories AS (
              SELECT category_id, nomination_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.nomination_id = wc.nomination_id THEN 1 ELSE 0 END) AS correct
              FROM user_picks up
              JOIN winner_categories wc ON wc.category_id = up.category_id
              WHERE up.year = ?
              GROUP BY up.user_key
            )
            SELECT COUNT(*) AS count
            FROM user_scores
            ''',
            (year, year),
        ).fetchone()
        conn.close()

        payload = {
            'year': year,
            'uniqueUsers': unique_users_row['count'] if unique_users_row else 0,
            'usersCompared': user_scores_row['count'] if user_scores_row else 0,
            'totalPicks': total_picks_row['count'] if total_picks_row else 0,
            'winnerCategories': winner_categories_row['count'] if winner_categories_row else 0,
        }
        self._audit_admin('admin_dashboard_view', success=True, admin=admin, details={'year': year})
        self._json(payload)

    def _get_admin_odds_status(self, year):
        admin = self._current_admin()
        conn = connect()
        try:
            payload = get_odds_status(conn, int(year))
            self._audit_admin(
                'admin_odds_status_view',
                success=True,
                admin=admin,
                details={'year': int(year)},
            )
            self._json({'ok': True, **payload})
        except Exception as error:
            self._audit_admin(
                'admin_odds_status_view',
                success=False,
                admin=admin,
                details={'year': int(year), 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Unable to load odds status.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _post_admin_odds_sync(self, body):
        admin = self._current_admin()
        year_raw = body.get('year')
        source = str(body.get('source') or 'external_api').strip().lower()
        rows = body.get('rows')
        try:
            year = int(year_raw) if year_raw not in (None, '') else 2026
        except (TypeError, ValueError):
            self._json({'ok': False, 'error': 'Invalid year.'}, status=HTTPStatus.BAD_REQUEST)
            return

        conn = connect()
        try:
            if isinstance(rows, list):
                result = sync_external_odds(conn, year=year, rows=rows, source=source)
            else:
                result = {
                    'ok': False,
                    'year': year,
                    'error': 'No external odds provider is configured. Provide structured rows or use manual import.',
                }
            self._audit_admin(
                'admin_odds_sync',
                success=bool(result.get('ok')),
                admin=admin,
                details={
                    'year': year,
                    'source': source,
                    'status': result.get('status'),
                    'mappedCount': result.get('mappedCount', 0),
                    'unmappedCount': result.get('unmappedCount', 0),
                    'error': result.get('error', ''),
                },
            )
            status = HTTPStatus.OK if result.get('ok') else HTTPStatus.BAD_GATEWAY
            self._json(result, status=status)
        except Exception as error:
            self._audit_admin(
                'admin_odds_sync',
                success=False,
                admin=admin,
                details={'year': year, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Odds sync failed.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _post_admin_odds_import(self, body):
        admin = self._current_admin()
        year_raw = body.get('year')
        text = body.get('text')
        try:
            year = int(year_raw) if year_raw not in (None, '') else 2026
        except (TypeError, ValueError):
            self._json({'ok': False, 'error': 'Invalid year.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(text, str) or not text.strip():
            self._json({'ok': False, 'error': 'Missing import text.'}, status=HTTPStatus.BAD_REQUEST)
            return
        if len(text) > 500000:
            self._json({'ok': False, 'error': 'Import text too large.'}, status=HTTPStatus.BAD_REQUEST)
            return

        conn = connect()
        try:
            result = import_manual_odds(conn, year=year, text=text)
            self._audit_admin(
                'admin_odds_import',
                success=bool(result.get('ok')),
                admin=admin,
                details={
                    'year': year,
                    'status': result.get('status'),
                    'rawCount': result.get('rawCount', 0),
                    'mappedCount': result.get('mappedCount', 0),
                    'unmappedCount': result.get('unmappedCount', 0),
                    'error': result.get('error', ''),
                },
            )
            status = HTTPStatus.OK if result.get('ok') else HTTPStatus.BAD_REQUEST
            self._json(result, status=status)
        except Exception as error:
            self._audit_admin(
                'admin_odds_import',
                success=False,
                admin=admin,
                details={'year': year, 'error': str(error)},
            )
            self._json({'ok': False, 'error': 'Odds import failed.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            conn.close()

    def _get_admin_audit_logs(self, query):
        admin = self._current_admin()
        action = (query.get('action', [''])[0] or '').strip()
        success_raw = (query.get('success', ['all'])[0] or 'all').strip().lower()
        limit_raw = (query.get('limit', ['100'])[0] or '100').strip()
        try:
            limit = max(1, min(int(limit_raw), 500))
        except ValueError:
            limit = 100

        clauses = []
        params = []
        if action:
            clauses.append('action = ?')
            params.append(action)
        if success_raw in {'0', '1'}:
            clauses.append('success = ?')
            params.append(int(success_raw))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''

        conn = connect()
        rows = conn.execute(
            f'''
            SELECT id, admin_user_id, action, success, actor_email, request_ip, user_agent, details, created_at
            FROM admin_audit_logs
            {where}
            ORDER BY id DESC
            LIMIT ?
            ''',
            (*params, limit),
        ).fetchall()
        actions = conn.execute(
            '''
            SELECT action, COUNT(*) AS count
            FROM admin_audit_logs
            GROUP BY action
            ORDER BY action
            '''
        ).fetchall()
        conn.close()

        logs = []
        for row in rows:
            details_obj = {}
            try:
                details_obj = json.loads(row['details'] or '{}')
            except Exception:
                details_obj = {'raw': row['details'] or ''}
            logs.append(
                {
                    'id': row['id'],
                    'adminUserId': row['admin_user_id'],
                    'action': row['action'],
                    'success': bool(row['success']),
                    'actorEmail': row['actor_email'] or '',
                    'requestIp': row['request_ip'] or '',
                    'userAgent': row['user_agent'] or '',
                    'details': details_obj,
                    'createdAt': row['created_at'],
                }
            )

        self._audit_admin(
            'admin_audit_logs_view',
            success=True,
            admin=admin,
            details={'limit': limit, 'action': action, 'success': success_raw},
        )
        self._json(
            {
                'logs': logs,
                'actions': [dict(row) for row in actions],
                'filters': {'action': action, 'success': success_raw, 'limit': limit},
            }
        )

    def _get_nominees(self, year, category):
        conn = connect()
        categories = conn.execute(
            'SELECT name, year_started, year_ended FROM categories WHERE year = ? ORDER BY id',
            (year,),
        ).fetchall()

        if category == '__ALL__':
            film_rows = conn.execute(
                '''
                SELECT f.id, f.title, wl.url AS override_url,
                       wlbl.free_to_watch AS free_to_watch,
                       sp.url AS scraped_poster_url, ap.url AS admin_poster_url
                FROM film_years fy
                JOIN films f ON f.id = fy.film_id
                LEFT JOIN admin_watch_links wl ON wl.year = fy.year AND wl.film_id = fy.film_id
                LEFT JOIN admin_watch_labels wlbl ON wlbl.year = fy.year AND wlbl.film_id = fy.film_id
                LEFT JOIN scraped_posters sp ON sp.year = fy.year AND sp.film_id = fy.film_id
                LEFT JOIN admin_posters ap ON ap.year = fy.year AND ap.film_id = fy.film_id
                WHERE fy.year = ?
                ORDER BY f.title
                ''',
                (year,),
            ).fetchall()
        else:
            film_rows = conn.execute(
                '''
                SELECT DISTINCT f.id, f.title, wl.url AS override_url,
                       wlbl.free_to_watch AS free_to_watch,
                       sp.url AS scraped_poster_url, ap.url AS admin_poster_url
                FROM nominations n
                JOIN categories c ON c.id = n.category_id
                JOIN films f ON f.id = n.film_id
                JOIN film_years fy ON fy.year = n.year AND fy.film_id = n.film_id
                LEFT JOIN admin_watch_links wl ON wl.year = fy.year AND wl.film_id = fy.film_id
                LEFT JOIN admin_watch_labels wlbl ON wlbl.year = fy.year AND wlbl.film_id = fy.film_id
                LEFT JOIN scraped_posters sp ON sp.year = fy.year AND sp.film_id = fy.film_id
                LEFT JOIN admin_posters ap ON ap.year = fy.year AND ap.film_id = fy.film_id
                WHERE n.year = ? AND c.name = ?
                ORDER BY f.title
                ''',
                (year, category),
            ).fetchall()

        nominations = conn.execute(
            '''
            SELECT c.name AS category, n.id AS nominationId, n.film_id AS filmId, n.nominee
            FROM nominations n
            JOIN categories c ON c.id = n.category_id
            WHERE n.year = ?
            ORDER BY n.id
            ''',
            (year,),
        ).fetchall()

        winners = conn.execute(
            '''
            SELECT c.name AS category, cw.nomination_id AS nominationId, cw.film_id AS filmId
            FROM category_winners cw
            JOIN categories c ON c.id = cw.category_id
            WHERE cw.year = ?
            ''',
            (year,),
        ).fetchall()

        banner = conn.execute(
            'SELECT enabled, text FROM admin_banners WHERE year = ?',
            (year,),
        ).fetchone()
        event_mode = conn.execute(
            'SELECT enabled FROM admin_event_modes WHERE year = ?',
            (year,),
        ).fetchone()
        voting_lock = conn.execute(
            'SELECT enabled FROM admin_voting_locks WHERE year = ?',
            (year,),
        ).fetchone()

        conn.close()

        films = []
        for row in film_rows:
            films.append(
                {
                    'id': row['id'],
                    'title': row['title'],
                    'whereToWatchUrl': row['override_url'],
                    'whereToWatchOverrideUrl': row['override_url'],
                    'freeToWatch': bool(row['free_to_watch']),
                    'posterUrl': row['admin_poster_url'] or row['scraped_poster_url'],
                    'posterOverrideUrl': row['admin_poster_url'],
                }
            )

        payload = {
            'year': year,
            'categories': [
                {
                    'name': c['name'],
                    'yearStarted': c['year_started'],
                    'yearEnded': c['year_ended'],
                }
                for c in categories
            ],
            'films': films,
            'nominations': [dict(row) for row in nominations],
            'winnersByCategory': {row['category']: row['nominationId'] for row in winners},
            'eventMode': bool(event_mode['enabled']) if event_mode else False,
            'votingLocked': bool(voting_lock['enabled']) if voting_lock else False,
            'banner': {
                'enabled': bool(banner['enabled']) if banner else True,
                'text': (banner['text'] if banner and banner['text'] else DEFAULT_BANNER_TEXT),
            },
        }
        self._json(payload)

    def _get_user_state(self, year, user_key_hint=''):
        user_key = user_key_hint or DEFAULT_USER_KEY
        conn = connect()
        rows = conn.execute(
            'SELECT film_id FROM user_seen WHERE year = ? AND user_key = ? AND seen = 1',
            (year, user_key),
        ).fetchall()

        picks = conn.execute(
            '''
            SELECT c.name AS category, up.nomination_id AS nominationId, up.film_id AS filmId
            FROM user_picks up
            JOIN categories c ON c.id = up.category_id
            WHERE up.year = ? AND up.user_key = ? AND up.nomination_id IS NOT NULL
            ''',
            (year, user_key),
        ).fetchall()
        unresolved_repick_rows = conn.execute(
            '''
            SELECT c.name AS category
            FROM user_picks up
            JOIN categories c ON c.id = up.category_id
            WHERE up.year = ? AND up.user_key = ? AND up.nomination_id IS NULL
            ORDER BY c.name
            ''',
            (year, user_key),
        ).fetchall()
        user_seen_count = len(rows)

        viewing_vs_others = conn.execute(
            '''
            WITH viewer_scores AS (
              SELECT
                us.user_key AS user_key,
                COUNT(*) AS seen_count
              FROM user_seen us
              WHERE us.year = ? AND us.seen = 1
              GROUP BY us.user_key
            )
            SELECT
              SUM(CASE WHEN seen_count < ? THEN 1 ELSE 0 END) AS beaten,
              COUNT(*) AS total_others
            FROM viewer_scores
            WHERE user_key <> ?
            ''',
            (year, user_seen_count, user_key),
        ).fetchone()
        viewing_beaten = viewing_vs_others['beaten'] if viewing_vs_others else 0
        viewing_total_others = viewing_vs_others['total_others'] if viewing_vs_others else 0
        viewing_better_than_percent = (
            round((viewing_beaten / viewing_total_others) * 100) if viewing_total_others else 0
        )

        viewing_rank_row = conn.execute(
            '''
            WITH viewer_scores AS (
              SELECT
                us.user_key AS user_key,
                COUNT(*) AS seen_count
              FROM user_seen us
              WHERE us.year = ? AND us.seen = 1
              GROUP BY us.user_key
            ),
            current_score AS (
              SELECT COALESCE(
                (SELECT seen_count FROM viewer_scores WHERE user_key = ?),
                0
              ) AS seen_count
            )
            SELECT
              1 + COALESCE(SUM(CASE WHEN vs.seen_count > (SELECT seen_count FROM current_score) THEN 1 ELSE 0 END), 0) AS rank_position,
              COUNT(*) AS ranked_user_count,
              COALESCE(SUM(CASE WHEN vs.seen_count = (SELECT seen_count FROM current_score) THEN 1 ELSE 0 END), 0) AS tied_user_count
            FROM viewer_scores vs
            '''
            ,
            (year, user_key),
        ).fetchone()
        viewing_rank_position = (
            viewing_rank_row['rank_position']
            if viewing_rank_row and viewing_rank_row['ranked_user_count']
            else 1
        )
        viewing_ranked_user_count = viewing_rank_row['ranked_user_count'] if viewing_rank_row else 0
        viewing_tied_user_count = (
            viewing_rank_row['tied_user_count']
            if viewing_rank_row and viewing_rank_row['ranked_user_count']
            else 1
        )

        winner_count_row = conn.execute(
            'SELECT COUNT(*) AS count FROM category_winners WHERE year = ?',
            (year,),
        ).fetchone()
        winner_count = winner_count_row['count'] if winner_count_row else 0

        user_correct_row = conn.execute(
            '''
            SELECT COUNT(*) AS correct
            FROM user_picks up
            JOIN category_winners cw
              ON cw.year = up.year
             AND cw.category_id = up.category_id
             AND cw.nomination_id = up.nomination_id
            WHERE up.year = ? AND up.user_key = ?
            ''',
            (year, user_key),
        ).fetchone()
        user_correct = user_correct_row['correct'] if user_correct_row else 0

        other_scores = conn.execute(
            '''
            WITH winner_categories AS (
              SELECT category_id, nomination_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.nomination_id = wc.nomination_id THEN 1 ELSE 0 END) AS correct
              FROM user_picks up
              JOIN winner_categories wc ON wc.category_id = up.category_id
              WHERE up.year = ?
              GROUP BY up.user_key
            )
            SELECT
              SUM(CASE WHEN correct < ? THEN 1 ELSE 0 END) AS beaten,
              COUNT(*) AS total_others
            FROM user_scores
            WHERE user_key <> ?
            ''',
            (year, year, user_correct, user_key),
        ).fetchone()
        beaten = other_scores['beaten'] if other_scores else 0
        total_others = other_scores['total_others'] if other_scores else 0
        better_than_percent = (
            round((beaten / total_others) * 100) if total_others else 0
        )

        rank_row = conn.execute(
            '''
            WITH winner_categories AS (
              SELECT category_id, nomination_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.nomination_id = wc.nomination_id THEN 1 ELSE 0 END) AS correct
              FROM user_picks up
              JOIN winner_categories wc ON wc.category_id = up.category_id
              WHERE up.year = ?
              GROUP BY up.user_key
            ),
            current_score AS (
              SELECT COALESCE(
                (SELECT correct FROM user_scores WHERE user_key = ?),
                0
              ) AS correct
            )
            SELECT
              1 + COALESCE(SUM(CASE WHEN us.correct > (SELECT correct FROM current_score) THEN 1 ELSE 0 END), 0) AS rank_position,
              COUNT(*) AS ranked_user_count,
              COALESCE(SUM(CASE WHEN us.correct = (SELECT correct FROM current_score) THEN 1 ELSE 0 END), 0) AS tied_user_count
            FROM user_scores us
            ''',
            (year, year, user_key),
        ).fetchone()
        rank_position = rank_row['rank_position'] if rank_row and rank_row['ranked_user_count'] else 1
        ranked_user_count = rank_row['ranked_user_count'] if rank_row else 0
        tied_user_count = rank_row['tied_user_count'] if rank_row and rank_row['ranked_user_count'] else 1

        repick_categories = [row['category'] for row in unresolved_repick_rows]
        supporting_pair = {'Actor in a Supporting Role', 'Actress in a Supporting Role'}
        if any(category in supporting_pair for category in repick_categories):
            repick_categories = [
                'Actor in a Supporting Role',
                'Actress in a Supporting Role',
                *[category for category in repick_categories if category not in supporting_pair],
            ]

        conn.close()
        self._json(
            {
                'seenFilmIds': [row['film_id'] for row in rows],
                'picksByCategory': {row['category']: row['nominationId'] for row in picks},
                'repickCategories': repick_categories,
                'performance': {
                    'viewingBetterThanPercent': viewing_better_than_percent,
                    'viewingComparedUserCount': viewing_total_others,
                    'viewingRankPosition': viewing_rank_position,
                    'viewingRankedUserCount': viewing_ranked_user_count,
                    'viewingTiedUserCount': viewing_tied_user_count,
                    'winnerCategoryCount': winner_count,
                    'userCorrectCount': user_correct,
                    'betterThanPercent': better_than_percent,
                    'comparedUserCount': total_others,
                    'rankPosition': rank_position,
                    'rankedUserCount': ranked_user_count,
                    'tiedUserCount': tied_user_count,
                },
            }
        )

    def _put_user_state(self, body):
        year = int(body.get('year'))
        user_key = body.get('userKey') or DEFAULT_USER_KEY
        film_id = body.get('filmId')
        seen = 1 if body.get('seen') else 0

        conn = connect()
        conn.execute(
            '''
            INSERT INTO user_seen(user_key, year, film_id, seen)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_key, year, film_id) DO UPDATE SET
              seen=excluded.seen,
              updated_at=CURRENT_TIMESTAMP
            ''',
            (user_key, year, film_id, seen),
        )
        conn.commit()
        conn.close()
        self._json({'ok': True})

    def _category_id(self, year, category_name):
        conn = connect()
        row = conn.execute(
            'SELECT id FROM categories WHERE year = ? AND name = ?',
            (year, category_name),
        ).fetchone()
        conn.close()
        return row['id'] if row else None

    def _put_user_pick(self, body):
        year = int(body.get('year'))
        user_key = body.get('userKey') or DEFAULT_USER_KEY
        category_name = body.get('category')
        film_id = body.get('filmId')
        nomination_id = body.get('nominationId')
        picked = bool(body.get('picked'))
        category_id = self._category_id(year, category_name)

        if not category_id:
            self._json({'ok': False, 'error': 'Unknown category'}, status=HTTPStatus.BAD_REQUEST)
            return

        if nomination_id in (None, ''):
            self._json({'ok': False, 'error': 'nominationId is required'}, status=HTTPStatus.BAD_REQUEST)
            return

        conn = connect()
        voting_lock_row = conn.execute(
            'SELECT enabled FROM admin_voting_locks WHERE year = ?',
            (year,),
        ).fetchone()
        if voting_lock_row and voting_lock_row['enabled']:
            conn.close()
            self._json(
                {'ok': False, 'error': 'Voting is locked'},
                status=HTTPStatus.FORBIDDEN,
            )
            return

        nomination_row = conn.execute(
            '''
            SELECT film_id
            FROM nominations
            WHERE id = ? AND year = ? AND category_id = ?
            ''',
            (nomination_id, year, category_id),
        ).fetchone()
        if not nomination_row:
            conn.close()
            self._json(
                {'ok': False, 'error': 'Unknown nominee'},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        film_id = nomination_row['film_id']

        if picked:
            conn.execute(
                '''
                INSERT INTO user_picks(user_key, year, category_id, film_id, nomination_id)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_key, year, category_id) DO UPDATE SET
                  film_id=excluded.film_id,
                  nomination_id=excluded.nomination_id,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (user_key, year, category_id, film_id, nomination_id),
            )
        else:
            conn.execute(
                '''
                DELETE FROM user_picks
                WHERE user_key = ? AND year = ? AND category_id = ? AND nomination_id = ?
                ''',
                (user_key, year, category_id, nomination_id),
            )
        conn.commit()
        conn.close()
        self._json({'ok': True})

    def _get_poster_image(self, year, film_id):
        if not film_id:
            self.send_error(HTTPStatus.BAD_REQUEST, 'filmId is required')
            return

        conn = connect()
        row = conn.execute(
            '''
            SELECT ap.url AS admin_url, sp.url AS scraped_url
            FROM film_years fy
            LEFT JOIN admin_posters ap ON ap.year = fy.year AND ap.film_id = fy.film_id
            LEFT JOIN scraped_posters sp ON sp.year = fy.year AND sp.film_id = fy.film_id
            WHERE fy.year = ? AND fy.film_id = ?
            LIMIT 1
            ''',
            (year, film_id),
        ).fetchone()
        conn.close()

        # Admin override must win immediately so stale cache can't mask overrides.
        admin_url = (row['admin_url'] if row else '') or ''
        admin_url = admin_url.strip()
        if admin_url and urlparse(admin_url).scheme in {'http', 'https'}:
            return self._redirect(admin_url, status=HTTPStatus.TEMPORARY_REDIRECT)

        cache_path = self._poster_cache_path(year, film_id)
        if not cache_path.exists():
            fallback_url = ''
            if row:
                fallback_url = (row['scraped_url'] or '').strip()
            if fallback_url and urlparse(fallback_url).scheme in {'http', 'https'}:
                return self._redirect(fallback_url, status=HTTPStatus.TEMPORARY_REDIRECT)
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = cache_path.read_bytes()
        content_type = mimetypes.guess_type(str(cache_path))[0] or 'image/jpeg'
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(body)

    def _put_admin_where_to_watch(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        film_id = body.get('filmId')
        url = (body.get('url') or '').strip()
        has_free_to_watch = 'freeToWatch' in body
        free_to_watch = 1 if body.get('freeToWatch') else 0

        conn = connect()
        if url:
            conn.execute(
                '''
                INSERT INTO admin_watch_links(year, film_id, url)
                VALUES(?, ?, ?)
                ON CONFLICT(year, film_id) DO UPDATE SET
                  url=excluded.url,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (year, film_id, url),
            )
        else:
            conn.execute(
                'DELETE FROM admin_watch_links WHERE year = ? AND film_id = ?',
                (year, film_id),
            )

        if has_free_to_watch:
            if free_to_watch:
                conn.execute(
                    '''
                    INSERT INTO admin_watch_labels(year, film_id, free_to_watch)
                    VALUES(?, ?, 1)
                    ON CONFLICT(year, film_id) DO UPDATE SET
                      free_to_watch=1,
                      updated_at=CURRENT_TIMESTAMP
                    ''',
                    (year, film_id),
                )
            else:
                conn.execute(
                    'DELETE FROM admin_watch_labels WHERE year = ? AND film_id = ?',
                    (year, film_id),
                )
        conn.commit()
        conn.close()
        self._audit_admin(
            'admin_where_to_watch_update',
            success=True,
            admin=admin,
            details={'year': year, 'filmId': film_id, 'hasUrl': bool(url), 'freeToWatch': bool(free_to_watch)},
        )

        self._json({'ok': True})

    def _put_admin_banner(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        enabled = 1 if body.get('enabled') else 0
        text = (body.get('text') or '').strip()

        conn = connect()
        conn.execute(
            '''
            INSERT INTO admin_banners(year, enabled, text)
            VALUES(?, ?, ?)
            ON CONFLICT(year) DO UPDATE SET
              enabled=excluded.enabled,
              text=excluded.text
            ''',
            (year, enabled, text),
        )
        conn.commit()
        conn.close()
        self._audit_admin(
            'admin_banner_update',
            success=True,
            admin=admin,
            details={'year': year, 'enabled': bool(enabled), 'textLength': len(text)},
        )
        self._json({'ok': True})

    def _put_admin_event_mode(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        enabled = 1 if body.get('enabled') else 0

        conn = connect()
        conn.execute(
            '''
            INSERT INTO admin_event_modes(year, enabled)
            VALUES(?, ?)
            ON CONFLICT(year) DO UPDATE SET
              enabled=excluded.enabled
            ''',
            (year, enabled),
        )
        conn.commit()
        conn.close()
        self._audit_admin(
            'admin_event_mode_update',
            success=True,
            admin=admin,
            details={'year': year, 'enabled': bool(enabled)},
        )
        self._json({'ok': True})

    def _put_admin_voting_lock(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        enabled = 1 if body.get('enabled') else 0

        conn = connect()
        conn.execute(
            '''
            INSERT INTO admin_voting_locks(year, enabled)
            VALUES(?, ?)
            ON CONFLICT(year) DO UPDATE SET
              enabled=excluded.enabled
            ''',
            (year, enabled),
        )
        conn.commit()
        conn.close()
        self._audit_admin(
            'admin_voting_lock_update',
            success=True,
            admin=admin,
            details={'year': year, 'enabled': bool(enabled)},
        )
        self._json({'ok': True})

    def _put_admin_poster(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        film_id = body.get('filmId')
        url = (body.get('url') or '').strip()

        conn = connect()
        if url:
            conn.execute(
                '''
                INSERT INTO admin_posters(year, film_id, url)
                VALUES(?, ?, ?)
                ON CONFLICT(year, film_id) DO UPDATE SET
                  url=excluded.url,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (year, film_id, url),
            )
        else:
            conn.execute(
                'DELETE FROM admin_posters WHERE year = ? AND film_id = ?',
                (year, film_id),
            )
        conn.commit()
        conn.close()

        cache_path = self._poster_cache_path(year, film_id)
        if url:
            try:
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
                with urlopen(req, timeout=12) as response:
                    body_bytes = response.read()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(body_bytes)
            except Exception:
                if cache_path.exists():
                    cache_path.unlink()
        elif cache_path.exists():
            cache_path.unlink()
        self._audit_admin(
            'admin_poster_update',
            success=True,
            admin=admin,
            details={'year': year, 'filmId': film_id, 'hasUrl': bool(url)},
        )

        self._json({'ok': True})

    def _put_admin_winner(self, body):
        admin = self._current_admin()
        year = int(body.get('year'))
        category_name = body.get('category')
        film_id = body.get('filmId')
        nomination_id = body.get('nominationId')
        winner = bool(body.get('winner'))
        category_id = self._category_id(year, category_name)

        if not category_id:
            self._audit_admin(
                'admin_winner_update',
                success=False,
                admin=admin,
                details={'year': year, 'category': category_name, 'filmId': film_id, 'reason': 'unknown_category'},
            )
            self._json({'ok': False, 'error': 'Unknown category'}, status=HTTPStatus.BAD_REQUEST)
            return

        if nomination_id in (None, ''):
            self._json({'ok': False, 'error': 'nominationId is required'}, status=HTTPStatus.BAD_REQUEST)
            return

        conn = connect()
        nomination_row = conn.execute(
            '''
            SELECT film_id
            FROM nominations
            WHERE id = ? AND year = ? AND category_id = ?
            ''',
            (nomination_id, year, category_id),
        ).fetchone()
        if not nomination_row:
            conn.close()
            self._json({'ok': False, 'error': 'Unknown nominee'}, status=HTTPStatus.BAD_REQUEST)
            return
        film_id = nomination_row['film_id']
        if winner:
            conn.execute(
                '''
                INSERT INTO category_winners(year, category_id, film_id, nomination_id)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(year, category_id) DO UPDATE SET
                  film_id=excluded.film_id,
                  nomination_id=excluded.nomination_id,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (year, category_id, film_id, nomination_id),
            )
        else:
            conn.execute(
                '''
                DELETE FROM category_winners
                WHERE year = ? AND category_id = ? AND nomination_id = ?
                ''',
                (year, category_id, nomination_id),
        )
        conn.commit()
        conn.close()
        self._audit_admin(
            'admin_winner_update',
            success=True,
            admin=admin,
            details={'year': year, 'category': category_name, 'filmId': film_id, 'winner': bool(winner)},
        )
        self._json({'ok': True})

    @staticmethod
    def _send_contact_email(name, email, topic, message):
        subject = f'whatsnominated contact: {topic}'
        email_message = EmailMessage()
        email_message['Subject'] = subject
        email_message['From'] = CONTACT_FROM_EMAIL
        email_message['To'] = SUPPORT_EMAIL
        email_message['Reply-To'] = email
        email_message.set_content(
            '\n'.join(
                [
                    'New contact form submission:',
                    '',
                    f'Name: {name}',
                    f'Email: {email}',
                    f'Topic: {topic}',
                    '',
                    'Message:',
                    message,
                ]
            )
        )

        OscarHandler._smtp_send_message(email_message)

    def _post_contact(self, body):
        name = (body.get('name') or '').strip()
        email = (body.get('email') or '').strip()
        topic = (body.get('topic') or '').strip()
        message = (body.get('message') or '').strip()

        if not name or not email or not message:
            self._json(
                {'ok': False, 'error': 'Name, email, and message are required.'},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        sent = True
        send_error = ''
        try:
            self._send_contact_email(name, email, topic or 'General', message)
        except Exception as exc:
            sent = False
            send_error = str(exc)

        conn = connect()
        conn.execute(
            '''
            INSERT INTO contact_submissions(name, email, topic, message, sent, send_error)
            VALUES(?, ?, ?, ?, ?, ?)
            ''',
            (name, email, topic, message, 1 if sent else 0, send_error),
        )
        conn.commit()
        conn.close()

        self._json(
            {
                'ok': True,
                'sent': sent,
                'message': 'Thanks. Your message has been received.',
            }
        )


def run():
    init_db()
    host = os.getenv('OSCAR_HOST', '127.0.0.1')
    port = int(os.getenv('OSCAR_PORT', '8000'))
    server = ThreadingHTTPServer((host, port), OscarHandler)
    print(f'Serving on http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    run()
