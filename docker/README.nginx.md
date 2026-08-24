# RestreamByDDas — nginx-rtmp

Приём и релей RTMP-потока для [RestreamByDDas](https://github.com/damodara/RestreamByDDas) (nginx + модуль `nginx-rtmp`), плюс реверс-прокси для веб-интерфейса и раздача статики.

**Это не самостоятельный образ.** Он ходит HTTP-хуками (`on_publish`, список дестинаций) в `damodara/restreambyddas-django` и рассчитан на совместный запуск с ним (и опционально с `damodara/restreambyddas-srt` для приёма по SRT) — по отдельности принимать поток он сможет, но без Django не будет знать, куда его ретранслировать.

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
