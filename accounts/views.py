import ipaddress

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView, PasswordResetView
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from accounts.emails import send_admin_registration_notice, send_user_decision_notice
from accounts.forms import LogRetentionForm, RegistrationForm
from accounts.models import User
from accounts.tokens import read_decision_token


def client_ip(request):
    """IP клиента для троттлинга. REMOTE_ADDR — это TCP-адрес того, кто
    подключился НАПРЯМУЮ к Django; за nginx (как в docker-compose) это
    всегда адрес самого nginx, а не браузера — иначе все пользователи
    делили бы один счётчик попыток (подтверждено живым тестом: один и тот
    же REMOTE_ADDR для разных X-Forwarded-For). Доверяем X-Real-IP только
    когда REMOTE_ADDR — приватный/loopback адрес, т.е. соединение реально
    пришло изнутри нашей же docker-сети (от nginx) — иначе Django слушает
    порт 8000 и напрямую с хоста, и снаружи, где заголовок можно подделать
    для обхода лимита или чтобы подставить чужой IP под блокировку."""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    try:
        is_trusted_proxy = ipaddress.ip_address(remote_addr).is_private
    except ValueError:
        is_trusted_proxy = False
    if is_trusted_proxy:
        real_ip = request.META.get("HTTP_X_REAL_IP")
        if real_ip:
            return real_ip
    return remote_addr or "unknown"


# Троттлинг неудачных попыток входа по IP — защита от перебора пароля.
# Состояние в django.core.cache (по умолчанию LocMemCache, живёт в памяти
# процесса), поэтому не переживает рестарт и не шарится между несколькими
# воркерами — приемлемо для однопроцессного runserver/gunicorn -w 1, каким
# этот проект и разворачивается сейчас; при переходе на несколько воркеров
# понадобится общий кэш (Redis/Memcached).
LOGIN_THROTTLE_LIMIT = 5
LOGIN_THROTTLE_WINDOW = 300  # 5 минут

# Та же логика для регистрации — без лимита один IP мог бы плодить заявки
# без ограничений, а каждая успешная заявка шлёт письмо всем is_staff
# пользователям (спам администраторам, не только нагрузка на форму).
REGISTER_THROTTLE_LIMIT = 3
REGISTER_THROTTLE_WINDOW = 3600  # 1 час

# И для запроса сброса пароля — PasswordResetForm всегда отвечает одинаково
# (страница "done"), даже если email не зарегистрирован, так что успех тут
# не показатель: считаем каждую попытку, иначе можно засыпать письмами
# любого пользователя, зная только его email.
PASSWORD_RESET_THROTTLE_LIMIT = 3
PASSWORD_RESET_THROTTLE_WINDOW = 3600  # 1 час


class ThrottledLoginView(LoginView):
    def _cache_key(self):
        return f"login-attempts:{client_ip(self.request)}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._cache_key(), 0) >= LOGIN_THROTTLE_LIMIT:
            form = self.get_form()
            form.add_error(
                None,
                "Слишком много неудачных попыток входа. "
                "Попробуйте снова через несколько минут.",
            )
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._cache_key()
        cache.set(key, cache.get(key, 0) + 1, LOGIN_THROTTLE_WINDOW)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._cache_key())
        return super().form_valid(form)


def register(request):
    if request.method == "POST":
        throttle_key = f"register-attempts:{client_ip(request)}"
        if cache.get(throttle_key, 0) >= REGISTER_THROTTLE_LIMIT:
            form = RegistrationForm(request.POST)
            form.add_error(
                None,
                "Слишком много заявок на регистрацию с этого адреса. "
                "Попробуйте снова через час.",
            )
            return render(request, "accounts/register.html", {"form": form})

        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.approval_status = User.ApprovalStatus.PENDING
            user.save()
            cache.set(
                throttle_key, cache.get(throttle_key, 0) + 1, REGISTER_THROTTLE_WINDOW
            )
            send_admin_registration_notice(request, user)
            return render(request, "accounts/registration_pending.html")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


class ThrottledPasswordResetView(PasswordResetView):
    def _cache_key(self):
        return f"password-reset-attempts:{client_ip(self.request)}"

    def post(self, request, *args, **kwargs):
        key = self._cache_key()
        if cache.get(key, 0) >= PASSWORD_RESET_THROTTLE_LIMIT:
            form = self.get_form()
            form.add_error(
                None,
                "Слишком много запросов на сброс пароля с этого адреса. "
                "Попробуйте снова через час.",
            )
            return self.render_to_response(self.get_context_data(form=form))
        cache.set(key, cache.get(key, 0) + 1, PASSWORD_RESET_THROTTLE_WINDOW)
        return super().post(request, *args, **kwargs)


def admin_decision(request, action, token):
    if action not in ("approve", "reject"):
        return render(request, "accounts/decision_result.html", {"invalid": True})

    user_id = read_decision_token(token, action)
    user = User.objects.filter(pk=user_id).first() if user_id else None

    if user is None:
        return render(request, "accounts/decision_result.html", {"invalid": True})

    if user.approval_status != User.ApprovalStatus.PENDING:
        return render(
            request,
            "accounts/decision_result.html",
            {"already_processed": True, "user": user},
        )

    if request.method == "POST":
        approved = action == "approve"
        user.approval_status = (
            User.ApprovalStatus.APPROVED if approved else User.ApprovalStatus.REJECTED
        )
        user.is_active = approved
        user.approved_at = timezone.now()
        user.save()
        send_user_decision_notice(user, approved)
        return render(
            request,
            "accounts/decision_result.html",
            {"processed": True, "approved": approved, "user": user},
        )

    return render(
        request,
        "accounts/admin_decision_confirm.html",
        {"user": user, "action": action},
    )


@login_required
def profile(request):
    if request.method == "POST":
        form = LogRetentionForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Настройки сохранены.")
            return redirect("accounts:profile")
    else:
        form = LogRetentionForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})


class ProfilePasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change_form.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Пароль изменён.")
        return response
