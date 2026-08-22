from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import make_decision_token
from accounts.views import LOGIN_THROTTLE_LIMIT, REGISTER_THROTTLE_LIMIT


class RegistrationApprovalFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
            is_staff=True,
        )

    def register(self):
        return self.client.post(
            reverse("accounts:register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": "some-strong-pass-1",
                "password2": "some-strong-pass-1",
            },
        )

    def test_registration_creates_pending_inactive_user_and_notifies_admins(self):
        self.register()
        user = User.objects.get(username="newbie")
        self.assertFalse(user.is_active)
        self.assertEqual(user.approval_status, User.ApprovalStatus.PENDING)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.admin.email, mail.outbox[0].to)

    def test_pending_user_cannot_log_in(self):
        self.register()
        logged_in = self.client.login(username="newbie", password="some-strong-pass-1")
        self.assertFalse(logged_in)

    def test_approve_activates_user_and_notifies_them(self):
        self.register()
        user = User.objects.get(username="newbie")
        token = make_decision_token(user, "approve")
        url = reverse("accounts:decision", args=["approve", token])

        self.client.post(url)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.approval_status, User.ApprovalStatus.APPROVED)

        self.assertEqual(len(mail.outbox), 2)
        self.assertIn(user.email, mail.outbox[-1].to)

        second_response = self.client.post(url)
        self.assertContains(second_response, "уже обработана")

    def test_reject_keeps_user_inactive_and_notifies_them(self):
        self.register()
        user = User.objects.get(username="newbie")
        token = make_decision_token(user, "reject")
        url = reverse("accounts:decision", args=["reject", token])

        self.client.post(url)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.approval_status, User.ApprovalStatus.REJECTED)
        self.assertEqual(len(mail.outbox), 2)

    def test_invalid_token_is_reported(self):
        response = self.client.post(
            reverse("accounts:decision", args=["approve", "garbage-token"])
        )
        self.assertContains(response, "недействительна")


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="throttleowner",
            email="throttleowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def attempt(self, password="wrong-password"):
        return self.client.post(
            reverse("accounts:login"),
            {"username": "throttleowner", "password": password},
        )

    def test_blocks_after_repeated_failures(self):
        for _ in range(LOGIN_THROTTLE_LIMIT):
            self.attempt()
        response = self.attempt()
        self.assertContains(response, "Слишком много неудачных попыток")

    def test_successful_login_resets_counter(self):
        for _ in range(LOGIN_THROTTLE_LIMIT - 1):
            self.attempt()
        response = self.attempt(password="ownerpass123")
        self.assertRedirects(response, "/crud/")

        self.client.logout()
        response = self.attempt()
        self.assertNotContains(response, "Слишком много неудачных попыток")

    def test_under_limit_shows_normal_error(self):
        response = self.attempt()
        self.assertNotContains(response, "Слишком много неудачных попыток")
        self.assertContains(response, "Пожалуйста, введите правильные")


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resetowner",
            email="resetowner@example.com",
            password="oldpass12345",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_request_sends_email_with_working_link(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": self.user.email}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)
        self.assertIn("reset/", mail.outbox[0].body)

    def test_request_for_unknown_email_does_not_error(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "nobody@example.com"}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_confirm_sets_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        # PasswordResetConfirmView меняет токен в URL на "set-password" после
        # первого GET (хранит реальный токен в сессии) — так делает и сама
        # Django-форма при обычном переходе по ссылке из письма.
        follow_url = reverse("accounts:password_reset_confirm", args=[uid, token])
        self.client.get(follow_url, follow=True)

        response = self.client.post(
            reverse("accounts:password_reset_confirm", args=[uid, "set-password"]),
            {"new_password1": "brand-new-pass-1", "new_password2": "brand-new-pass-1"},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))

        self.assertTrue(
            self.client.login(username="resetowner", password="brand-new-pass-1")
        )


class RegisterThrottleTests(TestCase):
    def setUp(self):
        cache.clear()

    def register(self, username):
        return self.client.post(
            reverse("accounts:register"),
            {
                "username": username,
                "email": f"{username}@example.com",
                "password1": "some-strong-pass-1",
                "password2": "some-strong-pass-1",
            },
        )

    def test_blocks_after_repeated_registrations(self):
        for i in range(REGISTER_THROTTLE_LIMIT):
            self.register(f"user{i}")
        response = self.register("oneMore")
        self.assertContains(response, "Слишком много заявок")
        self.assertFalse(User.objects.filter(username="oneMore").exists())

    def test_under_limit_allows_registration(self):
        response = self.register("freshuser")
        self.assertContains(response, "Заявка отправлена")
        self.assertTrue(User.objects.filter(username="freshuser").exists())
