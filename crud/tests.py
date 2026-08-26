import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from django import forms
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import DEFAULT_LOG_RETENTION_DAYS, User
from crud.destination_logs import read_destination_log
from crud.destination_test import test_push as test_push_fn
from crud.destination_test import test_push_many
from crud.emails import send_push_error_email
from crud.forms import StreamChatForm
from crud.models import ChatMessage, Rtmp, Stream
from crud.nginx_control import restart_stream
from crud.nginx_stat import fetch_live_stream_keys, fetch_stream_stats
from crud.server_load import get_server_load
from crud.templatetags.ru_plural import ru_days
from crud.youtube_chat import fetch_live_chat_id, fetch_new_messages

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

STAT_XML_WITH_META = b"""<?xml version="1.0" encoding="utf-8" ?>
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
<meta>
<video>
<width>1280</width>
<height>720</height>
<frame_rate>30</frame_rate>
<codec>H264</codec>
<profile></profile>
<compat>0</compat>
<level>3.1</level>
</video>
<audio>
<codec>AAC</codec>
<profile>LC</profile>
<channels>1</channels>
<sample_rate>44100</sample_rate>
</audio>
</meta>
</stream>
<nclients>1</nclients>
</live>
</application>
</server>
</rtmp>
"""


class AppVersionFooterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="footerowner",
            email="footerowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

    @override_settings(APP_VERSION="v1.2.3")
    def test_footer_shows_configured_version(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("crud:index"))
        self.assertContains(response, '<footer class="site-footer">')
        self.assertContains(response, "v1.2.3")

    def test_footer_defaults_to_dev(self):
        # APP_VERSION не задан явно ни в settings.py, ни через .env в
        # тестовом окружении — тот же дефолт, что при bare-metal запуске
        # без сборки Docker-образа.
        self.client.force_login(self.user)
        response = self.client.get(reverse("crud:index"))
        self.assertContains(response, "dev")


