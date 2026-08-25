# Собирать из корня репозитория, чтобы попал srt-bridge/:
#   docker build -f srt-gateway/Dockerfile -t restream-srt-gateway .
FROM debian:bookworm-slim

ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="RestreamByDDas (SRT gateway)" \
      org.opencontainers.image.description="MediaMTX-based SRT ingest gateway for RestreamByDDas, bridging into the same RTMP pipeline as the nginx image. Part of the RestreamByDDas stack; run alongside the django and nginx images from the same project, not standalone." \
      org.opencontainers.image.source="https://github.com/damodara/RestreamByDDas" \
      org.opencontainers.image.documentation="https://github.com/damodara/RestreamByDDas/blob/master/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

ARG MEDIAMTX_VERSION=v1.19.2
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        ffmpeg \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
        "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${TARGETARCH}.tar.gz" \
        -o /tmp/mediamtx.tar.gz \
    && tar -xzf /tmp/mediamtx.tar.gz -C /usr/local/bin mediamtx \
    && rm /tmp/mediamtx.tar.gz

COPY srt-gateway/conf/mediamtx.yml.template /mediamtx.yml.template
COPY srt-gateway/docker-entrypoint.sh /docker-entrypoint.sh
COPY srt-bridge/ /srt-bridge/
RUN chmod +x /docker-entrypoint.sh /srt-bridge/start.sh

EXPOSE 8890/udp

ENTRYPOINT ["/docker-entrypoint.sh"]
