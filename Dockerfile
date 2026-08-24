FROM python:3.13-slim

LABEL org.opencontainers.image.title="RestreamByDDas (Django)" \
      org.opencontainers.image.description="Django app for managing RTMP/SRT restream targets — web UI + hook endpoints. Part of the RestreamByDDas stack; run alongside the nginx and srt images from the same project, not standalone." \
      org.opencontainers.image.source="https://github.com/damodara/RestreamByDDas" \
      org.opencontainers.image.documentation="https://github.com/damodara/RestreamByDDas/blob/master/README.md" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
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