class RootUrlTests(TestCase):
    def test_root_redirects_to_crud_index(self):
        response = self.client.get("/")
        # target_status_code=302: crud:index сам требует логин и дальше
        # редиректит анонима — это ожидаемо, проверяется отдельно ниже.
        self.assertRedirects(response, reverse("crud:index"), target_status_code=302)

    def test_root_eventually_reaches_login_for_anonymous(self):
        # Два прыжка: "/" -> "/crud/" (этот RedirectView) -> "/accounts/
        # login/" (crud:index сам требует логин) — цепочку уже проверяет
        # CrudOwnershipTests.test_anonymous_redirects_to_login для второго
        # прыжка отдельно, здесь — что вся цепочка целиком доходит до 200.
        response = self.client.get("/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [
                (reverse("crud:index"), 302),
                (
                    f"{reverse('accounts:login')}?next={reverse('crud:index')}",
                    302,
                ),
            ],
        )

    def test_root_eventually_reaches_index_for_authenticated_user(self):
        User.objects.create_user(
            username="rooter",
            email="rooter@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(User.objects.get(username="rooter"))
        response = self.client.get("/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(reverse("crud:index"), 302)])


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

    def test_toggle_shows_feedback_message(self):
        self.login(self.user)
        toggle_url = reverse("crud:destination_toggle", args=[self.destination.id])

        response = self.client.post(toggle_url, follow=True)
        self.assertContains(response, "выключена")

        response = self.client.post(toggle_url, follow=True)
        self.assertContains(response, "включена")

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


class IndexLiveJsonViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="liveowner",
            email="liveowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="liveother",
            email="liveother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Моя точка")
        self.other_stream = Stream.objects.create(
            owner=self.other_user, name="Чужая точка"
        )

    def test_requires_login(self):
        url = reverse("crud:index_live_json")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_unavailable_when_stats_not_configured(self):
        self.client.force_login(self.user)
        with patch("crud.views.fetch_live_stream_keys", return_value=None):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(response.json(), {"available": False, "streams": {}})

    def test_scoped_to_own_streams_with_live_mapping(self):
        self.client.force_login(self.user)
        with patch(
            "crud.views.fetch_live_stream_keys",
            return_value={self.stream.stream_key, self.other_stream.stream_key},
        ):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(
            response.json(),
            {
                "available": True,
                "streams": {str(self.stream.id): {"live": True, "push_error": False}},
            },
        )

    def test_offline_when_key_not_in_live_set(self):
        self.client.force_login(self.user)
        with patch("crud.views.fetch_live_stream_keys", return_value=set()):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(
            response.json(),
            {
                "available": True,
                "streams": {str(self.stream.id): {"live": False, "push_error": False}},
            },
        )

    def test_push_error_true_when_live_and_enabled_destination_erroring(self):
        Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
            push_status=Rtmp.PushStatus.ERROR,
        )
        self.client.force_login(self.user)
        with patch(
            "crud.views.fetch_live_stream_keys",
            return_value={self.stream.stream_key},
        ):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(
            response.json()["streams"][str(self.stream.id)],
            {"live": True, "push_error": True},
        )

    def test_push_error_false_when_stream_not_live(self):
        Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
            push_status=Rtmp.PushStatus.ERROR,
        )
        self.client.force_login(self.user)
        with patch("crud.views.fetch_live_stream_keys", return_value=set()):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(
            response.json()["streams"][str(self.stream.id)],
            {"live": False, "push_error": False},
        )

    def test_push_error_false_when_erroring_destination_disabled(self):
        Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
            push_status=Rtmp.PushStatus.ERROR,
            enabled=False,
        )
        self.client.force_login(self.user)
        with patch(
            "crud.views.fetch_live_stream_keys",
            return_value={self.stream.stream_key},
        ):
            response = self.client.get(reverse("crud:index_live_json"))
        self.assertEqual(
            response.json()["streams"][str(self.stream.id)],
            {"live": True, "push_error": False},
        )

    def test_index_page_shows_push_error_badge(self):
        Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
            push_status=Rtmp.PushStatus.ERROR,
        )
        self.client.force_login(self.user)
        with patch(
            "crud.views.fetch_live_stream_keys",
            return_value={self.stream.stream_key},
        ):
            response = self.client.get(reverse("crud:index"))
        self.assertContains(response, "ошибка пуша")


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

    def test_status_hook_sends_email_on_error_when_opted_in(self):
        self.user.notify_on_push_error = True
        self.user.save(update_fields=["notify_on_push_error"])
        response = self.post_status(self.destination.id, "error")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("VK", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])

    def test_status_hook_does_not_email_when_not_opted_in(self):
        response = self.post_status(self.destination.id, "error")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_status_hook_only_emails_on_edge_transition_to_error(self):
        self.user.notify_on_push_error = True
        self.user.save(update_fields=["notify_on_push_error"])
        self.post_status(self.destination.id, "error")
        self.post_status(self.destination.id, "error")
        self.assertEqual(len(mail.outbox), 1)

    def test_status_hook_emails_again_after_recovering_then_erroring(self):
        self.user.notify_on_push_error = True
        self.user.save(update_fields=["notify_on_push_error"])
        self.post_status(self.destination.id, "error")
        self.post_status(self.destination.id, "live")
        self.post_status(self.destination.id, "error")
        self.assertEqual(len(mail.outbox), 2)


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

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_includes_media_info_when_meta_present(self):
        mock_response = MagicMock()
        mock_response.read.return_value = STAT_XML_WITH_META
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_stat.urllib.request.urlopen", return_value=mock_response
        ):
            stats = fetch_stream_stats("known-key")
        self.assertEqual(stats["video_width"], "1280")
        self.assertEqual(stats["video_height"], "720")
        self.assertEqual(stats["video_frame_rate"], "30")
        self.assertEqual(stats["video_codec"], "H264")
        self.assertEqual(stats["audio_codec"], "AAC")
        self.assertEqual(stats["audio_channels"], "1")
        self.assertEqual(stats["audio_sample_rate"], "44100")

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_omits_media_info_when_meta_absent(self):
        mock_response = MagicMock()
        mock_response.read.return_value = STAT_XML
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_stat.urllib.request.urlopen", return_value=mock_response
        ):
            stats = fetch_stream_stats("known-key")
        self.assertNotIn("video_codec", stats)
        self.assertNotIn("audio_codec", stats)


class FetchLiveStreamKeysTests(TestCase):
    @override_settings(NGINX_STAT_URL="")
    def test_returns_none_when_not_configured(self):
        with patch("crud.nginx_stat.urllib.request.urlopen") as mock_urlopen:
            self.assertIsNone(fetch_live_stream_keys())
            mock_urlopen.assert_not_called()

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_returns_none_when_unreachable(self):
        with patch("crud.nginx_stat.urllib.request.urlopen", side_effect=OSError):
            self.assertIsNone(fetch_live_stream_keys())

    @override_settings(NGINX_STAT_URL=STAT_URL)
    def test_returns_set_of_live_stream_keys(self):
        mock_response = MagicMock()
        mock_response.read.return_value = STAT_XML
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.nginx_stat.urllib.request.urlopen", return_value=mock_response
        ):
            keys = fetch_live_stream_keys()
        self.assertEqual(keys, {"known-key"})


