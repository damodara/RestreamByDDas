from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.models import User
from accounts.tokens import make_decision_token, make_email_change_token


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


def send_email_change_confirmation(request, user, new_email):
    """Отправляется на НОВЫЙ адрес, а не на текущий — подтверждает, что
    именно владелец нового адреса запросил смену, а не опечатку/чужой email."""
    confirm_url = request.build_absolute_uri(
        reverse(
            "accounts:confirm_email_change",
            args=[make_email_change_token(user, new_email)],
        )
    )
    body = render_to_string(
        "accounts/email/confirm_email_change.txt",
        {"user": user, "new_email": new_email, "confirm_url": confirm_url},
    )
    send_mail(
        subject="Подтверждение смены email",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email],
    )


def send_email_change_alert(user, old_email, new_email):
    """Уведомление на СТАРЫЙ адрес о том, что запрошена смена email — сама
    смена ждёт перехода по ссылке из send_email_change_confirmation (на
    новый адрес), но без этого письма владелец старого адреса вообще не
    узнал бы о попытке смены (например, при захвате чужой сессии), пока
    email уже не поменяют и вход/сброс пароля не перестанут работать.
    Без ссылки отмены — самого механизма отмены пока нет, только сигнал
    "если это не вы — смените пароль"."""
    if not old_email:
        return
    body = render_to_string(
        "accounts/email/email_change_alert.txt",
        {"user": user, "new_email": new_email},
    )
    send_mail(
        subject="Запрошена смена email вашего аккаунта",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[old_email],
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
