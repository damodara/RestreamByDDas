# Собирать из корня репозитория, чтобы попал rtmp-push/:
#   docker build -f nginx/Dockerfile -t restream-nginx .
FROM debian:bookworm-slim

ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="RestreamByDDas (nginx-rtmp)" \
      org.opencontainers.image.description="nginx-rtmp ingest/relay + reverse proxy for RestreamByDDas. Part of the RestreamByDDas stack; run alongside the django and srt images from the same project, not standalone." \
      org.opencontainers.image.source="https://github.com/damodara/RestreamByDDas" \
      org.opencontainers.image.documentation="https://github.com/damodara/RestreamByDDas/blob/master/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

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

EXPOSE 80 1935 8080

ENTRYPOINT ["/docker-entrypoint.sh"]