class YoutubeChatApiTests(TestCase):
    @override_settings(YOUTUBE_API_KEY="")
    def test_fetch_live_chat_id_returns_none_without_key(self):
        with patch("crud.youtube_chat.urllib.request.urlopen") as mock_urlopen:
            self.assertIsNone(fetch_live_chat_id("abc123"))
            mock_urlopen.assert_not_called()

    @override_settings(YOUTUBE_API_KEY="test-key")
    def test_fetch_live_chat_id_parses_response(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"items": [{"liveStreamingDetails": {"activeLiveChatId": "chat-123"}}]}
        ).encode()
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.youtube_chat.urllib.request.urlopen", return_value=mock_response
        ):
            self.assertEqual(fetch_live_chat_id("abc123"), "chat-123")

    @override_settings(YOUTUBE_API_KEY="test-key")
    def test_fetch_live_chat_id_returns_none_for_unknown_video(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"items": []}).encode()
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.youtube_chat.urllib.request.urlopen", return_value=mock_response
        ):
            self.assertIsNone(fetch_live_chat_id("no-such-video"))

    @override_settings(YOUTUBE_API_KEY="test-key")
    def test_fetch_live_chat_id_returns_none_on_network_error(self):
        with patch("crud.youtube_chat.urllib.request.urlopen", side_effect=OSError):
            self.assertIsNone(fetch_live_chat_id("abc123"))

    @override_settings(YOUTUBE_API_KEY="test-key")
    def test_fetch_new_messages_parses_response(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "items": [
                    {
                        "id": "msg-1",
                        "snippet": {
                            "displayMessage": "Привет!",
                            "publishedAt": "2026-01-01T12:00:00Z",
                        },
                        "authorDetails": {"displayName": "Зритель"},
                    }
                ],
                "nextPageToken": "token-2",
                "pollingIntervalMillis": 4000,
            }
        ).encode()
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.youtube_chat.urllib.request.urlopen", return_value=mock_response
        ):
            result = fetch_new_messages("chat-123")
        messages, next_page_token, interval = result
        self.assertEqual(
            messages,
            [
                {
                    "external_id": "msg-1",
                    "author_name": "Зритель",
                    "text": "Привет!",
                    "posted_at": messages[0]["posted_at"],
                }
            ],
        )
        self.assertEqual(next_page_token, "token-2")
        self.assertEqual(interval, 4.0)

    @override_settings(YOUTUBE_API_KEY="test-key")
    def test_fetch_new_messages_skips_malformed_items(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"items": [{"id": "msg-1", "snippet": {}, "authorDetails": {}}]}
        ).encode()
        mock_response.__enter__.return_value = mock_response
        with patch(
            "crud.youtube_chat.urllib.request.urlopen", return_value=mock_response
        ):
            messages, _, _ = fetch_new_messages("chat-123")
        self.assertEqual(messages, [])


class PollYoutubeChatCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="chatowner",
            email="chatowner@example.com",
            password="ownerpass123",
        )
        self.stream = Stream.objects.create(
            owner=self.user, name="Chat stream", youtube_chat_video_id="video-1"
        )

    def test_tick_creates_messages_when_live(self):
        from crud.management.commands.poll_youtube_chat import Command

        state = {}
        with (
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_stream_stats",
                return_value={"live": True},
            ),
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_live_chat_id",
                return_value="chat-123",
            ),
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_new_messages",
                return_value=(
                    [
                        {
                            "external_id": "msg-1",
                            "author_name": "Зритель",
                            "text": "Привет!",
                            "posted_at": timezone.now(),
                        }
                    ],
                    "next-token",
                    5,
                ),
            ),
        ):
            Command()._tick(state)

        self.assertEqual(ChatMessage.objects.filter(stream=self.stream).count(), 1)
        message = ChatMessage.objects.get(stream=self.stream)
        self.assertEqual(message.author_name, "Зритель")
        self.assertEqual(message.platform, ChatMessage.Platform.YOUTUBE)

    def test_tick_does_not_duplicate_messages(self):
        from crud.management.commands.poll_youtube_chat import Command

        state = {}
        with (
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_stream_stats",
                return_value={"live": True},
            ),
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_live_chat_id",
                return_value="chat-123",
            ),
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_new_messages",
                return_value=(
                    [
                        {
                            "external_id": "msg-1",
                            "author_name": "Зритель",
                            "text": "Привет!",
                            "posted_at": timezone.now(),
                        }
                    ],
                    "next-token",
                    5,
                ),
            ),
        ):
            command = Command()
            command._tick(state)
            state[self.stream.id]["next_poll_at"] = timezone.now()
            command._tick(state)

        self.assertEqual(ChatMessage.objects.filter(stream=self.stream).count(), 1)

    def test_tick_skips_stream_when_not_live(self):
        from crud.management.commands.poll_youtube_chat import Command

        state = {}
        with (
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_stream_stats",
                return_value={"live": False},
            ),
            patch(
                "crud.management.commands.poll_youtube_chat.fetch_live_chat_id"
            ) as mock_live_chat_id,
        ):
            Command()._tick(state)
            mock_live_chat_id.assert_not_called()

        self.assertEqual(ChatMessage.objects.filter(stream=self.stream).count(), 0)

    def test_tick_ignores_streams_without_video_id(self):
        from crud.management.commands.poll_youtube_chat import Command

        Stream.objects.create(owner=self.user, name="No chat stream")
        state = {}
        with patch(
            "crud.management.commands.poll_youtube_chat.fetch_stream_stats",
            return_value={"live": True},
        ) as mock_fetch_stats:
            Command()._tick(state)
            # Только один стрим (self.stream) имеет youtube_chat_video_id —
            # значит fetch_stream_stats должен вызваться ровно один раз.
            self.assertEqual(mock_fetch_stats.call_count, 1)


