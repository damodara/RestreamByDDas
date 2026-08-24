# RestreamByDDas — Django

Веб-интерфейс и HTTP-хуки для [RestreamByDDas](https://github.com/damodara/RestreamByDDas) — приложения для управления рестримом RTMP/SRT-потока на несколько площадок одновременно.

**Это не самостоятельный образ.** Он рассчитан на совместный запуск с `damodara/restreambyddas-nginx` (приём/релей RTMP) и `damodara/restreambyddas-srt` (приём SRT) плюс PostgreSQL — по отдельности он не принимает и не рассылает поток, только отдаёт веб-интерфейс и обслуживает хуки для инфраструктурных образов.

## Быстрый старт

Используйте `docker-compose.prod.yml` из репозитория — он уже описывает все четыре сервиса (db/django/nginx/srt) и нужные переменные окружения:

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
