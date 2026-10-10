#!/usr/bin/env bash
# One-time / every-start setup for local development. Safe to run repeatedly.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="${VENV:-../.venv}"
PY="$VENV/bin/python"

echo "==> Checking PostgreSQL and Redis"
pg_isready -q -h localhost || { echo "PostgreSQL is not running. Start it: sudo systemctl start postgresql"; exit 1; }
"$PY" -c "import redis; redis.Redis().ping()" 2>/dev/null || { echo "Redis is not running. Start it: sudo systemctl start redis-server"; exit 1; }

echo "==> Python packages"
"$PY" -m pip install -q -r requirements.txt

echo "==> Database migrations"
"$PY" manage.py migrate --noinput

echo "==> Translations (Gujarati, Hindi)"
"$PY" manage.py compilemessages --ignore=node_modules >/dev/null

if [ ! -d frontend/node_modules ]; then
  echo "==> Frontend packages (first run only)"
  (cd frontend && npm ci --no-audit --no-fund)
fi

echo "==> Setup done"
