# Собирать из корня репозитория, чтобы попал rtmp-push/:
#   docker build -f nginx/Dockerfile -t restream-nginx .
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx-full \
        libnginx-mod-rtmp \
        ffmpeg \
        curl \
        jq \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY nginx/conf/nginx.conf.template /etc/nginx/nginx.conf.template
COPY nginx/docker-entrypoint.sh /docker-entrypoint.sh
COPY rtmp-push/ /rtmp-push/
RUN chmod +x /docker-entrypoint.sh /rtmp-push/push.sh /rtmp-push/stop.sh

EXPOSE 1935 8080

ENTRYPOINT ["/docker-entrypoint.sh"]
