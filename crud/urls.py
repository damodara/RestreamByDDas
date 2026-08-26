from django.urls import path

from crud import views

app_name = "crud"

urlpatterns = [
    path("", views.index, name="index"),
    path("streams/create/", views.stream_create, name="stream_create"),
    path("server-load.json", views.server_load_json, name="server_load_json"),
    path("index-live.json", views.index_live_json, name="index_live_json"),
    path("streams/<int:stream_id>/", views.stream_detail, name="stream_detail"),
    path(
        "streams/<int:stream_id>/stats.json",
        views.stream_stats_json,
        name="stream_stats_json",
    ),
    path(
        "streams/<int:stream_id>/chat.json",
        views.stream_chat_json,
        name="stream_chat_json",
    ),
    path(
        "streams/<int:stream_id>/chat-settings/",
        views.stream_chat_settings,
        name="stream_chat_settings",
    ),
    path(
        "streams/<int:stream_id>/chat-reset/",
        views.stream_chat_reset,
        name="stream_chat_reset",
    ),
    path("streams/<int:stream_id>/delete/", views.stream_delete, name="stream_delete"),
    path(
        "streams/<int:stream_id>/restart/", views.stream_restart, name="stream_restart"
    ),
    path(
        "streams/<int:stream_id>/regenerate-key/",
        views.stream_regenerate_key,
        name="stream_regenerate_key",
    ),
    path(
        "streams/<int:stream_id>/destinations/test-push/",
        views.stream_test_push_all,
        name="stream_test_push_all",
    ),
    path(
        "streams/<int:stream_id>/destinations/create/",
        views.destination_create,
        name="destination_create",
    ),
    path(
        "destinations/<int:destination_id>/update/",
        views.destination_update,
        name="destination_update",
    ),
    path(
        "destinations/<int:destination_id>/delete/",
        views.destination_delete,
        name="destination_delete",
    ),
    path(
        "destinations/<int:destination_id>/toggle/",
        views.destination_toggle,
        name="destination_toggle",
    ),
    path(
        "destinations/<int:destination_id>/test-push/",
        views.destination_test_push,
        name="destination_test_push",
    ),
    path(
        "destinations/<int:destination_id>/log/",
        views.destination_log,
        name="destination_log",
    ),
    path(
        "destinations/<int:destination_id>/log.json",
        views.destination_log_json,
        name="destination_log_json",
    ),
    path("rtmp-hooks/on-publish/", views.on_publish_hook, name="on_publish_hook"),
    path(
        "rtmp-hooks/destinations/<str:stream_key>/",
        views.stream_destinations_hook,
        name="stream_destinations_hook",
    ),
    path("rtmp-hooks/srt-auth/", views.srt_auth_hook, name="srt_auth_hook"),
    path(
        "rtmp-hooks/destination-status/",
        views.destination_status_hook,
        name="destination_status_hook",
    ),
]
