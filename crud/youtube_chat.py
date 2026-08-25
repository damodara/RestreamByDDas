import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"


def _get(path, params):
    url = f"{API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        logger.warning("youtube_chat: запрос к %s не удался", path, exc_info=True)
        return None


def fetch_live_chat_id(video_id):
    """ID активного live-чата для видео, или None (нет ключа, видео не live,
    у трансляции выключен чат, сетевая ошибка — все случаи неразличимы для
    вызывающего кода одинаково: "чат сейчас недоступен")."""
    if not settings.YOUTUBE_API_KEY or not video_id:
        return None
    data = _get(
        "videos",
        {
            "part": "liveStreamingDetails",
            "id": video_id,
            "key": settings.YOUTUBE_API_KEY,
        },
    )
    if not data:
        return None
    items = data.get("items") or []
    if not items:
        return None
    return items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")


def fetch_new_messages(live_chat_id, page_token=None):
    """Возвращает (messages, next_page_token, polling_interval_seconds) —
    messages это список {external_id, author_name, text, posted_at}.
    None вместо кортежа при ошибке/недоступности API."""
    if not settings.YOUTUBE_API_KEY:
        return None
    params = {
        "liveChatId": live_chat_id,
        "part": "snippet,authorDetails",
        "key": settings.YOUTUBE_API_KEY,
    }
    if page_token:
        params["pageToken"] = page_token
    data = _get("liveChat/messages", params)
    if data is None:
        return None

    messages = []
    for item in data.get("items", []):
        snippet = item.get("snippet") or {}
        author = item.get("authorDetails") or {}
        posted_at = (
            parse_datetime(snippet.get("publishedAt", ""))
            if snippet.get("publishedAt")
            else None
        )
        text = snippet.get("displayMessage")
        if not (item.get("id") and text and posted_at):
            continue
        messages.append(
            {
                "external_id": item["id"],
                "author_name": author.get("displayName", "?"),
                "text": text,
                "posted_at": posted_at,
            }
        )

    next_page_token = data.get("nextPageToken")
    polling_interval_ms = data.get("pollingIntervalMillis", 5000)
    return messages, next_page_token, max(polling_interval_ms / 1000, 2)
