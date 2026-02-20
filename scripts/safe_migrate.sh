#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$ROOT_DIR/data/backups"
ADMIN_EXPORT="$BACKUP_DIR/admin-state-$TS.json"
BEFORE_COUNTS="$BACKUP_DIR/admin-counts-before-$TS.json"
AFTER_COUNTS="$BACKUP_DIR/admin-counts-after-$TS.json"

mkdir -p "$BACKUP_DIR"

bash "$ROOT_DIR/scripts/backup_db.sh"
python3 "$ROOT_DIR/backend/export_admin_state.py" --db "$ROOT_DIR/data/oscars.db" --out "$ADMIN_EXPORT"

python3 - <<'PY' > "$BEFORE_COUNTS"
import json, sqlite3
conn=sqlite3.connect('data/oscars.db')
cur=conn.cursor()
tables=['admin_watch_links','admin_watch_labels','admin_posters','admin_banners','admin_event_modes','admin_voting_locks','admin_users']
out={}
for t in tables:
  out[t]=cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
print(json.dumps(out))
conn.close()
PY

if [[ $# -eq 0 ]]; then
  echo "No command supplied. Running default migration: python3 backend/seed_db.py"
  python3 backend/seed_db.py
else
  echo "Running migration command: $*"
  "$@"
fi

python3 - <<'PY' > "$AFTER_COUNTS"
import json, sqlite3
conn=sqlite3.connect('data/oscars.db')
cur=conn.cursor()
tables=['admin_watch_links','admin_watch_labels','admin_posters','admin_banners','admin_event_modes','admin_voting_locks','admin_users']
out={}
for t in tables:
  out[t]=cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
print(json.dumps(out))
conn.close()
PY

RESTORE_NEEDED=0
set +e
python3 - <<'PY' "$BEFORE_COUNTS" "$AFTER_COUNTS"
import json,sys
before=json.load(open(sys.argv[1]))
after=json.load(open(sys.argv[2]))
critical=['admin_watch_links','admin_users']
drop=False
for t in critical:
  b=before.get(t,0)
  a=after.get(t,0)
  if b>0 and a==0:
    drop=True
    print(f'CRITICAL DROP: {t} {b} -> {a}')
print('before',before)
print('after',after)
print('restore' if drop else 'ok')
if drop:
  sys.exit(12)
PY
status=$?
set -e
if [[ $status -eq 12 ]]; then
  RESTORE_NEEDED=1
elif [[ $status -ne 0 ]]; then
  echo "Post-migration integrity check failed unexpectedly."
  exit $status
fi

if [[ $RESTORE_NEEDED -eq 1 ]]; then
  echo "Restoring admin state from $ADMIN_EXPORT"
  python3 "$ROOT_DIR/backend/import_admin_state.py" --db "$ROOT_DIR/data/oscars.db" --infile "$ADMIN_EXPORT"
  echo "Admin state restored due to critical count regression."
else
  echo "Migration check passed."
fi

echo "Artifacts:"
echo "  $ADMIN_EXPORT"
echo "  $BEFORE_COUNTS"
echo "  $AFTER_COUNTS"
