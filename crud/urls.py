from django.urls import path

from crud import views

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("update/<int:rtmp_id>/", views.update, name="update"),
    path("delete/<int:rtmp_id>/", views.delete, name="delete"),
]
