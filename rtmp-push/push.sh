#!/bin/sh
# Запускается nginx-rtmp'ом (exec_publish) при старте публикации потока.
# $1 — stream_key (уже провалидирован on_publish-хуком в Django).
set -eu

STREAM_KEY="$1"
PID_DIR="/tmp/rtmp-push/${STREAM_KEY}"
mkdir -p "$PID_DIR"

DESTINATIONS_URL="${DJANGO_HOOK_BASE_URL}/crud/rtmp-hooks/destinations/${STREAM_KEY}/?secret=${RTMP_HOOK_SECRET}"
DESTINATIONS_JSON=$(curl -fsS "$DESTINATIONS_URL") || {
    echo "push.sh: failed to fetch destinations for ${STREAM_KEY}" >&2
    exit 0
}

COUNT=$(echo "$DESTINATIONS_JSON" | jq 'length')
if [ "$COUNT" -eq 0 ]; then
    exit 0
fi

STATUS_URL="${DJANGO_HOOK_BASE_URL}/crud/rtmp-hooks/destination-status/?secret=${RTMP_HOOK_SECRET}"

# Лучшее усилие — сам push не должен зависеть от того, ответил ли Django;
# это только для статуса в UI, не для решения "пушить или нет".
report_status() {
    curl -fsS --max-time 3 -X POST "$STATUS_URL" \
        -H "Content-Type: application/json" \
        -d "{\"destination_id\": $1, \"status\": \"$2\"}" >/dev/null 2>&1 || true
}

# Один ffmpeg-процесс на дестинацию, а не один процесс с несколькими -f flv
# выходами: если ffmpeg не может открыть хотя бы один выход (дестинация
# недоступна/отклонила соединение), он падает целиком — раньше это гасило
# раздачу вообще на все дестинации разом, включая рабочие. Подтверждено
# живым тестом: недоступная дестинация полностью останавливала push даже на
# заведомо рабочую. Изоляция по процессам решает это — падение одной
# дестинации не трогает остальные.
i=0
while [ "$i" -lt "$COUNT" ]; do
    URL=$(echo "$DESTINATIONS_JSON" | jq -r ".[$i].push_url")
    DEST_ID=$(echo "$DESTINATIONS_JSON" | jq -r ".[$i].id")

    # Каждая дестинация — свой независимый background-сабшелл: репортит
    # "live" сразу после запуска, дожидается своего ffmpeg и репортит
    # финальный статус по коду выхода. 143/137 — процесс убил stop.sh
    # (обычный конец публикации, TERM/KILL), значит "stopped". Любой другой
    # код — ffmpeg завершился сам (не смог подключиться к дестинации или она
    # оборвала соединение посреди эфира), значит "error". Так UI узнаёт не
    # просто "идёт стрим или нет", а какая конкретно площадка сейчас рвётся.
    (
        ffmpeg -nostdin -loglevel warning \
            -i "rtmp://127.0.0.1:1935/live/${STREAM_KEY}" \
            -c copy -f flv "$URL" \
            >"${PID_DIR}/${i}.log" 2>&1 &
        FFMPEG_PID=$!
        echo "$FFMPEG_PID" >"${PID_DIR}/${i}.pid"
        report_status "$DEST_ID" "live"

        set +e
        wait "$FFMPEG_PID"
        EXIT_CODE=$?
        set -e

        rm -f "${PID_DIR}/${i}.pid"
        if [ "$EXIT_CODE" -eq 143 ] || [ "$EXIT_CODE" -eq 137 ]; then
            report_status "$DEST_ID" "stopped"
        else
            report_status "$DEST_ID" "error"
        fi
    ) &

    i=$((i + 1))
done
