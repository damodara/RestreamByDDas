# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

RestreamByDDas is a Django app for managing RTMP restream targets — i.e. a list of social media destinations (name, viewing URL, RTMP ingest URL, RTMP stream key) that a stream should be pushed to. RTMP ingest/relay is implemented via a separate Docker-built nginx-rtmp component (`nginx/`, `rtmp-push/`) that talks back to Django over HTTP hooks — see Architecture below.

The codebase is a small Django project: an `accounts` app (custom user model + admin-approval registration flow) and a `crud` app (owner-scoped RTMP configuration + the hook endpoints nginx-rtmp calls).

## Product vision (target state)

- **RTMP first, SRT later**: implement RTMP restreaming fully before starting SRT support. Don't build SRT-specific code until RTMP is feature-complete.
- **Non-standard auth (implemented)**: registration is not self-service. A new signup creates an inactive `PENDING` user and emails every `is_staff` user a confirm/reject link (`accounts` app); once an admin decides via that link, the user gets an email with the result. See Architecture below for how this is wired.
- **Per-user restream config (implemented)**: a logged-in user creates any number of `Stream` ingest points, and for each one specifies one or more `Rtmp` restream destinations (typically social media RTMP publish URLs/keys). Each destination has a user-assigned name (`socialmedia_name`). See Architecture below.
- **RTMP ingest + relay (implemented)**: users actually stream in and get relayed out — see Architecture below.
- **Stream lifecycle/ops features**: ability to restart a broadcast, view per-stream statistics, and view overall server load — not built yet (the `push.sh`/`stop.sh` PID-file mechanism is a natural hook point for a future restart feature, but no UI/command uses it yet).
- **Deployment target (implemented locally)**: `docker-compose.yml` wires Django+Postgres+nginx together — see Architecture below. Production hardening (gunicorn instead of `runserver`, TLS, whitenoise) is intentionally not done yet.

## Commands

Dependencies are managed with Poetry; the virtualenv is created in-project at `.venv` (see `poetry.toml`).

```bash
poetry install                                    # install dependencies
poetry run python manage.py runserver             # run the dev server
poetry run python manage.py migrate                # apply migrations
poetry run python manage.py makemigrations <app>   # create a migration after model changes (e.g. crud, accounts)
poetry run python manage.py test                   # run the full test suite
poetry run python manage.py test crud               # run tests for one app only (accounts, crud)
poetry run python manage.py test crud.tests.<TestCase>.<test_method>  # run a single test
poetry run black .                                  # format code (black is a declared dependency)

docker compose up -d --build                        # run the full stack (nginx + django + postgres)
docker compose logs -f django                        # follow Django logs (incl. console-backend emails)
docker compose exec django python manage.py <cmd>    # run a management command inside the container
docker compose down -v                                # stop and wipe compose volumes (postgres data, static files)
```

