#!/bin/sh
# Запускается nginx-rtmp'ом (exec_publish_done) при завершении публикации.
# $1 — stream_key.
set -eu

STREAM_KEY="$1"
PID_FILE="/tmp/rtmp-push/${STREAM_KEY}.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
