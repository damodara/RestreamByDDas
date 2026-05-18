from django.urls import path

from crud import views

urlpatterns = [
    path("", views.read, name="read"),
    path("create/", views.create, name="create"),
    path("update/<int:rtmp_id>/", views.update, name="update"),
    path("delete/<int:rtmp_id>/", views.delete, name="delete"),
]
