#!/bin/sh
set -eu

envsubst '${DJANGO_HOOK_BASE_URL} ${RTMP_HOOK_SECRET}' \
    < /mediamtx.yml.template \
    > /mediamtx.yml

exec mediamtx /mediamtx.yml
