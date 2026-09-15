import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from django.conf import settings

logger = logging.getLogger(__name__)


def fetch_stream_stats(stream_key):
    if not settings.NGINX_STAT_URL:
        return None

    try:
        with urllib.request.urlopen(settings.NGINX_STAT_URL, timeout=2) as response:
            root = ET.fromstring(response.read())
    except (urllib.error.URLError, OSError, ET.ParseError):
        logger.warning(
            "fetch_stream_stats: не удалось получить/разобрать %s",
            settings.NGINX_STAT_URL,
            exc_info=True,
        )
        return None

    for stream in root.findall("./server/application/live/stream"):
        name = stream.findtext("name")
        if name != stream_key:
            continue
        result = {
            "live": True,
            "bytes_in": int(stream.findtext("bytes_in", "0")),
            "bytes_out": int(stream.findtext("bytes_out", "0")),
            "bw_in": int(stream.findtext("bw_in", "0")),
            "bw_out": int(stream.findtext("bw_out", "0")),
            "uptime_seconds": int(stream.findtext("time", "0")) // 1000,
        }
        result.update(_parse_meta(stream.find("meta")))
        return result

    return {"live": False}


def fetch_live_stream_keys():
    """Множество stream_key всех сейчас live потоков — один запрос к /stat
    вместо N (по одному на каждую точку приёма пользователя), которые
    fetch_stream_stats(key) делал бы, если звать его в цикле по списку
    стримов на index. Возвращает None, если /stat недоступен (тот же
    fail-soft, что и у fetch_stream_stats)."""
    if not settings.NGINX_STAT_URL:
        return None

    try:
        with urllib.request.urlopen(settings.NGINX_STAT_URL, timeout=2) as response:
            root = ET.fromstring(response.read())
    except (urllib.error.URLError, OSError, ET.ParseError):
        logger.warning(
            "fetch_live_stream_keys: не удалось получить/разобрать %s",
            settings.NGINX_STAT_URL,
            exc_info=True,
        )
        return None

    return {
        stream.findtext("name")
        for stream in root.findall("./server/application/live/stream")
        if stream.findtext("name")
    }


def fetch_raw_stat():
    """Сырой XML /stat как его отдал nginx-rtmp, без парсинга — для
    crud:server_logs. Разобранные fetch_stream_stats/fetch_live_stream_keys
    отвечают на вопрос "жив ли КОНКРЕТНЫЙ поток", а не показывают, что
    nginx-rtmp думает целиком: этого достаточно, пока /stat врёт
    консистентно, но если у nginx несколько worker_processes (у /stat
    нет общего состояния между воркерами — см. nginx.conf.template),
    расхождение видно только на сырых данных, не в одном булевом флаге."""
    if not settings.NGINX_STAT_URL:
        return None

    try:
        with urllib.request.urlopen(settings.NGINX_STAT_URL, timeout=2) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        logger.warning(
            "fetch_raw_stat: не удалось получить %s",
            settings.NGINX_STAT_URL,
            exc_info=True,
        )
        return None


def _parse_meta(meta):
    """Технические параметры входящего потока — nginx-rtmp узнаёт их из
    onMetaData/заголовков кодека самого потока, не от нас, так что блок
    <meta> может на секунду-другую отсутствовать сразу после начала
    публикации, пока nginx их не разобрал. Ключи отсутствуют в
    результате (не None), если meta целиком нет — шаблон/JS одинаково
    решают "нечего показывать" что для отсутствующего ключа, что для None."""
    if meta is None:
        return {}

    parsed = {}
    video = meta.find("video")
    if video is not None:
        parsed["video_width"] = video.findtext("width")
        parsed["video_height"] = video.findtext("height")
        parsed["video_frame_rate"] = video.findtext("frame_rate")
        parsed["video_codec"] = video.findtext("codec")

    audio = meta.find("audio")
    if audio is not None:
        parsed["audio_codec"] = audio.findtext("codec")
        parsed["audio_channels"] = audio.findtext("channels")
        parsed["audio_sample_rate"] = audio.findtext("sample_rate")

    return parsed
