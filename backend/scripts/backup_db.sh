#!/usr/bin/env bash
# Daily SQLite backup with 7-day rotation (plan 09 §1).
#
# Uses `sqlite3 .backup` (a consistent online snapshot, WAL-safe) rather than `cp`, which
# can capture a torn file while the runner is writing. Backs up every *.db in the data dir
# and prunes anything older than 7 daily generations per database.
#
# Usage:
#   backend/scripts/backup_db.sh [DATA_DIR] [BACKUP_DIR]
# Defaults: DATA_DIR=backend/data, BACKUP_DIR=$DATA_DIR/backups
#
# Cron (daily 02:30, keep 7):
#   30 2 * * * /path/to/backend/scripts/backup_db.sh >> /var/log/bot-backup.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${1:-$SCRIPT_DIR/../data}"
BACKUP_DIR="${2:-$DATA_DIR/backups}"
KEEP=7

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d)"

shopt -s nullglob
found=0
for db in "$DATA_DIR"/*.db; do
  found=1
  name="$(basename "$db" .db)"
  out="$BACKUP_DIR/${name}-${stamp}.db"
  echo "backing up $db -> $out"
  sqlite3 "$db" ".backup '$out'"

  # Keep only the newest $KEEP snapshots for this database (portable: no `mapfile`, which
  # macOS's bash 3.2 lacks).
  ls -1t "$BACKUP_DIR/${name}-"*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r f; do
    echo "pruning old backup $f"
    rm -f "$f"
  done
done

if [ "$found" -eq 0 ]; then
  echo "no *.db files found in $DATA_DIR" >&2
  exit 1
fi

echo "backup complete: $BACKUP_DIR"
