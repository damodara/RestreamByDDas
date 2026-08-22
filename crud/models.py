import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from crud.fields import EncryptedCharField


def generate_stream_key():
    return secrets.token_urlsafe(16)


class Stream(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="streams", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100, verbose_name="Название точки приёма")
    stream_key = models.CharField(
        max_length=64, unique=True, editable=False, default=generate_stream_key
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def publish_server(self):
        # Без ключа — большинство энкодеров (OBS и т.п.) просят "Server" и
        # "Stream Key" как два отдельных поля, а не единую строку.
        if not settings.RTMP_SERVER_HOST:
            return None
        return f"rtmp://{settings.RTMP_SERVER_HOST}/{settings.RTMP_APP}"

    @property
    def srt_publish_url(self):
        if not settings.SRT_SERVER_HOST:
            return None
        return (
            f"srt://{settings.SRT_SERVER_HOST}:{settings.SRT_PORT}"
            f"?streamid=publish:{self.stream_key}"
        )


class Rtmp(models.Model):
    stream = models.ForeignKey(
        Stream, related_name="destinations", on_delete=models.CASCADE
    )
    socialmedia_name = models.CharField(
        max_length=100, verbose_name="Название соц сети для рестрима"
    )
    socialmedia_url = models.URLField(verbose_name="Адрес для просмотра")
    socialmedia_rtmp_link = models.CharField(max_length=100, verbose_name="RTMP адрес")
    # Зашифровано at rest (Fernet, см. crud/fields.py) — это реальный
    # credential площадки, а не идентификатор. Не детерминировано, поэтому
    # без DB-level unique/filter по значению — уникальность в рамках Stream
    # проверяется в clean() ниже, расшифровкой и сравнением в Python.
    socialmedia_rtmp_key = EncryptedCharField(max_length=500, verbose_name="RTMP ключ")

    class PushStatus(models.TextChoices):
        UNKNOWN = "unknown", "—"
        LIVE = "live", "В эфире"
        ERROR = "error", "Ошибка"
        STOPPED = "stopped", "Остановлено"

    # Обновляется push.sh через destination_status_hook, а не считается на
    # лету — в отличие от статуса самого потока (nginx-rtmp /stat, см.
    # nginx_stat.py), у Django нет способа заглянуть в /tmp/rtmp-push
    # nginx-контейнера, чтобы проверить состояние push-процесса напрямую.
    # Может быть устаревшим, если nginx упал грубо, не успев отрапортовать
    # "stopped"/"error" — stream_detail.html подстраховывается, показывая
    # это поле только пока сам поток live по /stat.
    push_status = models.CharField(
        max_length=10, choices=PushStatus.choices, default=PushStatus.UNKNOWN
    )
    push_status_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.socialmedia_name

    def clean(self):
        # На уровне модели, а не только в DestinationForm — иначе, например,
        # Django admin (у него своя автосгенерированная ModelForm, наш
        # DestinationForm не используется) вообще не видит эту проверку и
        # молча создаёт дубликаты (подтверждено живьём).
        if self.stream_id is None:
            return
        siblings = Rtmp.objects.filter(stream_id=self.stream_id)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        if any(s.socialmedia_rtmp_key == self.socialmedia_rtmp_key for s in siblings):
            raise ValidationError(
                {
                    "socialmedia_rtmp_key": "Такой RTMP-ключ уже используется "
                    "в этой точке приёма."
                }
            )

    @property
    def push_url(self):
        return f"{self.socialmedia_rtmp_link.rstrip('/')}/{self.socialmedia_rtmp_key}"
