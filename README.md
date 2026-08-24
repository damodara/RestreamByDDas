# RestreamByDDas

Django-приложение для управления рестримом видеопотока на несколько площадок одновременно (VK, YouTube и т.п.).

## Возможности

- Приём потока по **RTMP** или **SRT** — один и тот же `stream_key`, любой протокол на входе
- Рестрим (фан-аут) на произвольное число RTMP-дестинаций
- Регистрация с подтверждением администратором по email-ссылке (без самостоятельной регистрации)
- Статистика потока (битрейт, аптайм) и нагрузка сервера
- Перезапуск трансляции (сброс паблишера) — подхватывает изменения списка дестинаций
- Полный стек в Docker Compose: Django + PostgreSQL + nginx-rtmp + MediaMTX (SRT-шлюз)

## Быстрый старт (Docker)

1. Скопировать `.env_example` в `.env` и заполнить значения (см. комментарии в файле).
2. Поднять стек:
   ```bash
   docker compose up -d --build
   ```
3. Открыть http://localhost — веб-интерфейс доступен.
4. Адреса для публикации потока:
   - RTMP: `rtmp://<host>:1935/live/<stream_key>`
   - SRT: `srt://<host>:8890?streamid=publish:<stream_key>`

Регистрация требует подтверждения от staff-пользователя, а такого пользователя изначально нет — первого создаём вручную:
```bash
docker compose exec django python manage.py createsuperuser
```

## Быстрый старт (без Docker)

Нужен локально запущенный PostgreSQL.

```bash
poetry install
cp .env_example .env   # заполнить DB_*, SECRET_KEY и т.д.
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

Без Docker недоступен сам приём/релей RTMP и SRT (это отдельные компоненты — nginx-rtmp и MediaMTX) — только веб-интерфейс управления точками приёма и дестинациями.

## Docker Hub

Готовые образы: `damodara/restreambyddas-django`, `damodara/restreambyddas-nginx`, `damodara/restreambyddas-srt`. Каждый образ — часть стека, по отдельности не запускается (нужны минимум `django`+`nginx`, `srt` — опционально для приёма по SRT). Запуск без клонирования репозитория целиком, только `docker-compose.prod.yml` и `.env`:

```bash
curl -O https://raw.githubusercontent.com/damodara/RestreamByDDas/master/docker-compose.prod.yml
curl -O https://raw.githubusercontent.com/damodara/RestreamByDDas/master/.env_example
cp .env_example .env   # заполнить значения
docker compose -f docker-compose.prod.yml up -d
```

Версия образов задаётся переменной `TAG` (по умолчанию `latest`), например `TAG=v1.2.0 docker compose -f docker-compose.prod.yml up -d`.

Используйте `docker-compose.prod.yml` как есть, не переписывайте его вручную — там уже расставлены все обязательные переменные окружения между сервисами (`ALLOWED_HOSTS` с добавлением `,django` для хуков, `NGINX_RTMP_HOST` для SRT-моста, пути монтирования статики и т.п.); ручной compose легко получить рабочим лишь частично.

При отсутствующих/некорректных `FIELD_ENCRYPTION_KEY` или `ALLOWED_HOSTS` (при `DEBUG=False`) контейнер `django` завершится сразу при старте с понятной ошибкой в `docker compose logs django` (`crud.E001`/`crud.E002`/`crud.E003`) — а не тихо взлетит и упадёт позже на первой попытке добавить дестинацию или принять поток.

### Выпуск релиза (для мейнтейнера)

Публикация образов автоматическая по CI (`.github/workflows/docker-publish.yml`), запускается git-тегом:

```bash
git tag v1.2.0
git push origin v1.2.0
```

CI собирает и пушит все три образа под `latest` и `v1.2.0` (multi-arch: `linux/amd64`, `linux/arm64`). Требуются секреты репозитория `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` (Settings → Secrets and variables → Actions на GitHub; токен — Docker Hub → Account Settings → Security → New Access Token, права Read & Write, не пароль от аккаунта).

Описания образов на Docker Hub (карточка репозитория) CI не трогает — Hub API для этого стабильно отвечает `Forbidden` на personal access token независимо от его прав (известное ограничение самого Docker Hub, не решается настройкой токена). Текст для каждой карточки лежит в `docker/README.{django,nginx,srt}.md` — при необходимости обновить вставить вручную на странице репозитория на Docker Hub.

## Тесты

```bash
poetry run python manage.py test
```

## Как это работает

1. Пользователь создаёт точку приёма (Stream) — получает уникальный `stream_key` и адреса для публикации (RTMP и/или SRT).
2. Добавляет одну или несколько RTMP-дестинаций (название площадки, RTMP-адрес, ключ).
3. Публикует поток с энкодера (OBS и т.п.) на выданный адрес.
4. Сервер принимает поток и рассылает копии на все дестинации.

Список дестинаций подхватывается только в момент старта публикации: если изменить дестинации у уже запущенного стрима, нужно нажать «Перезапустить трансляцию» на странице точки приёма (или переподключить энкодер вручную).

## Лицензия

[MIT](LICENSE)
