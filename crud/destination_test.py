import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor

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


def test_push_many(push_urls_by_id):
    """push_urls_by_id: {destination_id: push_url}. Возвращает
    {destination_id: (success, detail)} — запускает test_push для всех
    дестинаций ПАРАЛЛЕЛЬНО потоками, а не по очереди: subprocess.run
    отпускает GIL на время ожидания ffmpeg, так что общее время проверки
    ограничено TEST_PUSH_TIMEOUT_SECONDS одной проверки, а не их суммой по
    всем дестинациям потока."""
    if not push_urls_by_id:
        return {}
    with ThreadPoolExecutor(max_workers=len(push_urls_by_id)) as executor:
        futures = {
            destination_id: executor.submit(test_push, push_url)
            for destination_id, push_url in push_urls_by_id.items()
        }
        return {
            destination_id: future.result()
            for destination_id, future in futures.items()
        }