A `.env` file (see `.env_example` for the required keys) must exist before running any `manage.py` command, since `config/settings.py` loads env vars via `python-dotenv` and reads `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (comma-separated), `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` for PostgreSQL, and optional `EMAIL_*`/`DEFAULT_FROM_EMAIL`/`RTMP_SERVER_HOST`/`RTMP_APP`/`RTMP_HOOK_SECRET` vars (see below). There is no fallback/default DB — Postgres must be reachable for any command that touches models.

**Email in dev**: leave `EMAIL_HOST` unset in `.env` and outgoing mail (registration/approval notices) prints to the console instead of requiring SMTP.

**Note on `AUTH_USER_MODEL`**: it points at `accounts.User`. If you ever need to reset the dev DB after model changes to `accounts`, remember Django cannot swap `AUTH_USER_MODEL` on top of an already-migrated default `auth.User` — drop and recreate the dev database rather than trying to migrate in place.

**One `.env` for both bare-metal and Docker Compose**: values that differ between the two (`DB_HOST`, `ALLOWED_HOSTS`) are overridden per-service in `docker-compose.yml` rather than requiring a second env file — don't add a `DB_HOST=db`/`ALLOWED_HOSTS=...,django` to `.env` itself, that would break plain `manage.py runserver`.

## Architecture

- `config/` — the Django project package: `settings.py`, root `urls.py`, `wsgi.py`/`asgi.py`. `ROOT_URLCONF` points here and includes app URLs under path prefixes (`accounts/`, `crud/`).
- `accounts/` — custom user model and the admin-approval registration flow:
  - `models.py` — `User(AbstractUser)` with `approval_status` (`pending`/`approved`/`rejected`), `approved_at`, `approved_by`. This is `AUTH_USER_MODEL`.
  - `views.py` — `register` creates an inactive `PENDING` user and emails admins; `admin_decision` handles the approve/reject link (GET shows a confirmation page, POST applies the decision) keyed by a signed token from `tokens.py` (`django.core.signing`, no login required to act on the link — the token itself is the credential, `max_age` bounds its lifetime).
  - `emails.py` — sends the three notification emails (new-registration to all `is_staff` users, approved/rejected to the applicant) via `django.core.mail.send_mail` + templates under `accounts/templates/accounts/email/`.
  - Login/logout reuse Django's built-in `auth.views.LoginView`/`LogoutView`; a `PENDING`/`REJECTED` account simply can't log in because `is_active=False` until approved — no custom auth backend needed.
- `crud/` — two-level, owner-scoped RTMP configuration, plus the HTTP hooks nginx-rtmp calls:
  - `models.py` — `Stream` (an ingest point: `owner` FK to `accounts.User`, `name`, unique auto-generated `stream_key`, `publish_url` property built from `settings.RTMP_SERVER_HOST`/`RTMP_APP`); `Rtmp` (a restream destination: `stream` FK to `Stream`, social network name/viewing URL/RTMP link/RTMP key, `push_url` property = link+key joined for ffmpeg).
  - `views.py` (CRUD) — all require login (`@login_required`) and scope queries to the current user (`Stream.objects.filter(owner=request.user)`, `Rtmp` via `stream__owner=request.user`); accessing another user's object returns 404 rather than 403 to avoid leaking existence.
  - `views.py` (RTMP hooks, called by nginx/`rtmp-push`, not browsers) — `on_publish_hook` (`crud:on_publish_hook`) validates a stream_key on publish start (200/403); `stream_destinations_hook` (`crud:stream_destinations_hook`) returns a JSON list of `push_url`s for `rtmp-push/push.sh` to relay to. Both require `?secret=` to match `settings.RTMP_HOOK_SECRET` (empty secret = always reject, fail closed).
- `nginx/` — Docker image for nginx-rtmp (not installable as a stock package; built from `debian:bookworm-slim` + the `libnginx-mod-rtmp` apt package). `nginx/conf/nginx.conf.template` is rendered by `nginx/docker-entrypoint.sh` via `envsubst` (`DJANGO_HOOK_BASE_URL`, `RTMP_HOOK_SECRET` env vars) before nginx starts. Build from the **repo root** (not `nginx/`) so the build context includes `rtmp-push/`: `docker build -f nginx/Dockerfile -t restream-nginx .`. Deliberately `worker_processes 1` — nginx-rtmp connections/stats aren't shared across workers, so `/stat` on a multi-worker setup only reflects whichever worker handled a given request.
- `rtmp-push/` — `push.sh`/`stop.sh`, invoked by nginx-rtmp's `exec_publish`/`exec_publish_done` (not run directly). `push.sh` fetches the destination list from `stream_destinations_hook` and launches one `ffmpeg -c copy` process fanning out to all destinations, tracking its PID in `/tmp/rtmp-push/<stream_key>.pid` for `stop.sh` to kill on publish end. Builds the ffmpeg argv via `set --` rather than `eval`/`sh -c` on purpose — destination URLs/keys come from user input (`Rtmp` fields) and must never be shell-interpreted (command injection).
- Templates live under `<app>/templates/<app>/` following Django's app-namespaced template convention (no shared/base template exists yet).
- `Dockerfile`/`docker-entrypoint.sh` (repo root) — the Django image (`python:3.13-slim` + Poetry, `POETRY_VIRTUALENVS_CREATE=false`). The entrypoint waits for Postgres to accept connections (plain `depends_on` only waits for container start, not DB readiness), then runs `migrate`, `collectstatic`, and `runserver 0.0.0.0:8000`. `.dockerignore` excludes `.env` — never remove that exclusion, `COPY . .` would otherwise bake secrets into the image layer.
- `docker-compose.yml` — `db` (`postgres:16-alpine`, not exposed to the host to avoid clashing with a locally-running Postgres on 5432), `django` (builds the root `Dockerfile`), `nginx` (builds `nginx/Dockerfile`, now also reverse-proxies HTTP: a second `server { listen 80; }` block in `nginx/conf/nginx.conf.template` proxies `/` to `http://django:8000` and serves `/static/` directly from a shared `static_files` volume populated by `collectstatic`). nginx's `on_publish`/`push.sh` hooks reach Django at `http://django:8000` — Django's `ALLOWED_HOSTS` gets `django` appended in compose (see the `.env` note above) since that hostname never appears in the browser-facing `Host` header.

When adding new apps or restream/push functionality, follow the existing pattern: a Django app with its own `urls.py` included from `config/urls.py`, and app-namespaced templates.
