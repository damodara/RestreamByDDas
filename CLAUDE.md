# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

RestreamByDDas is an early-stage Django app for managing RTMP restream targets — i.e. a list of social media destinations (name, viewing URL, RTMP ingest URL, RTMP stream key) that a stream should be pushed to. The `nginx/` and `rtmp-push/` directories exist but are currently empty — they are placeholders for the actual restreaming infrastructure (likely an nginx-rtmp module config and a push/relay component) that has not been built yet.

The codebase is a small Django project: an `accounts` app (custom user model + admin-approval registration flow) and a `crud` app (RTMP restream targets) with mostly stubbed-out views. Expect a lot of scaffolding rather than finished features.

## Product vision (target state)

- **RTMP first, SRT later**: implement RTMP restreaming fully before starting SRT support. Don't build SRT-specific code until RTMP is feature-complete.
- **Non-standard auth (implemented)**: registration is not self-service. A new signup creates an inactive `PENDING` user and emails every `is_staff` user a confirm/reject link (`accounts` app); once an admin decides via that link, the user gets an email with the result. See Architecture below for how this is wired.
- **Per-user restream config (not yet built)**: a logged-in user creates any number of RTMP ingest points, and for each one specifies one or more restream destinations (typically social media RTMP publish URLs/keys — this is what the `Rtmp` model already models, via `socialmedia_name`/`socialmedia_url`/`socialmedia_rtmp_link`/`socialmedia_rtmp_key`). Each destination needs a user-assigned name. `Rtmp` does not yet have an owner FK to `accounts.User` — that link-up is the next step once auth was in place.
- **Stream lifecycle/ops features**: ability to restart a broadcast, view per-stream statistics, and view overall server load — none of this exists yet.
- **Deployment target**: the app is meant to ship as a Docker image so it can be installed on a Debian server via Docker. No Dockerfile/compose setup exists yet — when adding infra pieces (nginx-rtmp, mail sending, background jobs), favor approaches that containerize cleanly.

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
```

A `.env` file (see `.env_example` for the required keys) must exist before running any `manage.py` command, since `config/settings.py` loads env vars via `python-dotenv` and reads `SECRET_KEY`, `DEBUG`, `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` for PostgreSQL, and optional `EMAIL_*`/`DEFAULT_FROM_EMAIL` vars (see below). There is no fallback/default DB — Postgres must be reachable for any command that touches models.

**Email in dev**: leave `EMAIL_HOST` unset in `.env` and outgoing mail (registration/approval notices) prints to the console instead of requiring SMTP.

**Note on `AUTH_USER_MODEL`**: it points at `accounts.User`. If you ever need to reset the dev DB after model changes to `accounts`, remember Django cannot swap `AUTH_USER_MODEL` on top of an already-migrated default `auth.User` — drop and recreate the dev database rather than trying to migrate in place.

## Architecture

- `config/` — the Django project package: `settings.py`, root `urls.py`, `wsgi.py`/`asgi.py`. `ROOT_URLCONF` points here and includes app URLs under path prefixes (`accounts/`, `crud/`).
- `accounts/` — custom user model and the admin-approval registration flow:
  - `models.py` — `User(AbstractUser)` with `approval_status` (`pending`/`approved`/`rejected`), `approved_at`, `approved_by`. This is `AUTH_USER_MODEL`.
  - `views.py` — `register` creates an inactive `PENDING` user and emails admins; `admin_decision` handles the approve/reject link (GET shows a confirmation page, POST applies the decision) keyed by a signed token from `tokens.py` (`django.core.signing`, no login required to act on the link — the token itself is the credential, `max_age` bounds its lifetime).
  - `emails.py` — sends the three notification emails (new-registration to all `is_staff` users, approved/rejected to the applicant) via `django.core.mail.send_mail` + templates under `accounts/templates/accounts/email/`.
  - Login/logout reuse Django's built-in `auth.views.LoginView`/`LogoutView`; a `PENDING`/`REJECTED` account simply can't log in because `is_active=False` until approved — no custom auth backend needed.
- `crud/` — holds the `Rtmp` model (social network name, viewing URL, RTMP link, RTMP key) and CRUD-style views/urls (`index`, `create`, `read`, `update`, `delete`). Most of these views are still placeholder `HttpResponse` stubs, not full implementations — check `crud/views.py` before assuming a route is functional. `Rtmp` has no owner FK yet (see Product vision).
- Templates live under `<app>/templates/<app>/` following Django's app-namespaced template convention (no shared/base template exists yet).

When adding new apps or restream/push functionality, follow the existing pattern: a Django app with its own `urls.py` included from `config/urls.py`, and app-namespaced templates.
