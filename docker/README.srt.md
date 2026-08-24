# RestreamByDDas — SRT gateway

SRT-приём для [RestreamByDDas](https://github.com/damodara/RestreamByDDas) на базе MediaMTX — альтернативный вход в тот же RTMP-конвейер, что и у `damodara/restreambyddas-nginx` (тот же `stream_key`, любой протокол на входе).

**Это не самостоятельный образ.** Он авторизует публикацию через HTTP-хук в `damodara/restreambyddas-django` и ретранслирует принятый по SRT поток в `damodara/restreambyddas-nginx` по RTMP — без обоих эти образов он не функционален.

## Быстрый старт

Используйте `docker-compose.prod.yml` из репозитория — он уже описывает все нужные сервисы и переменные окружения:

```bash
git clone https://github.com/damodara/RestreamByDDas.git
cd RestreamByDDas
cp .env_example .env   # заполнить значения
docker compose -f docker-compose.prod.yml up -d
```

Полная документация: [README.md](https://github.com/damodara/RestreamByDDas/blob/master/README.md) и [CLAUDE.md](https://github.com/damodara/RestreamByDDas/blob/master/CLAUDE.md) (архитектура).

## Теги

- `latest` — последний собранный релиз (git-тег `vX.Y.Z`)
- `vX.Y.Z` — конкретная версия

## Лицензия

MIT
