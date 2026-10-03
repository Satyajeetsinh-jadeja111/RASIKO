#!/bin/sh
# Daily compressed PostgreSQL dump; keeps BACKUP_KEEP_DAYS days. Runs inside the `backup` container.
set -eu
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p /backups
while true; do
  STAMP=$(date +%Y%m%d-%H%M)
  FILE="/backups/rasiko-$STAMP.sql.gz"
  if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner | gzip -9 > "$FILE.tmp"; then
    mv "$FILE.tmp" "$FILE"
    echo "Backup written: $FILE"
  else
    rm -f "$FILE.tmp"
    echo "Backup FAILED at $STAMP" >&2
  fi
  find /backups -name 'rasiko-*.sql.gz' -mtime +"$KEEP" -delete
  sleep 86400
done
