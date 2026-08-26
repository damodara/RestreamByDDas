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

# Один долгоживущий процесс на весь контейнер — сам поллит YouTube чат в
# бесконечном цикле (не завершается сам по себе, в отличие от cleanup
# выше). Обёрнут в while, чтобы перезапускался, если всё же упадёт на
# необработанном исключении, а не тихо пропадал до рестарта контейнера.
(
    while true; do
        python manage.py poll_youtube_chat || true
        sleep 5
    done
) &

# Тот же принцип, для Telegram-бота (accounts.telegram_bot/поллинг
# getUpdates) — тоже долгоживущий процесс, тоже перезапускается сам при
# падении. Ничего не делает и не жжёт CPU, пока TELEGRAM_BOT_TOKEN не
# задан (см. accounts.management.commands.poll_telegram_bot).
(
    while true; do
        python manage.py poll_telegram_bot || true
        sleep 5
    done
) &

exec python manage.py runserver 0.0.0.0:8000
