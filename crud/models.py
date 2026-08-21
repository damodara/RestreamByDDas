import secrets

from django.conf import settings
from django.db import models


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
    def publish_url(self):
        if not settings.RTMP_SERVER_HOST:
            return None
        return (
            f"rtmp://{settings.RTMP_SERVER_HOST}/{settings.RTMP_APP}/{self.stream_key}"
        )

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
    socialmedia_rtmp_key = models.CharField(max_length=100, verbose_name="RTMP ключ")

    class Meta:
        unique_together = [("stream", "socialmedia_rtmp_key")]

    def __str__(self):
        return self.socialmedia_name

    @property
    def push_url(self):
        return f"{self.socialmedia_rtmp_link.rstrip('/')}/{self.socialmedia_rtmp_key}"
