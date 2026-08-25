from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Голый домен (без пути) иначе отдаёт 404 — crud.urls не мапится на "",
    # а нужен свой префикс (см. rtmp-hooks — на него жёстко завязаны URL в
    # rtmp-push/push.sh и MediaMTX authHTTPAddress, менять префикс на "" —
    # отдельная инфраструктурная правка, не только урлы Django).
    # crud:index сам сделает redirect на логин для анонимного пользователя.
    path("", RedirectView.as_view(pattern_name="crud:index"), name="root"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("crud/", include("crud.urls")),
]
