#!/bin/sh
set -eu

envsubst '${DJANGO_HOOK_BASE_URL} ${RTMP_HOOK_SECRET}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

# rtmp_logs — именованный Docker volume (см. docker-compose.yml), не
# обычная поддиректория /tmp. Docker создаёт его корень как root:root
# 0755, а exec_publish/exec_publish_done (push.sh/stop.sh) выполняются
# от www-data (nginx worker), не от root — без этого mkdir внутри
# push.sh падает Permission denied на первой же строке, и push вообще
# не запускается (подтверждено живым тестом на реальном сервере: nginx
# логирует "exec: child ... started", но тут же "exited with code 1",
# никаких файлов не появляется). 1777 — то же поведение, что было бы у
# обычной /tmp-поддиректории (sticky-bit, пишет кто угодно).
mkdir -p /tmp/rtmp-push
chmod 1777 /tmp/rtmp-push

exec nginx -g 'daemon off;'