class StreamChatFormTests(TestCase):
    def make_form(self, value):
        return StreamChatForm(data={"youtube_chat_video_id": value})

    def test_extracts_id_from_watch_url(self):
        form = self.make_form("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["youtube_chat_video_id"], "dQw4w9WgXcQ")

    def test_extracts_id_from_short_url(self):
        form = self.make_form("https://youtu.be/dQw4w9WgXcQ")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["youtube_chat_video_id"], "dQw4w9WgXcQ")

    def test_accepts_raw_id(self):
        form = self.make_form("dQw4w9WgXcQ")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["youtube_chat_video_id"], "dQw4w9WgXcQ")

    def test_accepts_empty_value(self):
        form = self.make_form("")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["youtube_chat_video_id"], "")


class StreamChatViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="chatviewowner",
            email="chatviewowner@example.com",
            password="ownerpass123",
        )
        self.other_user = User.objects.create_user(
            username="chatviewother",
            email="chatviewother@example.com",
            password="otherpass123",
        )
        self.stream = Stream.objects.create(
            owner=self.user, name="Chat view stream", youtube_chat_video_id="video-1"
        )

    def test_chat_settings_requires_login(self):
        url = reverse("crud:stream_chat_settings", args=[self.stream.id])
        response = self.client.post(url, {"youtube_chat_video_id": "abc"})
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_owner_can_update_chat_video_id(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_settings", args=[self.stream.id])
        response = self.client.post(
            url, {"youtube_chat_video_id": "https://youtu.be/newVideoId"}
        )
        self.assertRedirects(
            response, reverse("crud:stream_detail", args=[self.stream.id])
        )
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.youtube_chat_video_id, "newVideoId")

    def test_other_user_cannot_update_chat_settings(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_chat_settings", args=[self.stream.id])
        response = self.client.post(url, {"youtube_chat_video_id": "hacked"})
        self.assertEqual(response.status_code, 404)
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.youtube_chat_video_id, "video-1")

    def test_saving_empty_video_id_also_clears_message_history(self):
        # Отключить чат можно и через "Сохранить" с пустым полем, не
        # только через выделенную кнопку "Сбросить" — старые сообщения
        # не должны переживать оба пути одинаково.
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Привет!",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_settings", args=[self.stream.id])
        self.client.post(url, {"youtube_chat_video_id": ""})
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.youtube_chat_video_id, "")
        self.assertEqual(self.stream.chat_messages.count(), 0)

    def test_saving_new_video_id_keeps_message_history(self):
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Привет!",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_settings", args=[self.stream.id])
        self.client.post(url, {"youtube_chat_video_id": "https://youtu.be/newId"})
        self.assertEqual(self.stream.chat_messages.count(), 1)

    def test_chat_json_requires_login(self):
        url = reverse("crud:stream_chat_json", args=[self.stream.id])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404_for_chat_json(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_chat_json", args=[self.stream.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_chat_json_returns_recent_messages(self):
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Привет!",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_json", args=[self.stream.id])
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["author_name"], "Зритель")
        self.assertIn("posted_at", data["messages"][0])
        self.assertTrue(data["chat_enabled"])

    def test_chat_json_incremental_after_id(self):
        first = ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="A",
            text="Первое",
            posted_at=timezone.now(),
        )
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-2",
            author_name="B",
            text="Второе",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_json", args=[self.stream.id])
        response = self.client.get(url, {"after_id": first.id})
        data = response.json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["text"], "Второе")

    def test_chat_json_hides_messages_when_source_disconnected(self):
        # Даже если в БД почему-то остались старые строки (например,
        # чат отключили в обход stream_chat_settings/stream_chat_reset),
        # эндпоинт не должен их отдавать, пока youtube_chat_video_id пуст.
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Старое сообщение",
            posted_at=timezone.now(),
        )
        self.stream.youtube_chat_video_id = ""
        self.stream.save(update_fields=["youtube_chat_video_id"])
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_json", args=[self.stream.id])
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(data["messages"], [])
        self.assertFalse(data["chat_enabled"])

    def test_chat_reset_requires_login(self):
        url = reverse("crud:stream_chat_reset", args=[self.stream.id])
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_chat_reset_requires_post(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_reset", args=[self.stream.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_owner_can_reset_chat(self):
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Привет!",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.user)
        url = reverse("crud:stream_chat_reset", args=[self.stream.id])
        response = self.client.post(url)
        self.assertRedirects(
            response, reverse("crud:stream_detail", args=[self.stream.id])
        )
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.youtube_chat_video_id, "")
        self.assertEqual(self.stream.chat_messages.count(), 0)

    def test_other_user_cannot_reset_chat(self):
        ChatMessage.objects.create(
            stream=self.stream,
            platform=ChatMessage.Platform.YOUTUBE,
            external_id="msg-1",
            author_name="Зритель",
            text="Привет!",
            posted_at=timezone.now(),
        )
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_chat_reset", args=[self.stream.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.stream.refresh_from_db()
        self.assertEqual(self.stream.youtube_chat_video_id, "video-1")
        self.assertEqual(self.stream.chat_messages.count(), 1)


