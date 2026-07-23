#!/bin/sh
set -eu

envsubst '${DJANGO_HOOK_BASE_URL} ${RTMP_HOOK_SECRET}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

exec nginx -g 'daemon off;'
