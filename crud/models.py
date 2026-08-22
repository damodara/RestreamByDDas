import secrets

from django.conf import settings
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
    # проверяется в DestinationForm после расшифровки.
    socialmedia_rtmp_key = EncryptedCharField(max_length=500, verbose_name="RTMP ключ")

    def __str__(self):
        return self.socialmedia_name

    @property
    def push_url(self):
        return f"{self.socialmedia_rtmp_link.rstrip('/')}/{self.socialmedia_rtmp_key}"
