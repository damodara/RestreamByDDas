from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.models import User
from accounts.tokens import make_decision_token


def send_admin_registration_notice(request, user):
    admin_emails = list(
        User.objects.filter(is_staff=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not admin_emails:
        return

    context = {
        "user": user,
        "approve_url": request.build_absolute_uri(
            reverse(
                "accounts:decision",
                args=["approve", make_decision_token(user, "approve")],
            )
        ),
        "reject_url": request.build_absolute_uri(
            reverse(
                "accounts:decision",
                args=["reject", make_decision_token(user, "reject")],
            )
        ),
    }
    body = render_to_string("accounts/email/admin_new_registration.txt", context)
    send_mail(
        subject="Новая заявка на регистрацию",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=admin_emails,
    )


def send_user_decision_notice(user, approved):
    template = (
        "accounts/email/user_approved.txt"
        if approved
        else "accounts/email/user_rejected.txt"
    )
    body = render_to_string(template, {"user": user})
    send_mail(
        subject=(
            "Ваша регистрация подтверждена"
            if approved
            else "Ваша регистрация отклонена"
        ),
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )
