import json
import mimetypes
import os
import re
import smtplib
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

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / 'web'
POSTER_CACHE_ROOT = ROOT / 'data' / 'poster_cache'
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
ADMIN_SESSION_COOKIE = 'oscars_admin_session'
ADMIN_SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 10
LOGIN_LOCKOUT_SECONDS = 15 * 60
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

    def _handle_api_get(self, parsed):
        query = parse_qs(parsed.query)
        if parsed.path == '/api/admin-auth/session':
            return self._get_admin_auth_session()
        if parsed.path == '/api/years':
            return self._get_years()
        if parsed.path.startswith('/api/admin/audit'):
            if not self._require_admin_api():
                return
            return self._get_admin_audit_logs(query)
        if parsed.path == '/api/admin/dashboard':
            if not self._require_admin_api():
                return
            year = int(query.get('year', ['2026'])[0])
            return self._get_admin_dashboard(year)
        if parsed.path == '/api/nominees':
            year = int(query.get('year', ['2026'])[0])
            category = query.get('category', ['__ALL__'])[0]
            return self._get_nominees(year, category)
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

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_api_post(self, parsed):
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
        self.send_error(HTTPStatus.NOT_FOUND)

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
              SELECT category_id, film_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.film_id = wc.film_id THEN 1 ELSE 0 END) AS correct
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
            SELECT c.name AS category, n.film_id AS filmId, n.nominee
            FROM nominations n
            JOIN categories c ON c.id = n.category_id
            WHERE n.year = ?
            ORDER BY n.id
            ''',
            (year,),
        ).fetchall()

        winners = conn.execute(
            '''
            SELECT c.name AS category, cw.film_id AS filmId
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
            'winnersByCategory': {row['category']: row['filmId'] for row in winners},
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
            SELECT c.name AS category, up.film_id AS filmId
            FROM user_picks up
            JOIN categories c ON c.id = up.category_id
            WHERE up.year = ? AND up.user_key = ?
            ''',
            (year, user_key),
        ).fetchall()

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
             AND cw.film_id = up.film_id
            WHERE up.year = ? AND up.user_key = ?
            ''',
            (year, user_key),
        ).fetchone()
        user_correct = user_correct_row['correct'] if user_correct_row else 0

        other_scores = conn.execute(
            '''
            WITH winner_categories AS (
              SELECT category_id, film_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.film_id = wc.film_id THEN 1 ELSE 0 END) AS correct
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
              SELECT category_id, film_id
              FROM category_winners
              WHERE year = ?
            ),
            user_scores AS (
              SELECT
                up.user_key AS user_key,
                SUM(CASE WHEN up.film_id = wc.film_id THEN 1 ELSE 0 END) AS correct
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

        conn.close()
        self._json(
            {
                'seenFilmIds': [row['film_id'] for row in rows],
                'picksByCategory': {row['category']: row['filmId'] for row in picks},
                'performance': {
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
        picked = bool(body.get('picked'))
        category_id = self._category_id(year, category_name)

        if not category_id:
            self._json({'ok': False, 'error': 'Unknown category'}, status=HTTPStatus.BAD_REQUEST)
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

        if picked:
            conn.execute(
                '''
                INSERT INTO user_picks(user_key, year, category_id, film_id)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_key, year, category_id) DO UPDATE SET
                  film_id=excluded.film_id,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (user_key, year, category_id, film_id),
            )
        else:
            conn.execute(
                '''
                DELETE FROM user_picks
                WHERE user_key = ? AND year = ? AND category_id = ? AND film_id = ?
                ''',
                (user_key, year, category_id, film_id),
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

        conn = connect()
        if winner:
            conn.execute(
                '''
                INSERT INTO category_winners(year, category_id, film_id)
                VALUES(?, ?, ?)
                ON CONFLICT(year, category_id) DO UPDATE SET
                  film_id=excluded.film_id,
                  updated_at=CURRENT_TIMESTAMP
                ''',
                (year, category_id, film_id),
            )
        else:
            conn.execute(
                '''
                DELETE FROM category_winners
                WHERE year = ? AND category_id = ? AND film_id = ?
                ''',
                (year, category_id, film_id),
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