class ServerLoadTests(TestCase):
    def test_returns_expected_keys(self):
        data = get_server_load()
        self.assertIn("load1", data)
        self.assertIsInstance(data["load1"], float)
        self.assertIn("mem_used_percent", data)
        self.assertIn("disk_used_percent", data)


class ReadDestinationLogTests(TestCase):
    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("crud.destination_logs.LOGS_ROOT", Path(tmp)):
                self.assertIsNone(read_destination_log("no-such-key", 1))

    def test_returns_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / "some-key"
            stream_dir.mkdir()
            (stream_dir / "42.log").write_text("line1\nline2\n")
            with patch("crud.destination_logs.LOGS_ROOT", Path(tmp)):
                self.assertEqual(read_destination_log("some-key", 42), "line1\nline2")

    def test_truncates_to_last_max_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / "some-key"
            stream_dir.mkdir()
            lines = [f"line{i}" for i in range(600)]
            (stream_dir / "42.log").write_text("\n".join(lines))
            with patch("crud.destination_logs.LOGS_ROOT", Path(tmp)):
                result = read_destination_log("some-key", 42)
            result_lines = result.split("\n")
            self.assertEqual(len(result_lines), 500)
            self.assertEqual(result_lines[0], "line100")
            self.assertEqual(result_lines[-1], "line599")


class RuDaysFilterTests(TestCase):
    def test_declension_by_last_digit(self):
        self.assertEqual(ru_days(1), "день")
        self.assertEqual(ru_days(21), "день")
        self.assertEqual(ru_days(2), "дня")
        self.assertEqual(ru_days(3), "дня")
        self.assertEqual(ru_days(4), "дня")
        self.assertEqual(ru_days(5), "дней")
        self.assertEqual(ru_days(0), "дней")

    def test_teens_are_always_dney(self):
        # 11-14 — исключение из правила по последней цифре (не "день"/"дня",
        # хотя 1/2/3/4 сами по себе такие формы дают).
        for n in (11, 12, 13, 14, 111, 112):
            self.assertEqual(ru_days(n), "дней")

    def test_non_numeric_falls_back(self):
        self.assertEqual(ru_days("не число"), "дней")


class PlatformBadgeTests(TestCase):
    def make(self, socialmedia_name):
        stream = Stream.objects.create(
            owner=User.objects.create_user(
                username=f"badgeowner{socialmedia_name}",
                email=f"badgeowner{socialmedia_name}@example.com".replace(" ", ""),
                password="ownerpass123",
            ),
            name="Badge stream",
        )
        return Rtmp(
            stream=stream,
            socialmedia_name=socialmedia_name,
            socialmedia_rtmp_link="rtmp://example.com/live",
            socialmedia_rtmp_key="key",
        )

    def test_recognizes_known_platforms(self):
        cases = {
            "VK": ("VK", "#0077FF"),
            "Вконтакте": ("VK", "#0077FF"),
            "YouTube Live": ("YT", "#FF0000"),
            "Мой Twitch": ("TW", "#9146FF"),
            "Telegram канал": ("TG", "#26A5E4"),
            "Одноклассники": ("ОК", "#EE8208"),
            "RuTube": ("RT", "#1D6FB8"),
            "Vimeo": ("VM", "#1AB7EA"),
            "Trovo": ("TR", "#19D66B"),
            "Kick": ("K", "#53FC18"),
        }
        for name, (label, color) in cases.items():
            destination = self.make(name)
            self.assertEqual(
                destination.platform_badge, {"label": label, "color": color}
            )

    def test_unknown_platform_falls_back_to_initial(self):
        destination = self.make("Facebook")
        self.assertEqual(destination.platform_badge, {"label": "F", "color": "#6b7280"})


