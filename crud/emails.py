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
