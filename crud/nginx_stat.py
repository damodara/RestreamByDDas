import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from django.conf import settings


def fetch_stream_stats(stream_key):
    if not settings.NGINX_STAT_URL:
        return None

    try:
        with urllib.request.urlopen(settings.NGINX_STAT_URL, timeout=2) as response:
            root = ET.fromstring(response.read())
    except (urllib.error.URLError, OSError, ET.ParseError):
        return None

    for stream in root.findall("./server/application/live/stream"):
        name = stream.findtext("name")
        if name != stream_key:
            continue
        return {
            "live": True,
            "bytes_in": int(stream.findtext("bytes_in", "0")),
            "bytes_out": int(stream.findtext("bytes_out", "0")),
            "bw_in": int(stream.findtext("bw_in", "0")),
            "bw_out": int(stream.findtext("bw_out", "0")),
            "uptime_seconds": int(stream.findtext("time", "0")) // 1000,
        }

    return {"live": False}
