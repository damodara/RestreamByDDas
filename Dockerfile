FROM python:3.13-slim

# Дефолт "dev" — для локальной сборки (docker compose up --build) без
# CI, где нет git-тега в контексте. CI (.github/workflows/docker-publish.yml)
# передаёт сюда сам тег релиза (--build-arg APP_VERSION=v1.2.3).
ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="RestreamByDDas (Django)" \
      org.opencontainers.image.description="Django app for managing RTMP/SRT restream targets — web UI + hook endpoints. Part of the RestreamByDDas stack; run alongside the nginx and srt images from the same project, not standalone." \
      org.opencontainers.image.source="https://github.com/damodara/RestreamByDDas" \
      org.opencontainers.image.documentation="https://github.com/damodara/RestreamByDDas/blob/master/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

# В отличие от LABEL (видно только через `docker inspect`), это читает
# сам Django (settings.APP_VERSION) — показывается в футере на сайте.
ENV APP_VERSION=${APP_VERSION}

# ffmpeg — только для crud.destination_test (кнопка "тест" у дестинации,
# короткий синтетический пуш без реального эфира); сам relay-пайплайн живёт
# в контейнере nginx (rtmp-push/), это не дублирование той же роли.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV POETRY_VIRTUALENVS_CREATE=false
RUN pip install --no-cache-dir poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --without dev

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
