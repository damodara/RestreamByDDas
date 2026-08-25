#!/bin/sh
# Запускается nginx-rtmp'ом (exec_publish_done) при завершении публикации.
# $1 — stream_key.
set -eu

STREAM_KEY="$1"
PID_DIR="/tmp/rtmp-push/${STREAM_KEY}"

kill_and_wait() {
    PID="$1"
    LABEL="$2"
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
                echo "stop.sh: ${LABEL} (pid ${PID}) не завершился по TERM, добиваю KILL" >&2
                kill -9 "$PID" 2>/dev/null || true
                break
            fi
            sleep 0.5
        done
    fi
}

if [ -d "$PID_DIR" ]; then
    # Удаляем только .pid — .log за каждую дестинацию оставляем: файл
    # именуется по id дестинации (не позиции в списке), так что следующая
    # публикация того же stream_key перезапишет тот же файл, а до этого
    # по нему можно посмотреть, что пошло не так, уже после того как
    # стрим закончился — в т.ч. через crud:destination_log на сайте.
    for PID_FILE in "$PID_DIR"/*.pid; do
        [ -f "$PID_FILE" ] || continue
        PID=$(cat "$PID_FILE")
        rm -f "$PID_FILE"
        kill_and_wait "$PID" "${STREAM_KEY}/$(basename "$PID_FILE")"
    done
fi