def _age_file(path, days):
    old_time = time.time() - days * 86400
    os.utime(path, (old_time, old_time))


class CleanupDestinationLogsCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="cleanupowner",
            email="cleanupowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Cleanup stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def run_cleanup(self, tmp):
        with patch(
            "crud.management.commands.cleanup_destination_logs.LOGS_ROOT", Path(tmp)
        ):
            call_command("cleanup_destination_logs")

    def test_deletes_log_older_than_owner_retention(self):
        self.user.log_retention_days = 2
        self.user.save(update_fields=["log_retention_days"])
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / self.stream.stream_key
            stream_dir.mkdir()
            log_file = stream_dir / f"{self.destination.id}.log"
            log_file.write_text("old")
            _age_file(log_file, days=3)

            self.run_cleanup(tmp)
            self.assertFalse(log_file.exists())

    def test_keeps_log_within_owner_retention(self):
        self.user.log_retention_days = 10
        self.user.save(update_fields=["log_retention_days"])
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / self.stream.stream_key
            stream_dir.mkdir()
            log_file = stream_dir / f"{self.destination.id}.log"
            log_file.write_text("fresh")
            _age_file(log_file, days=3)

            self.run_cleanup(tmp)
            self.assertTrue(log_file.exists())

    def test_orphaned_destination_uses_default_retention(self):
        stream_key = self.stream.stream_key
        destination_id = self.destination.id
        self.destination.delete()
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / stream_key
            stream_dir.mkdir()
            log_file = stream_dir / f"{destination_id}.log"
            log_file.write_text("orphaned")
            _age_file(log_file, days=DEFAULT_LOG_RETENTION_DAYS + 1)

            self.run_cleanup(tmp)
            self.assertFalse(log_file.exists())

    def test_never_deletes_pid_files(self):
        self.user.log_retention_days = 1
        self.user.save(update_fields=["log_retention_days"])
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / self.stream.stream_key
            stream_dir.mkdir()
            pid_file = stream_dir / f"{self.destination.id}.pid"
            pid_file.write_text("12345")
            _age_file(pid_file, days=30)

            self.run_cleanup(tmp)
            self.assertTrue(pid_file.exists())

    def test_removes_now_empty_stream_dir(self):
        self.user.log_retention_days = 1
        self.user.save(update_fields=["log_retention_days"])
        with tempfile.TemporaryDirectory() as tmp:
            stream_dir = Path(tmp) / self.stream.stream_key
            stream_dir.mkdir()
            log_file = stream_dir / f"{self.destination.id}.log"
            log_file.write_text("old")
            _age_file(log_file, days=30)

            self.run_cleanup(tmp)
            self.assertFalse(stream_dir.exists())


class DestinationLogViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="logowner",
            email="logowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="logother",
            email="logother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Log stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def test_requires_login(self):
        url = reverse("crud:destination_log", args=[self.destination.id])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:destination_log", args=[self.destination.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_shows_message_when_no_log_yet(self):
        self.client.force_login(self.user)
        with patch("crud.views.read_destination_log", return_value=None):
            response = self.client.get(
                reverse("crud:destination_log", args=[self.destination.id])
            )
        self.assertContains(response, "публикации с этой дестинацией ещё не было")

    def test_shows_log_contents(self):
        self.client.force_login(self.user)
        with patch(
            "crud.views.read_destination_log",
            return_value="Input #0, flv, from 'rtmp://...'",
        ):
            response = self.client.get(
                reverse("crud:destination_log", args=[self.destination.id])
            )
        self.assertContains(response, "Input #0, flv, from")

    def test_stream_detail_links_to_log(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("crud:stream_detail", args=[self.stream.id]))
        self.assertContains(
            response,
            reverse("crud:destination_log", args=[self.destination.id]),
        )

    def test_json_requires_login(self):
        url = reverse("crud:destination_log_json", args=[self.destination.id])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_json_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:destination_log_json", args=[self.destination.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_json_returns_log_text(self):
        self.client.force_login(self.user)
        with patch(
            "crud.views.read_destination_log",
            return_value="Input #0, flv, from 'rtmp://...'",
        ):
            response = self.client.get(
                reverse("crud:destination_log_json", args=[self.destination.id])
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"log_text": "Input #0, flv, from 'rtmp://...'"}
        )

    def test_json_returns_none_when_no_log_yet(self):
        self.client.force_login(self.user)
        with patch("crud.views.read_destination_log", return_value=None):
            response = self.client.get(
                reverse("crud:destination_log_json", args=[self.destination.id])
            )
        self.assertEqual(response.json(), {"log_text": None})


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

    def test_hides_stale_error_badge_for_disabled_destination(self):
        # Пользователь выключил дестинацию тумблером именно из-за ошибки
        # пуша — push_status="error" остаётся в БД (toggle его не трогает),
        # но раз дестинация выключена, в неё больше ничего не льётся и
        # бейдж не должен вводить в заблуждение, что она всё ещё "в ошибке".
        self.destination.push_status = Rtmp.PushStatus.ERROR
        self.destination.enabled = False
        self.destination.save(update_fields=["push_status", "enabled"])
        with patch(
            "crud.views.fetch_stream_stats", return_value={"live": True, **_STATS}
        ):
            response = self.get_detail()
        self.assertNotContains(response, 'class="badge error">ошибка')


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


class StreamRegenerateKeyViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="regenowner",
            email="regenowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="regenother",
            email="regenother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Regen stream")

    def test_anonymous_redirects_to_login(self):
        url = reverse("crud:stream_regenerate_key", args=[self.stream.id])
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_regenerate_key", args=[self.stream.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_requires_post(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_regenerate_key", args=[self.stream.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_owner_can_regenerate_key(self):
        self.client.force_login(self.user)
        old_key = self.stream.stream_key
        url = reverse("crud:stream_regenerate_key", args=[self.stream.id])
        with patch("crud.views.restart_stream") as mock_restart:
            response = self.client.post(url, follow=True)
        self.stream.refresh_from_db()
        self.assertNotEqual(self.stream.stream_key, old_key)
        mock_restart.assert_called_once_with(old_key)
        self.assertContains(response, "Ключ обновлён")


class PushErrorEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="emailowner",
            email="emailowner@example.com",
            password="ownerpass123",
        )
        self.stream = Stream.objects.create(owner=self.user, name="Email stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    @override_settings(SITE_URL="")
    def test_sends_without_link_when_site_url_unset(self):
        send_push_error_email(self.destination)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("http", mail.outbox[0].body)

    @override_settings(SITE_URL="http://example.com")
    def test_includes_link_when_site_url_set(self):
        send_push_error_email(self.destination)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            f"http://example.com/crud/destinations/{self.destination.id}/log/",
            mail.outbox[0].body,
        )

    def test_skips_when_owner_has_no_email(self):
        self.user.email = ""
        self.user.save(update_fields=["email"])
        send_push_error_email(self.destination)
        self.assertEqual(len(mail.outbox), 0)


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

    def test_stream_stats_json_hides_stale_status_for_disabled_destination(self):
        self.destination.push_status = Rtmp.PushStatus.ERROR
        self.destination.enabled = False
        self.destination.save(update_fields=["push_status", "enabled"])
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
        self.assertEqual(
            data["destinations"], [{"id": self.destination.id, "push_status": None}]
        )


class DestinationPresetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="presetowner",
            email="presetowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.client.force_login(self.user)
        self.stream = Stream.objects.create(owner=self.user, name="Preset stream")

    def test_create_form_includes_presets(self):
        response = self.client.get(
            reverse("crud:destination_create", args=[self.stream.id])
        )
        self.assertContains(response, "destination-presets-data")
        self.assertContains(response, "YouTube")

    def test_update_form_includes_presets(self):
        destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )
        response = self.client.get(
            reverse("crud:destination_update", args=[destination.id])
        )
        self.assertContains(response, "destination-presets-data")


class DestinationTestPushViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testpushowner",
            email="testpushowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="testpushother",
            email="testpushother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Test push stream")
        self.destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="VK",
            socialmedia_url="https://vk.com/watch",
            socialmedia_rtmp_link="rtmp://vk.com/live",
            socialmedia_rtmp_key="vk-key",
        )

    def test_anonymous_redirects_to_login(self):
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_shows_success_message(self):
        self.client.force_login(self.user)
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        with patch(
            "crud.views.test_push",
            return_value=(True, "Площадка приняла тестовый поток."),
        ):
            response = self.client.post(url, follow=True)
        self.assertContains(response, "Площадка приняла тестовый поток.")

    def test_shows_failure_message(self):
        self.client.force_login(self.user)
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        with patch(
            "crud.views.test_push",
            return_value=(False, "Площадка отклонила подключение."),
        ):
            response = self.client.post(url, follow=True)
        self.assertContains(response, "Площадка отклонила подключение.")

    def test_calls_test_push_with_destination_push_url(self):
        self.client.force_login(self.user)
        url = reverse("crud:destination_test_push", args=[self.destination.id])
        with patch("crud.views.test_push", return_value=(True, "ok")) as mock_test_push:
            self.client.post(url)
        mock_test_push.assert_called_once_with(self.destination.push_url)


