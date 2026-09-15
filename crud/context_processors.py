from django.conf import settings

from crud.version_check import check_for_update


def app_version(request):
    context = {"app_version": settings.APP_VERSION}
    # Только для is_staff — обычному пользователю всё равно нечего с этим
    # делать (обновление сервера не его задача), а лишний (пусть и
    # кэшированный) вызов на каждый чих незачем платить для всех подряд.
    if getattr(request.user, "is_staff", False):
        context["update_info"] = check_for_update()
    return context
