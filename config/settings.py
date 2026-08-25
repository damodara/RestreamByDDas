import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/
load_dotenv(override=True)
SECRET_KEY = os.getenv("SECRET_KEY")

# Ключ шифрования RTMP-ключей дестинаций (crud.fields.EncryptedCharField) —
# отдельный от SECRET_KEY намеренно: ротация/компрометация одного не должна
# требовать трогать другой. Сгенерировать: `Fernet.generate_key()`.
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY")

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "crud.apps.CrudConfig",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "ru"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Хэш содержимого в имени файла (style.css -> style.<hash>.css) — при каждом
# изменении CSS/JS у файла новый URL, так что браузерный кэш никогда не
# отдаёт устаревшую версию после деплоя/пересборки.
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}


# Auth
# https://docs.djangoproject.com/en/6.0/topics/auth/default/

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "crud:index"
LOGOUT_REDIRECT_URL = "accounts:login"


# Email
# https://docs.djangoproject.com/en/6.0/topics/email/
# Без EMAIL_HOST письма просто печатаются в консоль — удобно для разработки
# и для контейнера, в котором SMTP ещё не настроен.

EMAIL_HOST = os.getenv("EMAIL_HOST")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "webmaster@localhost")


# RTMP
# Публичный адрес сервера приёма RTMP-потоков — используется только для
# отображения ссылки на публикацию пользователю (задаётся вручную в .env,
# т.к. это внешний адрес, а не внутренний compose-хост).

RTMP_SERVER_HOST = os.getenv("RTMP_SERVER_HOST", "")
RTMP_APP = os.getenv("RTMP_APP", "live")

# Общий секрет, которым вся наша инфраструктура (nginx-rtmp on_publish,
# rtmp-push/push.sh, MediaMTX authHTTPAddress) подтверждает Django, что
# запрос пришёл от неё. Пустое значение = хуки всегда отказывают (fail closed).
RTMP_HOOK_SECRET = os.getenv("RTMP_HOOK_SECRET", "")

# Откуда брать /stat nginx-rtmp для статистики потоков. Пусто = статистика
# недоступна (например, в голом dev без поднятого nginx-контейнера).
NGINX_STAT_URL = os.getenv("NGINX_STAT_URL", "")

# Базовый URL control-модуля nginx-rtmp (без /control/...) для рестарта
# трансляции. Пусто = рестарт недоступен.
NGINX_CONTROL_URL = os.getenv("NGINX_CONTROL_URL", "")

# SRT
# Публичный адрес и порт SRT-шлюза (MediaMTX) — тот же принцип, что и у
# RTMP_SERVER_HOST: задаётся вручную в .env, не переопределяется в compose.

SRT_SERVER_HOST = os.getenv("SRT_SERVER_HOST", "")
SRT_PORT = os.getenv("SRT_PORT", "8890")

# Multi-chat (YouTube)
# Собственный API-ключ проекта в Google Cloud Console (YouTube Data API v3
# включена) — не OAuth пользователя: чтение публичного чата трансляции не
# требует авторизации от лица зрителя/владельца канала, достаточно ключа.
# Пусто = чтение чата недоступно, poll_youtube_chat просто ничего не делает
# (тот же fail-soft паттерн, что у NGINX_STAT_URL/NGINX_CONTROL_URL).
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


# Security
# Отдельный флаг от DEBUG намеренно: TLS в этом проекте (см. CLAUDE.md) пока
# не настроен даже для docker-compose — если завязать secure-cookies/HSTS
# на одно только DEBUG=False, кто-то может выключить DEBUG раньше, чем
# появится TLS, и тихо сломать себе логин (браузер не отправит cookie с
# флагом Secure по http://) или устроить редирект-петлю на несуществующий
# https. Включать явно, только когда TLS реально терминируется.
USE_TLS = os.getenv("USE_TLS", "False") == "True"
if USE_TLS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Не зависит от TLS — можно включать всегда.
SECURE_CONTENT_TYPE_NOSNIFF = True


# Logging
# Раньше сбои интеграций с nginx-rtmp (недоступен /stat, недоступен
# /control) молча проглатывались (except -> return None/False) — теперь они
# хотя бы попадают в лог как WARNING, вместо того чтобы искать причину через
# "почему статистика не грузится" без единой зацепки.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
