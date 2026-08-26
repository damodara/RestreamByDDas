import logging
import subprocess

logger = logging.getLogger(__name__)

# Длительность синтетического ролика, который реально льём в destination —
# достаточно короткая, чтобы не выглядеть как настоящий эфир для площадки,
# но чтобы RTMP-хендшейк успел пройти целиком.
TEST_PUSH_DURATION_SECONDS = 3
# С запасом сверх TEST_PUSH_DURATION_SECONDS — ffmpeg должен успеть ещё
# и установить соединение, а не только пролить сам ролик.
TEST_PUSH_TIMEOUT_SECONDS = 15


def test_push(push_url):
    """Шлёт короткий синтетический ролик (testsrc + тишина) в push_url через
    ffmpeg — проверяет, что RTMP-адрес и ключ рабочие, без реального эфира
    от пользователя. Аргументы идут списком в subprocess (не через shell) —
    push_url собран из пользовательского ввода (Rtmp.socialmedia_rtmp_link/
    _key), и он не должен проходить shell-интерпретацию, тем же принципом,
    что и в rtmp-push/push.sh."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=15",
        "-f",
        "lavfi",
        "-i",
        "anullsrc",
        "-t",
        str(TEST_PUSH_DURATION_SECONDS),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-f",
        "flv",
        push_url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=TEST_PUSH_TIMEOUT_SECONDS,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, "Не удалось подключиться — истекло время ожидания."
    except FileNotFoundError:
        logger.error("test_push: ffmpeg не найден в контейнере")
        return False, "ffmpeg недоступен на сервере."

    if result.returncode == 0:
        return True, "Площадка приняла тестовый поток."

    error_line = next(
        (line for line in reversed(result.stderr.splitlines()) if line.strip()), ""
    )
    return False, error_line or "Площадка отклонила подключение."
