import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, connection

from accounts.models import User
from accounts.telegram_bot import get_updates, send_message
from accounts.tokens import read_telegram_link_token

logger = logging.getLogger(__name__)

# Пока токен бота не задан — не поллим вообще, просто ждём: без этого
# get_updates() возвращал бы [] мгновенно (см. accounts.telegram_bot._call)
# и цикл превратился бы в busy-loop, жгущий CPU впустую.
IDLE_SLEEP_SECONDS = 30


class Command(BaseCommand):
    help = (
        "Бесконечно поллит Telegram Bot API (long polling, getUpdates) и "
        "привязывает chat_id аккаунта по команде /start <токен> из "
        "личного кабинета. Один долгоживущий процесс на контейнер (см. "
        "docker-entrypoint.sh), тот же принцип, что и poll_youtube_chat — "
        "не завершается сам."
    )

    def handle(self, *args, **options):
        offset = 0
        while True:
            if not settings.TELEGRAM_BOT_TOKEN:
                time.sleep(IDLE_SLEEP_SECONDS)
                continue
            for update in get_updates(offset):
                offset = max(offset, update["update_id"] + 1)
                try:
                    self._handle_update(update)
                except OperationalError:
                    logger.warning(
                        "poll_telegram_bot: потеряно соединение с БД, "
                        "переподключаюсь",
                        exc_info=True,
                    )
                    connection.close()

    def _handle_update(self, update):
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not chat_id or not text.startswith("/start"):
            return

        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            send_message(
                chat_id,
                "Перейдите по ссылке из личного кабинета RestreamByDDas, "
                "чтобы подключить Telegram.",
            )
            return

        user_id = read_telegram_link_token(parts[1])
        if user_id is None:
            send_message(
                chat_id,
                "Ссылка для подключения устарела — обновите её в личном "
                "кабинете и попробуйте снова.",
            )
            return

        updated = User.objects.filter(pk=user_id).update(telegram_chat_id=str(chat_id))
        if updated:
            send_message(
                chat_id, "Telegram подключён к вашему аккаунту RestreamByDDas."
            )
