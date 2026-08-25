import json
from unittest.mock import MagicMock, patch

from django import forms
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from crud.models import Rtmp, Stream
from crud.nginx_control import restart_stream
from crud.nginx_stat import fetch_stream_stats
from crud.server_load import get_server_load

HOOK_SECRET = "test-hook-secret"
STAT_URL = "http://nginx-test/stat"

STAT_XML = b"""<?xml version="1.0" encoding="utf-8" ?>
<rtmp>
<server>
<application>
<name>live</name>
<live>
<stream>
<name>known-key</name>
<bytes_in>1000</bytes_in>
<bytes_out>2000</bytes_out>
<bw_in>100</bw_in>
<bw_out>200</bw_out>
<time>65000</time>
</stream>
<nclients>1</nclients>
</live>
</application>
</server>
</rtmp>
"""


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

    def test_destination_enabled_by_default(self):
        self.assertTrue(self.destination.enabled)

    def test_destination_name_links_to_viewing_url_when_set(self):
        self.login(self.user)
        response = self.client.get(reverse("crud:stream_detail", args=[self.stream.id]))
        self.assertContains(response, '<a class="name" href="https://vk.com/watch"')

    def test_destination_name_plain_text_when_no_viewing_url(self):
        self.destination.socialmedia_url = ""
        self.destination.save(update_fields=["socialmedia_url"])
        self.login(self.user)
        response = self.client.get(reverse("crud:stream_detail", args=[self.stream.id]))
        self.assertContains(response, '<span class="name">VK</span>')
        self.assertNotContains(response, '<a class="name"')

    def test_owner_can_toggle_destination(self):
        self.login(self.user)
        toggle_url = reverse("crud:destination_toggle", args=[self.destination.id])

        response = self.client.post(toggle_url)
        self.assertRedirects(
            response, reverse("crud:stream_detail", args=[self.stream.id])
        )
        self.destination.refresh_from_db()
        self.assertFalse(self.destination.enabled)

        self.client.post(toggle_url)
        self.destination.refresh_from_db()
        self.assertTrue(self.destination.enabled)

    def test_toggle_requires_post(self):
        self.login(self.user)
        toggle_url = reverse("crud:destination_toggle", args=[self.destination.id])
        response = self.client.get(toggle_url)
        self.assertEqual(response.status_code, 405)

    def test_other_user_cannot_toggle_destination(self):
        self.login(self.other_user)
        toggle_url = reverse("crud:destination_toggle", args=[self.destination.id])
        response = self.client.post(toggle_url)
        self.assertEqual(response.status_code, 404)
        self.destination.refresh_from_db()
        self.assertTrue(self.destination.enabled)

    def test_duplicate_rtmp_key_within_same_stream_rejected(self):
        self.login(self.user)
        create_url = reverse("crud:destination_create", args=[self.stream.id])
        response = self.client.post(
            create_url,
            {
                "socialmedia_name": "VK Backup",
                "socialmedia_url": "https://vk.com/watch",
                "socialmedia_rtmp_link": "rtmp://vk.com/live",
                "socialmedia_rtmp_key": "vk-key",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже используется")
        self.assertEqual(Rtmp.objects.filter(stream=self.stream).count(), 1)

    def test_same_rtmp_key_allowed_across_different_streams(self):
        self.login(self.user)
        other_stream = Stream.objects.create(owner=self.user, name="Вторая точка")
        create_url = reverse("crud:destination_create", args=[other_stream.id])
        response = self.client.post(
            create_url,
            {
                "socialmedia_name": "VK",
                "socialmedia_url": "https://vk.com/watch",
                "socialmedia_rtmp_link": "rtmp://vk.com/live",
                "socialmedia_rtmp_key": "vk-key",
            },
        )
        self.assertRedirects(
            response, reverse("crud:stream_detail", args=[other_stream.pk])
        )
        created = Rtmp.objects.get(stream=other_stream)
        self.assertEqual(created.socialmedia_rtmp_key, "vk-key")

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

    def test_stream_delete_kicks_current_publisher(self):
        # Удаление строки в БД само по себе не влияет на уже принятого
        # nginx-ом паблишера — без явного restart_stream трансляция
        # продолжила бы идти до тех пор, пока стример сам не отключится.
        self.login(self.user)
        delete_url = reverse("crud:stream_delete", args=[self.stream.id])
        stream_key = self.stream.stream_key
        with patch("crud.views.restart_stream") as mock_restart:
            self.client.post(delete_url)
        mock_restart.assert_called_once_with(stream_key)


@override_settings(RTMP_HOOK_SECRET=HOOK_SECRET)
class RtmpHooksTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="ownerpass123",
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

    def test_on_publish_rejects_without_valid_secret(self):
        url = reverse("crud:on_publish_hook")
        response = self.client.post(url, {"name": self.stream.stream_key})
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            f"{url}?secret=wrong", {"name": self.stream.stream_key}
        )
        self.assertEqual(response.status_code, 403)

    def test_on_publish_rejects_unknown_stream_key(self):
        url = reverse("crud:on_publish_hook")
        response = self.client.post(
            f"{url}?secret={HOOK_SECRET}", {"name": "no-such-key"}
        )
        self.assertEqual(response.status_code, 403)

    def test_on_publish_accepts_known_stream_key(self):
        url = reverse("crud:on_publish_hook")
        response = self.client.post(
            f"{url}?secret={HOOK_SECRET}", {"name": self.stream.stream_key}
        )
        self.assertEqual(response.status_code, 200)

    def test_destinations_hook_returns_push_urls(self):
        url = reverse("crud:stream_destinations_hook", args=[self.stream.stream_key])
        response = self.client.get(f"{url}?secret={HOOK_SECRET}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"id": self.destination.id, "push_url": "rtmp://vk.com/live/vk-key"}],
        )

    def test_destinations_hook_excludes_disabled_destination(self):
        self.destination.enabled = False
        self.destination.save(update_fields=["enabled"])
        url = reverse("crud:stream_destinations_hook", args=[self.stream.stream_key])
        response = self.client.get(f"{url}?secret={HOOK_SECRET}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_destinations_hook_empty_for_unknown_stream(self):
        url = reverse("crud:stream_destinations_hook", args=["no-such-key"])
        response = self.client.get(f"{url}?secret={HOOK_SECRET}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_destinations_hook_rejects_bad_secret(self):
        url = reverse("crud:stream_destinations_hook", args=[self.stream.stream_key])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def post_status(self, destination_id, status, secret=HOOK_SECRET):
        url = reverse("crud:destination_status_hook")
        return self.client.post(
            f"{url}?secret={secret}",
            data=json.dumps({"destination_id": destination_id, "status": status}),
            content_type="application/json",
        )

    def test_destination_status_hook_updates_status(self):
        response = self.post_status(self.destination.id, "live")
        self.assertEqual(response.status_code, 200)
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.push_status, Rtmp.PushStatus.LIVE)
        self.assertIsNotNone(self.destination.push_status_at)

    def test_destination_status_hook_rejects_bad_secret(self):
        response = self.post_status(self.destination.id, "live", secret="wrong")
        self.assertEqual(response.status_code, 403)

    def test_destination_status_hook_rejects_unknown_status(self):
        response = self.post_status(self.destination.id, "definitely-not-a-status")
        self.assertEqual(response.status_code, 403)
        self.destination.refresh_from_db()
        self.assertEqual(self.destination.push_status, Rtmp.PushStatus.UNKNOWN)

    def test_destination_status_hook_silently_ignores_unknown_destination(self):
        response = self.post_status(999999, "live")
        self.assertEqual(response.status_code, 200)


class NginxStatTests(TestCase):
    @override_settings(NGINX_STAT_URL="")
    def test_returns_none_when_not_configured(self):
        with patch("crud.nginx_stat.urllib.request.urlopen") as mock_urlopen:
            self.assertIsNone(fetch_stream_stats("known-key"))
            mock_urlopen.assert_not_called()

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_returns_none_when_unreachable(self):
        with patch("crud.nginx_stat.urllib.request.urlopen", side_effect=OSError):
            self.assertIsNone(fetch_stream_stats("known-key"))

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_returns_live_stats_for_matching_stream(self):
        mock_response = MagicMock()
        mock_response.read.return_value = STAT_XML
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_stat.urllib.request.urlopen", return_value=mock_response
        ):
            stats = fetch_stream_stats("known-key")
        self.assertEqual(
            stats,
            {
                "live": True,
                "bytes_in": 1000,
                "bytes_out": 2000,
                "bw_in": 100,
                "bw_out": 200,
                "uptime_seconds": 65,
            },
        )

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_returns_not_live_for_unknown_stream(self):
        mock_response = MagicMock()
        mock_response.read.return_value = STAT_XML
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_stat.urllib.request.urlopen", return_value=mock_response
        ):
            stats = fetch_stream_stats("no-such-key")
        self.assertEqual(stats, {"live": False})


class ServerLoadTests(TestCase):
    def test_returns_expected_keys(self):
        data = get_server_load()
        self.assertIn("load1", data)
        self.assertIsInstance(data["load1"], float)
        self.assertIn("mem_used_percent", data)
        self.assertIn("disk_used_percent", data)


class StreamStatsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="statsowner",
            email="statsowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)
        self.stream = Stream.objects.create(owner=self.user, name="Stats stream")

    def test_stream_detail_shows_unavailable_when_stats_none(self):
        with patch("crud.views.fetch_stream_stats", return_value=None):
            response = self.client.get(
                reverse("crud:stream_detail", args=[self.stream.id])
            )
        self.assertContains(response, "Статистика недоступна")

    def test_stream_detail_shows_not_live(self):
        with patch("crud.views.fetch_stream_stats", return_value={"live": False}):
            response = self.client.get(
                reverse("crud:stream_detail", args=[self.stream.id])
            )
        self.assertContains(response, "не идёт")

    def test_stream_detail_shows_live_stats(self):
        stats = {
            "live": True,
            "bytes_in": 1000,
            "bytes_out": 2000,
            "bw_in": 100,
            "bw_out": 200,
            "uptime_seconds": 65,
        }
        with patch("crud.views.fetch_stream_stats", return_value=stats):
            response = self.client.get(
                reverse("crud:stream_detail", args=[self.stream.id])
            )
        self.assertContains(response, "В эфире")
        self.assertContains(response, "1:05")

    def test_index_renders_server_load_panel(self):
        response = self.client.get(reverse("crud:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нагрузка сервера")


class DestinationPushStatusDisplayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pushstatusowner",
            email="pushstatusowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)
        self.stream = Stream.objects.create(owner=self.user, name="Push status stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def get_detail(self):
        return self.client.get(reverse("crud:stream_detail", args=[self.stream.id]))

    def test_shows_live_badge_for_destination_when_stream_live(self):
        # count=2: и бейдж самого потока (заголовок "Статистика"), и бейдж
        # именно этой дестинации — substring-проверка одна не отличила бы
        # случай "бейдж дестинации сломан" от "остался только бейдж потока".
        self.destination.push_status = Rtmp.PushStatus.LIVE
        self.destination.save(update_fields=["push_status"])
        with patch(
            "crud.views.fetch_stream_stats", return_value={"live": True, **_STATS}
        ):
            response = self.get_detail()
        self.assertContains(response, 'class="badge live">в эфире', count=2)

    def test_shows_error_badge_for_destination_when_stream_live(self):
        self.destination.push_status = Rtmp.PushStatus.ERROR
        self.destination.save(update_fields=["push_status"])
        with patch(
            "crud.views.fetch_stream_stats", return_value={"live": True, **_STATS}
        ):
            response = self.get_detail()
        self.assertContains(response, 'class="badge error">ошибка')

    def test_hides_destination_badge_when_stream_not_live(self):
        # Статус дестинации мог остаться "live" со старой сессии (например,
        # nginx упал грубо, не успев отрапортовать) — не показываем его как
        # актуальный, если сам поток по /stat сейчас не идёт.
        self.destination.push_status = Rtmp.PushStatus.LIVE
        self.destination.save(update_fields=["push_status"])
        with patch("crud.views.fetch_stream_stats", return_value={"live": False}):
            response = self.get_detail()
        self.assertNotContains(response, 'class="badge live">в эфире')


_STATS = {
    "bytes_in": 1000,
    "bytes_out": 2000,
    "bw_in": 100,
    "bw_out": 200,
    "uptime_seconds": 65,
}


CONTROL_URL = "http://nginx-test"


class NginxControlTests(TestCase):
    @override_settings(NGINX_CONTROL_URL="")
    def test_returns_false_when_not_configured(self):
        with patch("crud.nginx_control.urllib.request.urlopen") as mock_urlopen:
            self.assertFalse(restart_stream("some-key"))
            mock_urlopen.assert_not_called()

    @override_settings(NGINX_CONTROL_URL=CONTROL_URL)
    def test_returns_false_when_unreachable(self):
        with patch("crud.nginx_control.urllib.request.urlopen", side_effect=OSError):
            self.assertFalse(restart_stream("some-key"))

    @override_settings(NGINX_CONTROL_URL=CONTROL_URL)
    def test_returns_true_on_success(self):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_control.urllib.request.urlopen", return_value=mock_response
        ):
            self.assertTrue(restart_stream("some-key"))


class StreamRestartViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="restartowner",
            email="restartowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="restartother",
            email="restartother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Restart stream")

    def test_anonymous_redirects_to_login(self):
        url = reverse("crud:stream_restart", args=[self.stream.id])
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_restart", args=[self.stream.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_owner_sees_success_message(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_restart", args=[self.stream.id])
        with patch("crud.views.restart_stream", return_value=True):
            response = self.client.post(url, follow=True)
        self.assertContains(response, "Сигнал на перезапуск отправлен")

    def test_owner_sees_failure_message(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_restart", args=[self.stream.id])
        with patch("crud.views.restart_stream", return_value=False):
            response = self.client.post(url, follow=True)
        self.assertContains(response, "Не удалось перезапустить")


@override_settings(RTMP_HOOK_SECRET=HOOK_SECRET)
class SrtAuthHookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="srtowner",
            email="srtowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="SRT stream")

    def post_payload(self, url, payload):
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def test_rejects_without_valid_secret(self):
        url = reverse("crud:srt_auth_hook")
        response = self.post_payload(
            url, {"action": "publish", "path": self.stream.stream_key}
        )
        self.assertEqual(response.status_code, 403)

    def test_allows_non_publish_actions_without_key_check(self):
        url = f"{reverse('crud:srt_auth_hook')}?secret={HOOK_SECRET}"
        response = self.post_payload(url, {"action": "read", "path": "no-such-key"})
        self.assertEqual(response.status_code, 200)

    def test_publish_accepts_known_stream_key(self):
        url = f"{reverse('crud:srt_auth_hook')}?secret={HOOK_SECRET}"
        response = self.post_payload(
            url, {"action": "publish", "path": self.stream.stream_key}
        )
        self.assertEqual(response.status_code, 200)

    def test_publish_rejects_unknown_stream_key(self):
        url = f"{reverse('crud:srt_auth_hook')}?secret={HOOK_SECRET}"
        response = self.post_payload(url, {"action": "publish", "path": "no-such-key"})
        self.assertEqual(response.status_code, 403)


class SrtPublishUrlTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="srturlowner",
            email="srturlowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="SRT url stream")

    @override_settings(SRT_SERVER_HOST="")
    def test_none_when_not_configured(self):
        self.assertIsNone(self.stream.srt_publish_url)

    @override_settings(SRT_SERVER_HOST="example.com", SRT_PORT="8890")
    def test_builds_url_when_configured(self):
        self.assertEqual(
            self.stream.srt_publish_url,
            f"srt://example.com:8890?streamid=publish:{self.stream.stream_key}",
        )


class RtmpKeyEncryptionTests(TestCase):
    def test_key_stored_encrypted_but_reads_back_decrypted(self):
        user = User.objects.create_user(
            username="enc-owner",
            email="enc-owner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        stream = Stream.objects.create(owner=user, name="Enc stream")
        destination = Rtmp.objects.create(
            stream=stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="super-secret-key",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT socialmedia_rtmp_key FROM crud_rtmp WHERE id = %s",
                [destination.id],
            )
            raw_value = cursor.fetchone()[0]

        self.assertNotEqual(raw_value, "super-secret-key")
        destination.refresh_from_db()
        self.assertEqual(destination.socialmedia_rtmp_key, "super-secret-key")


class RtmpUniquenessValidationTests(TestCase):
    """Уникальность RTMP-ключа живёт в Rtmp.clean() (модель), не в
    DestinationForm — иначе её бы не видели формы, которые DestinationForm
    не используют, например автосгенерированная ModelForm в Django admin
    (подтверждено живьём: без этого admin создавал дубликаты молча)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="modelvalidationowner",
            email="modelvalidationowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Model validation")
        Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def test_rejects_duplicate_via_generic_modelform_not_just_destination_form(self):
        # То же самое, что строит Django admin по умолчанию для модели без
        # явно указанного form= — а не наш кастомный DestinationForm.
        AdminLikeForm = forms.modelform_factory(Rtmp, fields="__all__")
        form = AdminLikeForm(
            data={
                "stream": self.stream.id,
                "socialmedia_name": "VK Backup",
                "socialmedia_url": "https://vk.com/watch2",
                "socialmedia_rtmp_link": "rtmp://vk.com/live",
                "socialmedia_rtmp_key": "vk-key",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("socialmedia_rtmp_key", form.errors)
        self.assertEqual(Rtmp.objects.filter(stream=self.stream).count(), 1)


class LiveStatsJsonViewTests(TestCase):
    """JS-поллинг (crud/static/crud/live_stats.js) на index/stream_detail
    бьёт эти эндпоинты вместо перезагрузки страницы — проверяем ту же
    авторизацию/owner-scoping, что и у остальных crud-вьюх, плюс форму
    ответа, которую разбирает фронт."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="jsonowner",
            email="jsonowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="jsonother",
            email="jsonother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="JSON stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def test_server_load_json_requires_login(self):
        response = self.client.get(reverse("crud:server_load_json"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('crud:server_load_json')}",
        )

    def test_server_load_json_returns_expected_keys(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("crud:server_load_json"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in (
            "load1",
            "load5",
            "load15",
            "cpu_count",
            "load1_percent",
            "load1_level",
            "mem_used_percent",
            "mem_level",
            "disk_used_percent",
            "disk_level",
        ):
            self.assertIn(key, data)

    def test_stream_stats_json_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        response = self.client.get(
            reverse("crud:stream_stats_json", args=[self.stream.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_stream_stats_json_includes_destination_status_when_live(self):
        self.destination.push_status = Rtmp.PushStatus.LIVE
        self.destination.save(update_fields=["push_status"])
        self.client.force_login(self.user)
        with patch(
            "crud.views.fetch_stream_stats",
            return_value={
                "live": True,
                "bytes_in": 1000,
                "bytes_out": 2000,
                "bw_in": 100,
                "bw_out": 200,
                "uptime_seconds": 65,
            },
        ):
            response = self.client.get(
                reverse("crud:stream_stats_json", args=[self.stream.id])
            )
        data = response.json()
        self.assertTrue(data["stats"]["live"])
        self.assertEqual(data["stats"]["uptime_display"], "1:05")
        self.assertEqual(
            data["destinations"], [{"id": self.destination.id, "push_status": "live"}]
        )

    def test_stream_stats_json_hides_destination_status_when_not_live(self):
        self.destination.push_status = Rtmp.PushStatus.LIVE
        self.destination.save(update_fields=["push_status"])
        self.client.force_login(self.user)
        with patch("crud.views.fetch_stream_stats", return_value={"live": False}):
            response = self.client.get(
                reverse("crud:stream_stats_json", args=[self.stream.id])
            )
        data = response.json()
        self.assertEqual(
            data["destinations"], [{"id": self.destination.id, "push_status": None}]
        )
