from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.tokens import make_decision_token


class RegistrationApprovalFlowTests(TestCase):
    def setUp(self):
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
