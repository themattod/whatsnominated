#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
YEAR="${1:-2026}"
INFILE="${2:-}"

if [ -z "$INFILE" ]; then
  echo "Usage: bash scripts/sync_odds.sh <year> <infile>"
  exit 1
fi

python3 backend/odds_sync.py --year "$YEAR" --infile "$INFILE"
