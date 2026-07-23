from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from crud.models import Rtmp, Stream


class CrudOwnershipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Моя точка")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def login(self, user):
        self.client.force_login(user)

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("crud:index"))
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={reverse('crud:index')}"
        )

    def test_index_shows_only_own_streams(self):
        Stream.objects.create(owner=self.other_user, name="Чужая точка")
        self.login(self.user)
        response = self.client.get(reverse("crud:index"))
        self.assertContains(response, "Моя точка")
        self.assertNotContains(response, "Чужая точка")

    def test_stream_create_sets_owner_and_generates_key(self):
        self.login(self.user)
        response = self.client.post(reverse("crud:stream_create"), {"name": "Новая"})
        stream = Stream.objects.get(name="Новая")
        self.assertEqual(stream.owner, self.user)
        self.assertTrue(stream.stream_key)
        self.assertRedirects(response, reverse("crud:stream_detail", args=[stream.id]))

    def test_other_user_cannot_view_stream(self):
        self.login(self.other_user)
        response = self.client.get(reverse("crud:stream_detail", args=[self.stream.id]))
        self.assertEqual(response.status_code, 404)

    def test_owner_can_add_update_delete_destination(self):
        self.login(self.user)
        create_url = reverse("crud:destination_create", args=[self.stream.id])
        self.client.post(
            create_url,
            {
                "socialmedia_name": "YouTube",
                "socialmedia_url": "https://youtube.com/watch",
                "socialmedia_rtmp_link": "rtmp://youtube.com/live",
                "socialmedia_rtmp_key": "yt-key",
            },
        )
        destination = Rtmp.objects.get(socialmedia_name="YouTube")
        self.assertEqual(destination.stream, self.stream)

        update_url = reverse("crud:destination_update", args=[destination.id])
        self.client.post(
            update_url,
            {
                "socialmedia_name": "YouTube Live",
                "socialmedia_url": "https://youtube.com/watch",
                "socialmedia_rtmp_link": "rtmp://youtube.com/live",
                "socialmedia_rtmp_key": "yt-key",
            },
        )
        destination.refresh_from_db()
        self.assertEqual(destination.socialmedia_name, "YouTube Live")

        delete_url = reverse("crud:destination_delete", args=[destination.id])
        self.client.post(delete_url)
        self.assertFalse(Rtmp.objects.filter(pk=destination.id).exists())

    def test_other_user_cannot_modify_destination(self):
        self.login(self.other_user)
        update_url = reverse("crud:destination_update", args=[self.destination.id])
        response = self.client.get(update_url)
        self.assertEqual(response.status_code, 404)

    def test_stream_delete_cascades_destinations(self):
        self.login(self.user)
        delete_url = reverse("crud:stream_delete", args=[self.stream.id])
        self.client.post(delete_url)
        self.assertFalse(Stream.objects.filter(pk=self.stream.id).exists())
        self.assertFalse(Rtmp.objects.filter(pk=self.destination.id).exists())
