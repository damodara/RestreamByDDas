import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


def restart_stream(stream_key):
    """Отключает текущего публикующего клиента потока — если он сам
    переподключается (как это делает большинство энкодеров, включая OBS),
    приём и релей на destination-ы запускаются заново с чистого листа."""
    if not settings.NGINX_CONTROL_URL:
        return False

    query = urllib.parse.urlencode({"app": settings.RTMP_APP, "name": stream_key})
    url = f"{settings.NGINX_CONTROL_URL}/control/drop/publisher?{query}"

    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError):
        return False
