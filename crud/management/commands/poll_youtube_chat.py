import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import OperationalError, connection
from django.utils import timezone

from crud.models import ChatMessage, Stream
from crud.nginx_stat import fetch_stream_stats
from crud.youtube_chat import fetch_live_chat_id, fetch_new_messages

logger = logging.getLogger(__name__)

# Как часто проходить по списку стримов с настроенным чатом и проверять,
# не пора ли кому-то из них поллить YouTube снова (у каждого свой интервал,
# см. FALLBACK_INTERVAL/pollingIntervalMillis от самого YouTube).
SCAN_INTERVAL = 2
FALLBACK_INTERVAL = timedelta(seconds=15)


class Command(BaseCommand):
    help = (
        "Бесконечно поллит YouTube live chat для точек приёма с настроенным "
        "youtube_chat_video_id, пока они live. Не завершается сам — один "
        "долгоживущий процесс на весь контейнер (см. docker-entrypoint.sh), "
        "не Celery/cron-задача, как cleanup_destination_logs."
    )

    def handle(self, *args, **options):
        # Состояние в памяти процесса, не в БД: live_chat_id/page_token
        # осмысленны только пока жив этот процесс, восстанавливать их после
        # рестарта не нужно — просто начнём поллинг заново с нуля.
        state = {}
        while True:
            if settings.YOUTUBE_API_KEY:
                try:
                    self._tick(state)
                except OperationalError:
                    logger.warning(
                        "poll_youtube_chat: потеряно соединение с БД, переподключаюсь",
                        exc_info=True,
                    )
                    connection.close()
            time.sleep(SCAN_INTERVAL)

    def _tick(self, state):
        now = timezone.now()
        streams = list(Stream.objects.exclude(youtube_chat_video_id=""))
        active_ids = set()

        for stream in streams:
            active_ids.add(stream.id)
            entry = state.get(stream.id)
            if entry is None or entry["video_id"] != stream.youtube_chat_video_id:
                entry = {
                    "video_id": stream.youtube_chat_video_id,
                    "live_chat_id": None,
                    "page_token": None,
                    "next_poll_at": now,
                }
                state[stream.id] = entry

            if entry["next_poll_at"] > now:
                continue

            stats = fetch_stream_stats(stream.stream_key)
            if not (stats and stats.get("live")):
                entry["next_poll_at"] = now + FALLBACK_INTERVAL
                continue

            if not entry["live_chat_id"]:
                entry["live_chat_id"] = fetch_live_chat_id(entry["video_id"])
                if not entry["live_chat_id"]:
                    entry["next_poll_at"] = now + FALLBACK_INTERVAL
                    continue

            result = fetch_new_messages(entry["live_chat_id"], entry["page_token"])
            if result is None:
                entry["next_poll_at"] = now + FALLBACK_INTERVAL
                continue

            messages, next_page_token, interval_seconds = result
            entry["page_token"] = next_page_token
            entry["next_poll_at"] = now + timedelta(seconds=interval_seconds)

            for message in messages:
                ChatMessage.objects.get_or_create(
                    stream=stream,
                    platform=ChatMessage.Platform.YOUTUBE,
                    external_id=message["external_id"],
                    defaults={
                        "author_name": message["author_name"],
                        "text": message["text"],
                        "posted_at": message["posted_at"],
                    },
                )

        for stale_id in set(state) - active_ids:
            del state[stale_id]
