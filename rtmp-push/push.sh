#!/bin/sh
# Запускается nginx-rtmp'ом (exec_publish) при старте публикации потока.
# $1 — stream_key (уже провалидирован on_publish-хуком в Django).
set -eu

STREAM_KEY="$1"
PID_DIR="/tmp/rtmp-push"
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

set --
i=0
while [ "$i" -lt "$COUNT" ]; do
    URL=$(echo "$DESTINATIONS_JSON" | jq -r ".[$i].push_url")
    set -- "$@" -c copy -f flv "$URL"
    i=$((i + 1))
done

# Без eval/sh -c: аргументы передаются ffmpeg напрямую, чтобы данные из БД
# (URL/ключ destination-а) не могли быть интерпретированы шеллом.
ffmpeg -nostdin -loglevel warning \
    -i "rtmp://127.0.0.1:1935/live/${STREAM_KEY}" \
    "$@" >"/tmp/rtmp-push/${STREAM_KEY}.log" 2>&1 &

echo $! >"${PID_DIR}/${STREAM_KEY}.pid"
