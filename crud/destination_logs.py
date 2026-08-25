from pathlib import Path

# Общий read-only volume с контейнером nginx — см. docker-compose.yml/
# docker-compose.prod.yml. rtmp-push/push.sh пишет туда
# <stream_key>/<destination_id>.log (именно по id дестинации, не по
# позиции в списке — стабильный ключ, не зависящий от порядка/состава
# дестинаций на момент конкретной публикации).
LOGS_ROOT = Path("/rtmp-logs")

MAX_LINES = 500


def read_destination_log(stream_key, destination_id):
    """Возвращает последние MAX_LINES строк лога ffmpeg для этой дестинации,
    либо None, если публикации с этой дестинацией ещё не было (файла нет) —
    например volume недоступен вне Docker (bare-metal dev, см. README)."""
    log_path = LOGS_ROOT / stream_key / f"{destination_id}.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    return "\n".join(lines[-MAX_LINES:])
