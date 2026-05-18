from django.db import models


class Rtmp(models.Model):
    socialmedia_name = models.CharField(
        max_length=100, verbose_name="Название соц сети для рестрима"
    )
    socialmedia_url = models.URLField(verbose_name="Адрес для просмотра")
    socialmedia_rtmp_link = models.CharField(max_length=100, verbose_name="RTMP адрес")
    socialmedia_rtmp_key = models.CharField(
        max_length=100, verbose_name="RTMP ключ", unique=True
    )
