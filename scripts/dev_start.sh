#!/usr/bin/env bash
# Run setup, then open each dev process in its own gnome-terminal tab.
# (Inside VS Code, use Terminal -> Run Task -> "Rasiko: start all" instead.)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENV="$(cd "${VENV:-../.venv}" && pwd)"

./scripts/dev_setup.sh

tab() { # title, command
  echo "--tab --title=$1 -- bash -c \"cd '$ROOT' && $2; echo; echo '[$1 stopped] press Enter to close'; read\""
}
eval gnome-terminal \
  "$(tab Django "'$VENV/bin/python' manage.py runserver")" \
  "$(tab Celery-worker "'$VENV/bin/celery' -A config worker -l info")" \
  "$(tab Celery-beat "'$VENV/bin/celery' -A config beat -l info")" \
  "$(tab Tailwind "cd frontend && npm run watch")"
echo "Started. Shop: http://localhost:8000"
