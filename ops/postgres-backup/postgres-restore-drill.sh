#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

DRILL_DATABASE="${POSTGRES_RESTORE_DRILL_DATABASE:-aio_agent_restore_drill}"
BACKUP_FILE="${POSTGRES_RESTORE_DRILL_FILE:-}"

case "$DRILL_DATABASE" in
    *_restore_drill) ;;
    *) echo "POSTGRES_RESTORE_DRILL_DATABASE must end with _restore_drill" >&2; exit 1 ;;
esac
case "$DRILL_DATABASE" in
    *[!A-Za-z0-9_]*) echo "POSTGRES_RESTORE_DRILL_DATABASE contains unsupported characters" >&2; exit 1 ;;
esac

if [ -z "$BACKUP_FILE" ]; then
    BACKUP_FILE="$(find /backups -maxdepth 1 -type f -name '*.dump' -print | sort | tail -1)"
fi
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "No backup file is available for the restore drill" >&2
    exit 1
fi

dropdb --if-exists "$DRILL_DATABASE"
createdb "$DRILL_DATABASE"
cleanup() {
    dropdb --if-exists "$DRILL_DATABASE"
}
trap cleanup EXIT INT TERM

pg_restore --exit-on-error --no-owner --no-privileges --dbname="$DRILL_DATABASE" "$BACKUP_FILE"
psql --dbname="$DRILL_DATABASE" --tuples-only --command="select count(*) from flyway_schema_history where success = true"
psql --dbname="$DRILL_DATABASE" --tuples-only --command="select count(*) from app_users"
echo "restore_drill_completed database=$DRILL_DATABASE backup=$(basename "$BACKUP_FILE")"
