from django.contrib import admin

from crud.models import Rtmp, Stream


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "stream_key", "created_at")


@admin.register(Rtmp)
class RtmpAdmin(admin.ModelAdmin):
    list_display = ("socialmedia_name", "stream", "socialmedia_url", "enabled")
    list_filter = ("enabled",)
