from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone

from accounts.emails import send_admin_registration_notice, send_user_decision_notice
from accounts.forms import RegistrationForm
from accounts.models import User
from accounts.tokens import read_decision_token

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


class ThrottledLoginView(LoginView):
    def _cache_key(self):
        return f"login-attempts:{self.request.META.get('REMOTE_ADDR', 'unknown')}"

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
        throttle_key = f"register-attempts:{request.META.get('REMOTE_ADDR', 'unknown')}"
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
