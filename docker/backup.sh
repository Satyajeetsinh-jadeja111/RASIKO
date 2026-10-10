#!/bin/sh
# Write the dump first: POSIX shell pipelines otherwise hide pg_dump failures.
set -eu
umask 077
KEEP="${BACKUP_KEEP_DAYS:-14}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
mkdir -p "$BACKUP_DIR"
backup_once() {
  STAMP=$(date -u +%Y%m%d-%H%M%S)
  FILE="$BACKUP_DIR/rasiko-$STAMP"
  if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "${POSTGRES_HOST:-db}" -U "${POSTGRES_USER:-rasiko}" -d "${POSTGRES_DB:-rasiko}" --no-owner -f "$FILE.sql.tmp" \
      && gzip -c "$FILE.sql.tmp" > "$FILE.sql.gz.tmp" \
      && gzip -t "$FILE.sql.gz.tmp" \
      && tar -czf "$FILE.media.tar.gz.tmp" -C "${BACKUP_MEDIA_DIR:-/media}" .; then
    mv "$FILE.sql.gz.tmp" "$FILE.sql.gz"
    mv "$FILE.media.tar.gz.tmp" "$FILE.media.tar.gz"
    rm -f "$FILE.sql.tmp"
    if [ -n "${BACKUP_UPLOAD_COMMAND:-}" ]; then
      # Administrator-supplied executable receives both paths; no shell evaluation.
      "$BACKUP_UPLOAD_COMMAND" "$FILE.sql.gz" "$FILE.media.tar.gz" || return 1
    fi
    touch "$BACKUP_DIR/last-success"
    echo "Backup verified: $STAMP"
    find "$BACKUP_DIR" -name 'rasiko-*.gz' -mtime +"$KEEP" -delete
  else
    rm -f "$FILE.sql.tmp" "$FILE.sql.gz.tmp" "$FILE.media.tar.gz.tmp"
    echo "Backup FAILED: $STAMP" >&2
    return 1
  fi
}
while true; do
  if backup_once; then result=0; else result=1; fi
  [ "${BACKUP_ONCE:-0}" = "1" ] && exit "$result"
  sleep 86400
done
