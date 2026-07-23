#!/bin/sh
# Запускается MediaMTX (runOnReady) когда SRT-паблишер становится активным,
# и держится на переднем плане: MediaMTX сама шлёт этому процессу SIGINT,
# когда поток останавливается (и перезапускает — runOnReadyRestart — если он
# упал сам, например из-за временного сбоя соединения при самом старте).
# $1 — путь (= stream_key, т.к. клиент публикует с streamid=publish:<stream_key>,
# а он уже провалидирован authHTTPAddress-хуком в Django).
#
# Читает поток обратно у MediaMTX через её встроенный RTMP-вывод и публикует
# его в уже существующий RTMP-приём nginx под тем же stream_key — дальше всё
# идёт по обычному RTMP-пути (on_publish_hook, push.sh, destinations, /stat).
set -eu

PATH_NAME="$1"

# MediaMTX отдаёт свежепринятый SRT-поток по RTMP без надёжного onMetaData
# (в отличие от обычной OBS-публикации), поэтому ffmpeg не может мгновенно
# определить параметры видео — явно просим его подождать/пробрать достаточно
# данных, вместо того чтобы сразу проваливать попытку подключения к nginx.
exec ffmpeg -nostdin -loglevel warning \
    -probesize 5000000 -analyzeduration 5000000 \
    -i "rtmp://127.0.0.1:1935/${PATH_NAME}" \
    -c copy -f flv "rtmp://${NGINX_RTMP_HOST}:1935/live/${PATH_NAME}"
