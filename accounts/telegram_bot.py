import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _call(method, params, request_timeout=10):
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    url = f"{API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(
            url, data=data, timeout=request_timeout
        ) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        logger.warning("telegram_bot: запрос %s не удался", method, exc_info=True)
        return None


def send_message(chat_id, text):
    """True при успехе, False иначе (нет токена, сеть недоступна, чат
    заблокировал бота и т.п.) — fail-soft тем же принципом, что и у
    остальных внешних интеграций проекта (nginx_stat/nginx_control)."""
    result = _call("sendMessage", {"chat_id": chat_id, "text": text})
    return bool(result and result.get("ok"))


def get_updates(offset, timeout=25):
    """Long polling — держит соединение открытым до timeout секунд на
    стороне Telegram или до появления апдейта, так что не нужно опрашивать
    чаще самим. request_timeout клиента чуть больше серверного timeout,
    чтобы не оборвать соединение раньше, чем ответит сам Telegram.
    Возвращает [] и при отсутствии апдейтов, и при ошибке — вызывающий код
    (poll_telegram_bot) не отличает эти случаи, в обоих просто повторяет
    попытку на следующей итерации."""
    result = _call(
        "getUpdates",
        {"offset": offset, "timeout": timeout},
        request_timeout=timeout + 10,
    )
    if not result or not result.get("ok"):
        return []
    return result.get("result", [])
