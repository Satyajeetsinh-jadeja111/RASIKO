#!/bin/sh
# One image, several roles: web (HTTP + websockets), worker (Celery), beat (scheduled jobs).
set -e
# SERVICE_ROLE (web / worker / beat) lets hosts like Railway run the same image as three services.
role="${SERVICE_ROLE:-$1}"
case "$role" in
  web)
    exec uvicorn config.asgi:application --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_WORKERS:-2}" \
      --proxy-headers --forwarded-allow-ips="*" --no-server-header
    ;;
  release)
    python manage.py migrate --noinput
    python manage.py bootstrap
    cp -a /app/staticfiles/. /shared-static/
    ;;
  worker)
    exec celery -A config worker --loglevel="${LOG_LEVEL:-INFO}" --concurrency="${WORKER_CONCURRENCY:-1}"
    ;;
  beat)
    exec celery -A config beat --loglevel="${LOG_LEVEL:-INFO}" --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  *)
    exec "$@"
    ;;
esac
