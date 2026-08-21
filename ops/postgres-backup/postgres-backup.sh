#!/bin/sh
set -eu

umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

BACKUP_INTERVAL_SECONDS="${POSTGRES_BACKUP_INTERVAL_SECONDS:-86400}"
RETENTION_DAYS="${POSTGRES_BACKUP_RETENTION_DAYS:-7}"

case "$BACKUP_INTERVAL_SECONDS" in
    *[!0-9]*|'') echo "POSTGRES_BACKUP_INTERVAL_SECONDS must be a positive integer" >&2; exit 1 ;;
esac
if [ "$BACKUP_INTERVAL_SECONDS" -eq 0 ]; then
    echo "POSTGRES_BACKUP_INTERVAL_SECONDS must be greater than zero" >&2
    exit 1
fi
case "$RETENTION_DAYS" in
    *[!0-9]*|'') echo "POSTGRES_BACKUP_RETENTION_DAYS must be a non-negative integer" >&2; exit 1 ;;
esac
case "$PGDATABASE" in
    *[!A-Za-z0-9_.-]*|'') echo "PGDATABASE contains unsupported characters" >&2; exit 1 ;;
esac

log() {
    level="$1"
    message="$2"
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"timestamp":"%s","level":"%s","service":"aio-agent-postgres-backup","trace_id":"","logger":"postgres.backup","message":"%s"}\n' \
        "$timestamp" "$level" "$message"
}

backup_once() {
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    target="/backups/${PGDATABASE}_${timestamp}.dump"
    temporary="${target}.tmp"
    marker_temporary="/backups/.last-success.tmp"

    rm -f "$temporary" "$marker_temporary"
    if pg_dump --format=custom --no-owner --no-privileges --file="$temporary"; then
        mv "$temporary" "$target"
        date +%s > "$marker_temporary"
        mv "$marker_temporary" /backups/.last-success
        find /backups -maxdepth 1 -type f -name "${PGDATABASE}_*.dump" -mtime "+$RETENTION_DAYS" -delete
        log INFO "backup_completed"
    else
        rm -f "$temporary" "$marker_temporary"
        log ERROR "backup_failed"
        return 1
    fi
}

trap 'exit 0' INT TERM

while true; do
    backup_once || true
    sleep "$BACKUP_INTERVAL_SECONDS" &
    wait "$!"
done