class DestinationTestPushFunctionTests(TestCase):
    def test_reports_failure_when_ffmpeg_missing(self):
        with patch(
            "crud.destination_test.subprocess.run", side_effect=FileNotFoundError
        ):
            success, detail = test_push_fn("rtmp://example.com/live/key")
        self.assertFalse(success)
        self.assertIn("ffmpeg", detail)

    def test_reports_timeout(self):
        with patch(
            "crud.destination_test.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=15),
        ):
            success, detail = test_push_fn("rtmp://example.com/live/key")
        self.assertFalse(success)
        self.assertIn("время ожидания", detail)

    def test_reports_success_on_zero_exit_code(self):
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("crud.destination_test.subprocess.run", return_value=mock_result):
            success, detail = test_push_fn("rtmp://example.com/live/key")
        self.assertTrue(success)

    def test_reports_failure_with_last_stderr_line(self):
        mock_result = MagicMock(
            returncode=1,
            stderr="Connecting...\nConnection refused\n",
        )
        with patch("crud.destination_test.subprocess.run", return_value=mock_result):
            success, detail = test_push_fn("rtmp://example.com/live/key")
        self.assertFalse(success)
        self.assertEqual(detail, "Connection refused")

    def test_push_many_returns_empty_dict_for_no_destinations(self):
        self.assertEqual(test_push_many({}), {})

    def test_push_many_returns_result_per_destination(self):
        def fake_test_push(push_url):
            return (push_url == "rtmp://ok.example.com/live/key", push_url)

        with patch("crud.destination_test.test_push", side_effect=fake_test_push):
            results = test_push_many(
                {
                    1: "rtmp://ok.example.com/live/key",
                    2: "rtmp://bad.example.com/live/key",
                }
            )
        self.assertEqual(
            results,
            {
                1: (True, "rtmp://ok.example.com/live/key"),
                2: (False, "rtmp://bad.example.com/live/key"),
            },
        )


class StreamTestPushAllViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testallowner",
            email="testallowner@example.com",
            password="ownerpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.other_user = User.objects.create_user(
            username="testallother",
            email="testallother@example.com",
            password="otherpass123",
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )
        self.stream = Stream.objects.create(owner=self.user, name="Test all stream")
        self.ok_destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="OK dest",
            socialmedia_rtmp_link="rtmp://ok.example.com/live",
            socialmedia_rtmp_key="ok-key",
        )
        self.bad_destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="Bad dest",
            socialmedia_rtmp_link="rtmp://bad.example.com/live",
            socialmedia_rtmp_key="bad-key",
        )
        self.disabled_destination = Rtmp.objects.create(
            stream=self.stream,
            socialmedia_name="Disabled dest",
            socialmedia_rtmp_link="rtmp://disabled.example.com/live",
            socialmedia_rtmp_key="disabled-key",
            enabled=False,
        )

    def test_anonymous_redirects_to_login(self):
        url = reverse("crud:stream_test_push_all", args=[self.stream.id])
        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_other_user_gets_404(self):
        self.client.force_login(self.other_user)
        url = reverse("crud:stream_test_push_all", args=[self.stream.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_test_push_all", args=[self.stream.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_shows_message_per_enabled_destination_only(self):
        self.client.force_login(self.user)
        url = reverse("crud:stream_test_push_all", args=[self.stream.id])

        def fake_test_push_many(push_urls_by_id):
            return {
                destination_id: (
                    destination_id == self.ok_destination.id,
                    "детали",
                )
                for destination_id in push_urls_by_id
            }

        with patch(
            "crud.views.test_push_many", side_effect=fake_test_push_many
        ) as mock_many:
            response = self.client.post(url, follow=True)

        mock_many.assert_called_once_with(
            {
                self.ok_destination.id: self.ok_destination.push_url,
                self.bad_destination.id: self.bad_destination.push_url,
            }
        )
        self.assertContains(response, "«OK dest»: детали")
        self.assertContains(response, "«Bad dest»: детали")
        self.assertNotContains(response, "«Disabled dest»: детали")

    def test_shows_info_message_when_no_enabled_destinations(self):
        self.ok_destination.enabled = False
        self.ok_destination.save(update_fields=["enabled"])
        self.bad_destination.enabled = False
        self.bad_destination.save(update_fields=["enabled"])
        self.client.force_login(self.user)
        url = reverse("crud:stream_test_push_all", args=[self.stream.id])
        with patch("crud.views.test_push_many") as mock_many:
            response = self.client.post(url, follow=True)
        mock_many.assert_not_called()
        self.assertContains(response, "Нет включённых дестинаций")
