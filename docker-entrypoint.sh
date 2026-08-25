#!/bin/sh
set -eu

python - <<'PYEOF'
import os
import time

import psycopg2

for attempt in range(30):
    try:
        psycopg2.connect(
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=os.environ["DB_PORT"],
        ).close()
        break
    except psycopg2.OperationalError:
        time.sleep(1)
else:
    raise SystemExit("Postgres is not reachable, giving up")
PYEOF

python manage.py migrate --noinput
python manage.py collectstatic --noinput

python manage.py cleanup_destination_logs || true
# Раз в час, в фоне — нет отдельного планировщика (Celery и т.п.) в этом
# проекте, а раз в час более чем достаточно для очистки по дням (см.
# accounts.models.User.log_retention_days).
(
    while true; do
        sleep 3600
        python manage.py cleanup_destination_logs || true
    done
) &

exec python manage.py runserver 0.0.0.0:8000
