#!/bin/sh
# Запускается nginx-rtmp'ом (exec_publish_done) при завершении публикации.
# $1 — stream_key.
set -eu

STREAM_KEY="$1"
PID_FILE="/tmp/rtmp-push/${STREAM_KEY}.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    rm -f "$PID_FILE"

    # nginx-rtmp не рвёт соединение push-ffmpeg с "live"-app принудительно —
    # оно просто перестаёт получать данные, и ffmpeg, простаивая на чтении
    # этого входа, иногда не реагирует на TERM (подтверждено живым тестом:
    # процесс оставался в TCP ESTABLISHED к дестинации бесконечно). Ждём
    # до 5 секунд и добиваем KILL, иначе push остаётся висеть без данных.
    if kill "$PID" 2>/dev/null; then
        i=0
        while kill -0 "$PID" 2>/dev/null; do
            i=$((i + 1))
            if [ "$i" -ge 10 ]; then
                echo "stop.sh: ${STREAM_KEY} (pid ${PID}) не завершился по TERM, добиваю KILL" >&2
                kill -9 "$PID" 2>/dev/null || true
                break
            fi
            sleep 0.5
        done
    fi
fi
