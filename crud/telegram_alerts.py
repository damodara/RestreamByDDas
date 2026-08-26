from django.conf import settings
from django.urls import reverse

from accounts.telegram_bot import send_message


def send_push_error_telegram(destination):
    """Аналог crud.emails.send_push_error_email, но в Telegram — тот же
    edge-triggered вызов из crud.views.destination_status_hook, только
    получатель — accounts.User.telegram_chat_id, а не email."""
    owner = destination.stream.owner
    if not owner.telegram_chat_id:
        return

    log_url = (
        f"{settings.SITE_URL}{reverse('crud:destination_log', args=[destination.id])}"
        if settings.SITE_URL
        else None
    )
    text = (
        f"Рестрим точки приёма «{destination.stream.name}» на "
        f"«{destination.socialmedia_name}» завершился с ошибкой."
    )
    if log_url:
        text += f"\n\nПодробности в логе: {log_url}"
    send_message(owner.telegram_chat_id, text)


def send_stream_drop_telegram(stream):
    """Telegram-аналог crud.emails.send_stream_drop_email — тот же
    notify_telegram_on_push_error переключатель, вызывается из
    crud.management.commands.poll_stream_health."""
    owner = stream.owner
    if not owner.telegram_chat_id:
        return

    stream_url = (
        f"{settings.SITE_URL}{reverse('crud:stream_detail', args=[stream.id])}"
        if settings.SITE_URL
        else None
    )
    text = (
        f"Публикация в точку приёма «{stream.name}» прервалась без явного "
        "завершения — похоже на обрыв связи или сбой энкодера."
    )
    if stream_url:
        text += f"\n\n{stream_url}"
    send_message(owner.telegram_chat_id, text)
