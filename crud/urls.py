from django.urls import path

from crud import views

app_name = "crud"

urlpatterns = [
    path("", views.index, name="index"),
    path("streams/create/", views.stream_create, name="stream_create"),
    path("streams/<int:stream_id>/", views.stream_detail, name="stream_detail"),
    path("streams/<int:stream_id>/delete/", views.stream_delete, name="stream_delete"),
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
]
