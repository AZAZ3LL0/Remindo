#!/bin/sh
# Database backup (tech.md 24.4). Runs inside the `db` container, which is the
# one place pg_dump is guaranteed to exist and to match the server version:
#
#   docker compose -f docker/compose.yml exec -T \
#     -e BACKUP_DIR=/backups db /srv/scripts/backup.sh
#
# On the VPS the same line goes into the host crontab. `make backup` wraps it.
#
# POSIX sh, not bash: postgres:16-alpine ships neither bash nor pipefail.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/reminder}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
POSTGRES_URL="${POSTGRES_URL:-postgresql://app:app@localhost:5432/reminder}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="${BACKUP_DIR}/reminder-${stamp}.dump"

mkdir -p "${BACKUP_DIR}"

# The custom format is compressed and pg_restore can take it apart object by
# object, which a plain SQL dump cannot. A half-written dump must never look
# like a backup, so the file lands under a partial name and is renamed only
# once pg_dump has exited cleanly.
pg_dump --format=custom --no-owner --no-privileges \
  --file="${target}.partial" "${POSTGRES_URL}"
mv "${target}.partial" "${target}"

echo "backup written: ${target}"

# Retention runs after the dump, never before: pruning first would leave a
# directory with neither a fresh backup nor the old ones when pg_dump fails.
find "${BACKUP_DIR}" -maxdepth 1 -name 'reminder-*.dump' -type f \
  -mtime "+${BACKUP_KEEP_DAYS}" -print -delete
