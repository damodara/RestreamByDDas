from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.telegram_bot import get_updates, send_message
from accounts.tokens import (
    make_decision_token,
    make_email_change_token,
    make_telegram_link_token,
    read_telegram_link_token,
)
from accounts.views import (
    LOGIN_THROTTLE_LIMIT,
    PASSWORD_RESET_THROTTLE_LIMIT,
    REGISTER_THROTTLE_LIMIT,
    client_ip,
)


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
        cache.clear()
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


class PasswordResetThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="resetthrottleowner",
            email="resetthrottleowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def request_reset(self, email="resetthrottleowner@example.com"):
        return self.client.post(reverse("accounts:password_reset"), {"email": email})

    def test_blocks_after_repeated_requests(self):
        for _ in range(PASSWORD_RESET_THROTTLE_LIMIT):
            self.request_reset()
        mail.outbox.clear()
        response = self.request_reset()
        self.assertContains(response, "Слишком много запросов на сброс пароля")
        self.assertEqual(len(mail.outbox), 0)

    def test_blocks_even_for_unknown_email(self):
        # Троттлинг считает попытки, а не успешные совпадения email — иначе
        # эндпоинт можно было бы использовать без ограничений для перебора
        # зарегистрированных адресов.
        for _ in range(PASSWORD_RESET_THROTTLE_LIMIT):
            self.request_reset(email="nobody@example.com")
        response = self.request_reset(email="nobody@example.com")
        self.assertContains(response, "Слишком много запросов на сброс пароля")

    def test_under_limit_allows_request(self):
        response = self.request_reset()
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)


class ClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_trusts_x_real_ip_behind_private_proxy(self):
        # REMOTE_ADDR приватный — как будто запрос реально пришёл от nginx
        # внутри docker-сети, значит X-Real-IP можно доверять.
        request = self.factory.get(
            "/", REMOTE_ADDR="172.19.0.4", HTTP_X_REAL_IP="8.8.8.8"
        )
        self.assertEqual(client_ip(request), "8.8.8.8")

    def test_ignores_x_real_ip_when_remote_addr_is_public(self):
        # REMOTE_ADDR публичный (реально маршрутизируемый, не из
        # зарезервированных RFC5737-диапазонов для документации, которые
        # ipaddress тоже помечает как "private") — запрос пришёл напрямую,
        # минуя nginx (или nginx подделан), X-Real-IP мог прислать сам
        # атакующий — не доверяем.
        request = self.factory.get("/", REMOTE_ADDR="8.8.8.8", HTTP_X_REAL_IP="1.1.1.1")
        self.assertEqual(client_ip(request), "8.8.8.8")

    def test_falls_back_to_remote_addr_without_header(self):
        request = self.factory.get("/", REMOTE_ADDR="172.19.0.4")
        self.assertEqual(client_ip(request), "172.19.0.4")


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="profileowner",
            email="profileowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_requires_login(self):
        url = reverse("accounts:profile")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_default_log_retention_is_five_days(self):
        self.assertEqual(self.user.log_retention_days, 5)

    def test_can_update_log_retention(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {"log_retention_days": 14, "save_settings": "1"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.log_retention_days, 14)

    def test_rejects_out_of_range_log_retention(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {"log_retention_days": 0, "save_settings": "1"},
        )
        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.log_retention_days, 5)

    def test_notify_on_push_error_defaults_to_false(self):
        self.assertFalse(self.user.notify_on_push_error)

    def test_can_opt_in_to_push_error_notifications(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("accounts:profile"),
            {
                "log_retention_days": 5,
                "notify_on_push_error": "on",
                "save_settings": "1",
            },
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_on_push_error)

    def test_can_opt_out_of_push_error_notifications(self):
        self.user.notify_on_push_error = True
        self.user.save(update_fields=["notify_on_push_error"])
        self.client.force_login(self.user)
        self.client.post(
            reverse("accounts:profile"),
            {"log_retention_days": 5, "save_settings": "1"},
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_on_push_error)

    def test_auto_end_broadcast_on_drop_defaults_to_true(self):
        self.assertTrue(self.user.auto_end_broadcast_on_drop)

    def test_can_opt_out_of_auto_end_broadcast_on_drop(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("accounts:profile"),
            {"log_retention_days": 5, "save_settings": "1"},
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.auto_end_broadcast_on_drop)

    def test_can_opt_back_in_to_auto_end_broadcast_on_drop(self):
        self.user.auto_end_broadcast_on_drop = False
        self.user.save(update_fields=["auto_end_broadcast_on_drop"])
        self.client.force_login(self.user)
        self.client.post(
            reverse("accounts:profile"),
            {
                "log_retention_days": 5,
                "auto_end_broadcast_on_drop": "on",
                "save_settings": "1",
            },
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.auto_end_broadcast_on_drop)

    def test_can_update_username_immediately(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "username": "newlogin",
                "email": self.user.email,
                "save_identity": "1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newlogin")

    def test_email_change_is_not_applied_until_confirmed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "username": self.user.username,
                "email": "newemail@example.com",
                "save_identity": "1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profileowner@example.com")
        self.assertEqual(len(mail.outbox), 2)
        confirmation, alert = mail.outbox
        self.assertEqual(confirmation.to, ["newemail@example.com"])
        self.assertEqual(alert.to, ["profileowner@example.com"])

    def test_rejects_duplicate_email_on_identity_update(self):
        User.objects.create_user(
            username="otheruser",
            email="taken@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "username": self.user.username,
                "email": "taken@example.com",
                "save_identity": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profileowner@example.com")
        self.assertEqual(len(mail.outbox), 0)


class ProfileTelegramTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tgowner",
            email="tgowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)

    @override_settings(TELEGRAM_BOT_USERNAME="")
    def test_shows_not_configured_message_without_bot_username(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Telegram-бот не настроен")

    @override_settings(TELEGRAM_BOT_USERNAME="restream_bot")
    def test_shows_connect_link_when_not_linked(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "https://t.me/restream_bot?start=")

    @override_settings(TELEGRAM_BOT_USERNAME="restream_bot")
    def test_shows_connected_state_when_linked(self):
        self.user.telegram_chat_id = "555"
        self.user.save(update_fields=["telegram_chat_id"])
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Telegram подключён")
        self.assertNotContains(response, "https://t.me/restream_bot?start=")

    def test_notify_toggle_requires_login(self):
        self.client.logout()
        url = reverse("accounts:telegram_notify_toggle")
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_notify_toggle_flips_setting(self):
        self.assertFalse(self.user.notify_telegram_on_push_error)
        self.client.post(reverse("accounts:telegram_notify_toggle"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.notify_telegram_on_push_error)
        self.client.post(reverse("accounts:telegram_notify_toggle"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_telegram_on_push_error)

    def test_unlink_clears_chat_id_and_notify_flag(self):
        self.user.telegram_chat_id = "555"
        self.user.notify_telegram_on_push_error = True
        self.user.save(
            update_fields=["telegram_chat_id", "notify_telegram_on_push_error"]
        )
        response = self.client.post(reverse("accounts:telegram_unlink"), follow=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")
        self.assertFalse(self.user.notify_telegram_on_push_error)
        self.assertContains(response, "Telegram отключён")


class TelegramLinkTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tokenowner",
            email="tokenowner@example.com",
            password="ownerpass123",
        )

    def test_round_trip(self):
        token = make_telegram_link_token(self.user)
        self.assertEqual(read_telegram_link_token(token), self.user.pk)

    def test_rejects_invalid_token(self):
        self.assertIsNone(read_telegram_link_token("not-a-real-token"))


class TelegramBotApiTests(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_send_message_returns_false_without_token(self):
        with patch("accounts.telegram_bot.urllib.request.urlopen") as mock_urlopen:
            self.assertFalse(send_message("123", "hi"))
            mock_urlopen.assert_not_called()

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_send_message_returns_true_on_ok_response(self):
        mock_response = MockResponse(b'{"ok": true}')
        with patch(
            "accounts.telegram_bot.urllib.request.urlopen", return_value=mock_response
        ):
            self.assertTrue(send_message("123", "hi"))

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_send_message_returns_false_on_network_error(self):
        with patch("accounts.telegram_bot.urllib.request.urlopen", side_effect=OSError):
            self.assertFalse(send_message("123", "hi"))

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_get_updates_returns_empty_list_without_token(self):
        with patch("accounts.telegram_bot.urllib.request.urlopen") as mock_urlopen:
            self.assertEqual(get_updates(0), [])
            mock_urlopen.assert_not_called()

    @override_settings(TELEGRAM_BOT_TOKEN="test-token")
    def test_get_updates_returns_results_on_ok_response(self):
        mock_response = MockResponse(b'{"ok": true, "result": [{"update_id": 1}]}')
        with patch(
            "accounts.telegram_bot.urllib.request.urlopen", return_value=mock_response
        ):
            self.assertEqual(get_updates(0), [{"update_id": 1}])


class MockResponse:
    """Минимальная замена контекст-менеджера urlopen — только .read() и
    вход/выход в `with`, как и у настоящего HTTPResponse в этих тестах."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PollTelegramBotCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="botlinkowner",
            email="botlinkowner@example.com",
            password="ownerpass123",
        )

    def make_command(self):
        from accounts.management.commands.poll_telegram_bot import Command

        return Command()

    def test_links_chat_id_on_valid_start_token(self):
        token = make_telegram_link_token(self.user)
        with patch(
            "accounts.management.commands.poll_telegram_bot.send_message"
        ) as mock_send:
            self.make_command()._handle_update(
                {
                    "update_id": 1,
                    "message": {"text": f"/start {token}", "chat": {"id": 777}},
                }
            )
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "777")
        mock_send.assert_called_once()

    def test_ignores_non_start_messages(self):
        with patch(
            "accounts.management.commands.poll_telegram_bot.send_message"
        ) as mock_send:
            self.make_command()._handle_update(
                {
                    "update_id": 1,
                    "message": {"text": "привет", "chat": {"id": 777}},
                }
            )
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")
        mock_send.assert_not_called()

    def test_start_without_token_sends_instructions(self):
        with patch(
            "accounts.management.commands.poll_telegram_bot.send_message"
        ) as mock_send:
            self.make_command()._handle_update(
                {"update_id": 1, "message": {"text": "/start", "chat": {"id": 777}}}
            )
        mock_send.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")

    def test_start_with_invalid_token_sends_expired_message(self):
        with patch(
            "accounts.management.commands.poll_telegram_bot.send_message"
        ) as mock_send:
            self.make_command()._handle_update(
                {
                    "update_id": 1,
                    "message": {"text": "/start not-a-real-token", "chat": {"id": 777}},
                }
            )
        mock_send.assert_called_once()
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")


class EmailChangeConfirmationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="emailowner",
            email="old@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def request_change(self, new_email="new@example.com"):
        self.client.force_login(self.user)
        self.client.post(
            reverse("accounts:profile"),
            {
                "username": self.user.username,
                "email": new_email,
                "save_identity": "1",
            },
        )
        self.client.logout()
        return make_email_change_token(self.user, new_email)

    def test_get_shows_confirmation_page_without_applying(self):
        token = self.request_change()
        response = self.client.get(
            reverse("accounts:confirm_email_change", args=[token])
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")

    def test_post_applies_the_new_email(self):
        token = self.request_change()
        response = self.client.post(
            reverse("accounts:confirm_email_change", args=[token])
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_rejects_invalid_token(self):
        response = self.client.post(
            reverse("accounts:confirm_email_change", args=["not-a-real-token"])
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")

    def test_rejects_when_email_taken_in_the_meantime(self):
        token = self.request_change()
        User.objects.create_user(
            username="raceduser",
            email="new@example.com",
            password="racepass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        response = self.client.post(
            reverse("accounts:confirm_email_change", args=[token])
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pwchangeowner",
            email="pwchangeowner@example.com",
            password="oldpass12345",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    def test_requires_login(self):
        url = reverse("accounts:password_change")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_can_change_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "oldpass12345",
                "new_password1": "brand-new-pass-1",
                "new_password2": "brand-new-pass-1",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.client.logout()
        self.assertTrue(
            self.client.login(username="pwchangeowner", password="brand-new-pass-1")
        )
