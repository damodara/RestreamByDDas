"""Экспорт/импорт точек приёма и дестинаций пользователя как JSON —
персональный бэкап на случай потери БД (например, неправильно
настроенный volume Postgres на самодельном деплое), а не общий дамп
всего проекта и не механизм передачи настроек между пользователями:
владелец при импорте всегда — тот, кто импортирует, не тот, что был в
файле на момент экспорта (в файле имя владельца вообще не хранится)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from crud.models import Rtmp, Stream

CONFIG_FORMAT = "restreambyddas-config-v1"


class ConfigImportError(Exception):
    """Текст исключения уходит прямо в форму (ConfigImportForm.config_file),
    поэтому формулируется по-человечески, а не как трейсбек."""


def build_export(owner):
    streams = (
        Stream.objects.filter(owner=owner)
        .prefetch_related("destinations")
        .order_by("id")
    )
    return {
        "format": CONFIG_FORMAT,
        "exported_at": timezone.now().isoformat(),
        "streams": [
            {
                "name": stream.name,
                "stream_key": stream.stream_key,
                "youtube_chat_video_id": stream.youtube_chat_video_id,
                "destinations": [
                    {
                        "socialmedia_name": destination.socialmedia_name,
                        "socialmedia_url": destination.socialmedia_url,
                        "socialmedia_rtmp_link": destination.socialmedia_rtmp_link,
                        # Настоящий credential в открытом виде — осознанно
                        # (см. обсуждение в CLAUDE.md/памяти сессии): иначе
                        # восстановление требовало бы вручную вбивать ключи
                        # каждой площадки заново. Предупреждение об этом —
                        # в crud/templates/crud/config_import.html.
                        "socialmedia_rtmp_key": destination.socialmedia_rtmp_key,
                        "enabled": destination.enabled,
                    }
                    for destination in stream.destinations.all()
                ],
            }
            for stream in streams
        ],
    }


def import_config(owner, payload):
    """Создаёт новые Stream/Rtmp под owner из payload (формат — см.
    build_export выше). Никогда не трогает и не удаляет уже существующие
    записи пользователя — повторный импорт того же файла просто даст
    дубликаты, а не потерю данных, это безопаснее умолчание для
    восстановительного сценария. Вся операция — одной транзакцией:
    наполовину прошедший импорт (часть потоков создалась, часть упала на
    валидации) читался бы куда хуже явного отказа целиком."""
    if not isinstance(payload, dict) or payload.get("format") != CONFIG_FORMAT:
        raise ConfigImportError(
            "Неизвестный формат файла — нужен файл, скачанный через "
            "«Экспортировать настройки» этой же версии приложения."
        )
    streams_data = payload.get("streams")
    if not isinstance(streams_data, list):
        raise ConfigImportError("В файле нет списка точек приёма.")

    streams_created = 0
    destinations_created = 0
    regenerated_stream_names = []

    with transaction.atomic():
        for stream_data in streams_data:
            if not isinstance(stream_data, dict):
                raise ConfigImportError("Точка приёма в файле имеет неверный формат.")

            stream = Stream(
                owner=owner,
                name=stream_data.get("name") or "Без названия",
                youtube_chat_video_id=stream_data.get("youtube_chat_video_id") or "",
            )
            requested_key = stream_data.get("stream_key")
            if requested_key:
                if Stream.objects.filter(stream_key=requested_key).exists():
                    # Ключ уже занят (своим или чужим потоком — stream_key
                    # уникален глобально, не в рамках владельца) — оставляем
                    # автосгенерированный дефолт (Stream.stream_key) вместо
                    # падения на unique-констрейнте при save().
                    regenerated_stream_names.append(stream.name)
                else:
                    stream.stream_key = requested_key
            try:
                stream.full_clean(exclude=["stream_key"])
            except ValidationError as exc:
                raise ConfigImportError(
                    f"Точка приёма «{stream.name}»: {'; '.join(exc.messages)}"
                ) from exc
            stream.save()
            streams_created += 1

            for dest_data in stream_data.get("destinations") or []:
                if not isinstance(dest_data, dict):
                    raise ConfigImportError(
                        f"Дестинация в потоке «{stream.name}» имеет неверный формат."
                    )
                destination = Rtmp(
                    stream=stream,
                    socialmedia_name=dest_data.get("socialmedia_name") or "",
                    socialmedia_url=dest_data.get("socialmedia_url") or "",
                    socialmedia_rtmp_link=dest_data.get("socialmedia_rtmp_link") or "",
                    socialmedia_rtmp_key=dest_data.get("socialmedia_rtmp_key") or "",
                    enabled=bool(dest_data.get("enabled", True)),
                )
                try:
                    destination.full_clean()
                except ValidationError as exc:
                    raise ConfigImportError(
                        f"Дестинация «{destination.socialmedia_name}» "
                        f"в потоке «{stream.name}»: {'; '.join(exc.messages)}"
                    ) from exc
                destination.save()
                destinations_created += 1

    return {
        "streams_created": streams_created,
        "destinations_created": destinations_created,
        "regenerated_stream_names": regenerated_stream_names,
    }
