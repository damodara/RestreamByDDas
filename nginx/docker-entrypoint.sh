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

# Диагностика для crud:server_logs (Django не может сам заглянуть внутрь
# контейнера nginx) — только worker_processes, ни строчки больше: сама
# nginx.conf содержит RTMP_HOOK_SECRET прямо в URL хуков (on_publish и
# т.п.), выкладывать её целиком на общий том никак нельзя. Больше одного
# воркера — самая частая причина "то в эфире, то нет" (/stat и /control
# у nginx-rtmp не шарят состояние между воркерами, см. nginx.conf.template).
mkdir -p /var/log/restream
grep -E '^worker_processes' /etc/nginx/nginx.conf > /var/log/restream/nginx-config-info.txt || true

exec nginx -g 'daemon off;'
