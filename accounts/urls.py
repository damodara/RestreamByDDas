from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path(
        "login/",
        views.ThrottledLoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("decision/<str:action>/<str:token>/", views.admin_decision, name="decision"),
    path("admin/users/", views.pending_users, name="pending_users"),
    path(
        "admin/users/<int:user_id>/<str:action>/",
        views.pending_user_decision,
        name="pending_user_decision",
    ),
    path(
        "confirm-email/<str:token>/",
        views.confirm_email_change,
        name="confirm_email_change",
    ),
    path("profile/", views.profile, name="profile"),
    path(
        "profile/password/",
        views.ProfilePasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "profile/telegram/toggle/",
        views.telegram_notify_toggle,
        name="telegram_notify_toggle",
    ),
    path(
        "profile/telegram/unlink/",
        views.telegram_unlink,
        name="telegram_unlink",
    ),
    path(
        "password-reset/",
        views.ThrottledPasswordResetView.as_view(
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/email/password_reset_email.txt",
            subject_template_name="accounts/email/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
