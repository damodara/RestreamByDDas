import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from crud.fields import EncryptedCharField


def generate_stream_key():
    return secrets.token_urlsafe(16)


# Опознаём площадку по подстроке в socialmedia_name (свободный текст,
# пользователь вводит как хочет) — только для цветного бейджа-иконки в
# stream_detail.html, ни на что функциональное не влияет. Официальные
# логотипы (SVG) сознательно не используем — точное воспроизведение
# чужих товарных знаков не стоит того ради декоративной иконки; вместо
# этого — фирменный цвет площадки + инициалы, узнаваемо и без этого риска.
# Короткие/двусмысленные подстроки (типа "ok") намеренно не включены —
# слишком легко случайно совпадают с частью другого слова.
_PLATFORM_BADGES = [
    (("вконтакте", "vkontakte", "vk.com", "vk"), "VK", "#0077FF"),
    (("youtube", "ютуб"), "YT", "#FF0000"),
    (("twitch",), "TW", "#9146FF"),
    (("telegram", "телеграм", "телега"), "TG", "#26A5E4"),
    (("одноклассники", "ok.ru", "okru"), "ОК", "#EE8208"),
    (("rutube", "рутуб"), "RT", "#1D6FB8"),
    (("vimeo",), "VM", "#1AB7EA"),
    (("trovo",), "TR", "#19D66B"),
    (("kick",), "K", "#53FC18"),
]
_DEFAULT_BADGE_COLOR = "#6b7280"


