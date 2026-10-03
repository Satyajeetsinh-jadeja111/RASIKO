#!/bin/sh
# One image, several roles: web (HTTP + websockets), worker (Celery), beat (scheduled jobs).
set -e
case "$1" in
  web)
    python manage.py migrate --noinput
    python manage.py bootstrap
    exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers "${WEB_WORKERS:-3}" \
      --proxy-headers --forwarded-allow-ips="*" --no-server-header
    ;;
  worker)
    exec celery -A config worker --loglevel="${LOG_LEVEL:-INFO}" --concurrency="${WORKER_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A config beat --loglevel="${LOG_LEVEL:-INFO}" --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  *)
    exec "$@"
    ;;
esac
