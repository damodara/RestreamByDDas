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
    ffmpeg -nostdin -loglevel warning \
        -i "rtmp://127.0.0.1:1935/live/${STREAM_KEY}" \
        -c copy -f flv "$URL" \
        >"${PID_DIR}/${i}.log" 2>&1 &
    echo $! >"${PID_DIR}/${i}.pid"
    i=$((i + 1))
done
