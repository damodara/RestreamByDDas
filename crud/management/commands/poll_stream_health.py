import logging
import time

from django.core.management.base import BaseCommand
from django.db import OperationalError, connection

from crud.emails import send_stream_drop_email
from crud.models import Stream
from crud.nginx_stat import fetch_live_stream_keys
from crud.telegram_alerts import send_stream_drop_telegram

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 30


class Command(BaseCommand):
    help = (
        "Раз в SCAN_INTERVAL секунд сверяет потоки с Stream.expected_live="
        "True (см. crud.views.on_publish_hook/stream_end_broadcast) с "
        "реальным списком live stream_key из nginx-rtmp /stat — расхождение "
        "значит, что публикация оборвалась без явного «Завершить эфир», и "
        "владельца стоит уведомить, если только он не включил "
        "accounts.User.auto_end_broadcast_on_drop (тогда флаг просто "
        "сбрасывается молча). Тот же долгоживущий процесс, что и "
        "poll_youtube_chat/poll_telegram_bot (см. docker-entrypoint.sh), не "
        "завершается сам."
    )

    def handle(self, *args, **options):
        while True:
            try:
                self._tick()
            except OperationalError:
                logger.warning(
                    "poll_stream_health: потеряно соединение с БД, переподключаюсь",
                    exc_info=True,
                )
                connection.close()
            time.sleep(SCAN_INTERVAL)

    def _tick(self):
        live_keys = fetch_live_stream_keys()
        if live_keys is None:
            # /stat недоступен — не то же самое, что "все потоки реально
            # пропали"; молчим, а не шлём ложную тревогу всем сразу.
            return

        dropped = list(
            Stream.objects.filter(expected_live=True)
            .exclude(stream_key__in=live_keys)
            .select_related("owner")
        )
        for stream in dropped:
            owner = stream.owner
            # auto_end_broadcast_on_drop — пользователь сам решил, что для
            # него пропадание сигнала само по себе уже значит "эфир
            # закончился", а не "инцидент": флаг ниже всё равно сбрасывается,
            # просто без уведомления.
            if owner.auto_end_broadcast_on_drop:
                continue
            if owner.notify_on_push_error:
                send_stream_drop_email(stream)
            if owner.notify_telegram_on_push_error:
                send_stream_drop_telegram(stream)

        if dropped:
            # Отдельным запросом по уже собранным pk, а не dropped.update() —
            # тот же queryset при повторном вычислении мог бы зацепить
            # строки, которые успели измениться между SELECT и UPDATE
            # (например, новый on_publish_hook только что вернул поток в
            # эфир) и сбросить только что выставленный expected_live=True.
            Stream.objects.filter(pk__in=[stream.pk for stream in dropped]).update(
                expected_live=False
            )
