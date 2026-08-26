# Установка на сервер (Docker Hub)

Готовые образы `damodara/restreambyddas-{django,nginx,srt}` — установка не требует клонирования репозитория и локальной сборки, только Docker Engine + Compose plugin на сервере.

## Установка

```bash
mkdir -p /opt/restreambyddas
cd /opt/restreambyddas

curl -O https://raw.githubusercontent.com/damodara/RestreamByDDas/master/docker-compose.prod.yml
curl -O https://raw.githubusercontent.com/damodara/RestreamByDDas/master/.env_example
cp .env_example .env
```

Сгенерировать секреты (Fernet-ключ генерируется без `cryptography` — её нет в голом `python:3.13-slim`, а сам ключ — это просто base64 от 32 случайных байт):

```bash
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
sed -i "s|^FIELD_ENCRYPTION_KEY=.*|FIELD_ENCRYPTION_KEY=$(docker run --rm python:3.13-slim python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")|" .env
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$(openssl rand -hex 24)|" .env
sed -i "s|^RTMP_HOOK_SECRET=.*|RTMP_HOOK_SECRET=$(openssl rand -hex 32)|" .env
```

Дозаполнить руками:

```bash
nano .env
```

```
DEBUG=False
ALLOWED_HOSTS=<IP-или-домен-сервера>,localhost,127.0.0.1
DB_NAME=restreambyddas
DB_USER=restreambyddas
DB_PORT=5432
RTMP_SERVER_HOST=<IP-или-домен-сервера>
RTMP_APP=live
SRT_SERVER_HOST=<IP-или-домен-сервера>
SRT_PORT=8890
USE_TLS=False
```

`ALLOWED_HOSTS`/`RTMP_SERVER_HOST`/`SRT_SERVER_HOST` — без `http://`, без пути, только голый хост/IP.

```bash
chmod 600 .env
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f django
```

Дождаться `Applying ... OK` по всем миграциям, `Ctrl+C` (контейнер продолжит работать), затем:

```bash
docker compose -f docker-compose.prod.yml exec django python manage.py createsuperuser
```

Первый пользователь регистрируется как `PENDING` и не может войти, пока admin (только что созданный суперпользователь) не подтвердит его через `/admin/` или email-ссылку — см. README «Как это работает».

## Проверка

```bash
docker compose -f docker-compose.prod.yml ps
curl -I http://localhost/accounts/login/
```

## Telegram-уведомления об ошибке пуша (опционально)

По умолчанию выключены — работают только при заполненных `TELEGRAM_BOT_TOKEN`/`TELEGRAM_BOT_USERNAME` в `.env`, один бот на весь сервер, каждый пользователь подключает его к своему аккаунту сам.

1. В Telegram написать [@BotFather](https://t.me/BotFather) → `/newbot`, задать имя и username (должен заканчиваться на `bot`, например `MyRestreamBot`). BotFather сразу выдаст токен и покажет username.
2. Вписать оба значения в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<токен от BotFather>
   TELEGRAM_BOT_USERNAME=<username без @>
   ```
3. Перезапустить `django` (он же поднимает фоновый процесс `poll_telegram_bot`):
   ```bash
   docker compose -f docker-compose.prod.yml up -d --force-recreate django
   ```

После этого каждый пользователь сам подключает Telegram в личном кабинете (`/accounts/profile/` → «Подключить Telegram») и включает уведомления галочкой — без участия администратора.

## HTTPS

Этот стек сам по себе не терминирует TLS — nginx здесь настроен только для RTMP-приёма и plain HTTP-проксирования на порт 80, сертификатов и HTTPS в нём нет. Значит:

- Логин, пароль, сессионные cookie идут в открытом виде по HTTP, если ничего не добавить.
- `USE_TLS=True` в `.env` включать нельзя, пока перед стеком нет реального TLS — иначе сломается логин (браузер не отправит `Secure`-cookie по `http://`).

Для настоящей защиты нужен отдельный TLS-терминирующий реверс-прокси перед этим стеком, слушающий 443 и проксирующий на порт nginx-контейнера. Проще всего — **Caddy** (автоматический Let's Encrypt):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Поменять маппинг `nginx` в `docker-compose.prod.yml` с `"80:80"` на `"127.0.0.1:8081:80"`, закрыть 80 порт снаружи и открыть 443 в firewall, и в `/etc/caddy/Caddyfile`:

```
ваш-домен.ру {
    reverse_proxy 127.0.0.1:8081
}
```

```bash
sudo systemctl reload caddy
```

После этого `USE_TLS=True` в `.env` включать уже можно и нужно — перезапустить `django`: `docker compose -f docker-compose.prod.yml up -d --force-recreate django`.

Требует доменного имени (Let's Encrypt не выдаёт сертификаты на голый IP).

## Обновление на новую версию

```bash
cd /opt/restreambyddas
cp docker-compose.prod.yml docker-compose.prod.yml.bak
curl -O https://raw.githubusercontent.com/damodara/RestreamByDDas/master/docker-compose.prod.yml
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

Оба шага обязательны, не только `pull`:

- `pull` — без него `up -d` не подтянет новый образ, если старый уже есть локально.
- Перекачать сам `docker-compose.prod.yml` — новые версии иногда меняют сам файл (новые volume'ы, переменные окружения), а `pull`/`up -d` эти изменения не подхватывают сами — файл на диске обновляется только явным `curl` поверх старого. Если пропустить этот шаг, контейнеры обновятся, но по-прежнему будут работать по старой схеме (например, без свежедобавленного volume) — молча, без ошибки при запуске.

Если правили `docker-compose.prod.yml` вручную (например под свой сервер, как volume'ы `db_data`/`static_data` вместо `postgres_data`/`static_files`) — не затирайте эти правки перекачанным файлом вслепую, сравните `diff docker-compose.prod.yml.bak docker-compose.prod.yml` и перенесите нужное руками.

## Резервное копирование БД

```bash
mkdir -p /opt/restreambyddas/backups
docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U restreambyddas restreambyddas | gzip > /opt/restreambyddas/backups/$(date +%Y%m%d-%H%M%S).sql.gz
```

Для регулярного автоматического бэкапа — обернуть в скрипт и добавить в cron.
