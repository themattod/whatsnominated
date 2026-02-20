#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import secrets

from db import connect, init_db


def password_hash(password, salt=None, iterations=180000):
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt_bytes, iterations)
    return f'pbkdf2_sha256${iterations}${salt_bytes.hex()}${digest.hex()}'


def verify_password(password, encoded):
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


def main():
    parser = argparse.ArgumentParser(description='Create or update the admin login account.')
    parser.add_argument('--email', required=True)
    parser.add_argument('--password', required=True)
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = args.password
    if '@' not in email:
        raise SystemExit('Email must be valid.')
    if len(password) < 10:
        raise SystemExit('Password must be at least 10 characters.')

    init_db()
    conn = connect()
    row = conn.execute('SELECT id, password_hash FROM admin_users WHERE lower(email) = ?', (email,)).fetchone()
    encoded = password_hash(password)

    if row:
        if verify_password(password, row['password_hash']):
            print(f'Admin account already set: {email}')
        else:
            conn.execute(
                'UPDATE admin_users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (encoded, row['id']),
            )
            conn.execute('DELETE FROM admin_sessions WHERE user_id = ?', (row['id'],))
            conn.commit()
            print(f'Admin password updated: {email}')
    else:
        conn.execute(
            'INSERT INTO admin_users(email, password_hash) VALUES(?, ?)',
            (email, encoded),
        )
        conn.commit()
        print(f'Admin account created: {email}')

    conn.close()


if __name__ == '__main__':
    main()
