#!/usr/bin/env bash
set -euo pipefail
python manage.py migrate --noinput
python manage.py bootstrap_app
if [ "${SEED_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo
fi
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --threads 2 --timeout 120 --access-logfile - --error-logfile -