class Stream(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="streams", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100, verbose_name="Название точки приёма")
    stream_key = models.CharField(
        max_length=64, unique=True, editable=False, default=generate_stream_key
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # ID видео YouTube-трансляции (из ссылки/студии YouTube) — вводится
    # пользователем вручную, как и остальные внешние адреса в проекте (RTMP
    # push URL и т.п.), мы её не создаём и не обнаруживаем автоматически.
    # Пусто = чат для этой точки приёма не подключён. Не привязано к
    # конкретной Rtmp-дестинации намеренно: чат — свойство самой трансляции
    # ("что льётся в этот stream_key прямо сейчас"), а не какого-то одного
    # из направлений рестрима.
    # max_length рассчитан на то, что сюда вставят целую ссылку, а не
    # только голый ID — StreamChatForm.clean_youtube_chat_video_id
    # укорачивает её до ID при сохранении, но валидация max_length на
    # ModelForm срабатывает раньше clean_<field>(), на исходной строке.
    youtube_chat_video_id = models.CharField(
        max_length=200, blank=True, verbose_name="YouTube Video ID для чата"
    )
    # True с момента успешной публикации (crud.views.on_publish_hook) до
    # явного «Завершить эфир» (crud:stream_end_broadcast) — намерение
    # "пользователь ещё не объявил, что закончил", а не текущий факт из
    # nginx-rtmp /stat (который отвечает только на "идёт ли поток прямо
    # сейчас", ничего не помня про предыдущие сеансы). Нужно отдельно от
    # /stat, чтобы crud.management.commands.poll_stream_health мог отличить
    # штатное завершение (кнопка нажата, флаг уже False) от необъявленного
    # обрыва (флаг всё ещё True, а по /stat потока уже нет) — иначе оба
    # случая выглядят для сервера одинаково.
    expected_live = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    @property
    def publish_server(self):
        # Без ключа — большинство энкодеров (OBS и т.п.) просят "Server" и
        # "Stream Key" как два отдельных поля, а не единую строку.
        if not settings.RTMP_SERVER_HOST:
            return None
        return f"rtmp://{settings.RTMP_SERVER_HOST}/{settings.RTMP_APP}"

    @property
    def srt_publish_url(self):
        if not settings.SRT_SERVER_HOST:
            return None
        return (
            f"srt://{settings.SRT_SERVER_HOST}:{settings.SRT_PORT}"
            f"?streamid=publish:{self.stream_key}"
        )


class Rtmp(models.Model):
    stream = models.ForeignKey(
        Stream, related_name="destinations", on_delete=models.CASCADE
    )
    socialmedia_name = models.CharField(
        max_length=100, verbose_name="Название соц сети для рестрима"
    )
    socialmedia_url = models.URLField(verbose_name="Адрес для просмотра", blank=True)
    socialmedia_rtmp_link = models.CharField(max_length=100, verbose_name="RTMP адрес")
    # Зашифровано at rest (Fernet, см. crud/fields.py) — это реальный
    # credential площадки, а не идентификатор. Не детерминировано, поэтому
    # без DB-level unique/filter по значению — уникальность в рамках Stream
    # проверяется в clean() ниже, расшифровкой и сравнением в Python.
    socialmedia_rtmp_key = EncryptedCharField(max_length=500, verbose_name="RTMP ключ")
    # Тумблер в stream_detail.html — выключенные дестинации не попадают в
    # ответ stream_destinations_hook (см. crud/views.py), т.е. push.sh их
    # не получит и ffmpeg на них не запустится. Как и остальной список
    # дестинаций, подхватывается только в момент старта публикации, а не
    # у уже идущего стрима (см. hint в stream_detail.html).
    enabled = models.BooleanField(default=True, verbose_name="Рестримить")

    class PushStatus(models.TextChoices):
        UNKNOWN = "unknown", "—"
        LIVE = "live", "В эфире"
        ERROR = "error", "Ошибка"
        STOPPED = "stopped", "Остановлено"

    # Обновляется push.sh через destination_status_hook, а не считается на
    # лету — в отличие от статуса самого потока (nginx-rtmp /stat, см.
    # nginx_stat.py), у Django нет способа заглянуть в /tmp/rtmp-push
    # nginx-контейнера, чтобы проверить состояние push-процесса напрямую.
    # Может быть устаревшим, если nginx упал грубо, не успев отрапортовать
    # "stopped"/"error" — stream_detail.html подстраховывается, показывая
    # это поле только пока сам поток live по /stat, и только пока сама
    # дестинация включена тумблером (enabled) — иначе, например, старый
    # "error" от сеанса до выключения продолжал бы висеть бейджем даже
    # после того, как в дестинацию перестали что-либо пушить.
    push_status = models.CharField(
        max_length=10, choices=PushStatus.choices, default=PushStatus.UNKNOWN
    )
    push_status_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.socialmedia_name

    def clean(self):
        # На уровне модели, а не только в DestinationForm — иначе, например,
        # Django admin (у него своя автосгенерированная ModelForm, наш
        # DestinationForm не используется) вообще не видит эту проверку и
        # молча создаёт дубликаты (подтверждено живьём).
        if self.stream_id is None:
            return
        siblings = Rtmp.objects.filter(stream_id=self.stream_id)
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)
        if any(s.socialmedia_rtmp_key == self.socialmedia_rtmp_key for s in siblings):
            raise ValidationError(
                {
                    "socialmedia_rtmp_key": "Такой RTMP-ключ уже используется "
                    "в этой точке приёма."
                }
            )

    @property
    def push_url(self):
        return f"{self.socialmedia_rtmp_link.rstrip('/')}/{self.socialmedia_rtmp_key}"

    @property
    def platform_badge(self):
        name = self.socialmedia_name.lower()
        for keywords, label, color in _PLATFORM_BADGES:
            if any(keyword in name for keyword in keywords):
                return {"label": label, "color": color}
        first_char = self.socialmedia_name.strip()[:1].upper() or "?"
        return {"label": first_char, "color": _DEFAULT_BADGE_COLOR}


class ChatMessage(models.Model):
    class Platform(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"

    stream = models.ForeignKey(
        Stream, related_name="chat_messages", on_delete=models.CASCADE
    )
    platform = models.CharField(max_length=10, choices=Platform.choices)
    # ID сообщения на стороне площадки — YouTube иногда отдаёт одно и то же
    # сообщение повторно на соседних страницах поллинга; unique_together
    # ниже + get_or_create в poll_youtube_chat защищают от дублей на вставке.
    external_id = models.CharField(max_length=100)
    author_name = models.CharField(max_length=200)
    text = models.TextField()
    posted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stream", "platform", "external_id"],
                name="unique_chat_message_per_stream_platform",
            )
        ]
        ordering = ["posted_at"]

    def __str__(self):
        return f"{self.author_name}: {self.text[:50]}"
