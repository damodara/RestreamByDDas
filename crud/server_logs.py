from pathlib import Path

from django.conf import settings

MAX_LINES = 500

# Общий read-only volume с контейнером nginx (server_logs, см.
# docker-compose.yml) — тот же принцип, что и LOGS_ROOT в
# destination_logs.py: снаружи Docker этого пути просто нет (bare-metal
# dev вообще не поднимает nginx-rtmp), так что чтение штатно вернёт None.
NGINX_LOG_PATH = Path("/server-logs/nginx-error.log")

# Пишется один раз при старте контейнера nginx (docker-entrypoint.sh) —
# только worker_processes, не весь nginx.conf (там RTMP_HOOK_SECRET прямо
# в URL хуков). Больше одного воркера — самая частая причина, по которой
# /stat и /control ведут себя непоследовательно (см. nginx.conf.template).
NGINX_CONFIG_INFO_PATH = Path("/server-logs/nginx-config-info.txt")


def _tail(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    return "\n".join(lines[-MAX_LINES:])


def read_nginx_log():
    return _tail(NGINX_LOG_PATH)


def read_nginx_config_info():
    try:
        text = NGINX_CONFIG_INFO_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text.strip() or None


def read_django_log():
    # В отличие от NGINX_LOG_PATH, путь настраиваемый (settings.SERVER_LOG_DIR) —
    # Django сам пишет и сам же читает этот файл в любом окружении (bare-metal
    # или Docker), в отличие от лога nginx, который приезжает только по volume.
    return _tail(Path(settings.SERVER_LOG_DIR) / "django.log")
