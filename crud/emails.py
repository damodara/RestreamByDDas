from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse


def send_push_error_email(destination):
    stream = destination.stream
    owner = stream.owner
    if not owner.email:
        return

    context = {
        "destination": destination,
        "stream": stream,
        "log_url": (
            f"{settings.SITE_URL}{reverse('crud:destination_log', args=[destination.id])}"
            if settings.SITE_URL
            else None
        ),
    }
    body = render_to_string("crud/email/push_error.txt", context)
    send_mail(
        subject=f"Ошибка рестрима: {destination.socialmedia_name}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[owner.email],
    )


def send_stream_drop_email(stream):
    """Тот же notify_on_push_error переключатель, что и у
    send_push_error_email — это тоже "что-то в моей трансляции сломалось",
    просто на стороне приёма, а не рестрима. Вызывается из
    crud.management.commands.poll_stream_health, edge-triggered тем же
    способом (Stream.expected_live сбрасывается сразу после отправки)."""
    owner = stream.owner
    if not owner.email:
        return

    context = {
        "stream": stream,
        "stream_url": (
            f"{settings.SITE_URL}{reverse('crud:stream_detail', args=[stream.id])}"
            if settings.SITE_URL
            else None
        ),
    }
    body = render_to_string("crud/email/stream_drop.txt", context)
    send_mail(
        subject=f"Эфир прервался: {stream.name}",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[owner.email],
    )
