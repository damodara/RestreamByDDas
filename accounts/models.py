from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# Общий дефолт между полем ниже и crud/management/commands/
# cleanup_destination_logs.py (для файлов уже удалённых дестинаций/точек
# приёма — там нет владельца, у которого можно спросить его собственный
# log_retention_days, применяется этот дефолт).
DEFAULT_LOG_RETENTION_DAYS = 5


class User(AbstractUser):
    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Ожидает решения"
        APPROVED = "approved", "Подтверждён"
        REJECTED = "rejected", "Отклонён"

    email = models.EmailField(unique=True)
    approval_status = models.CharField(
        max_length=10,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # Сколько хранить лог-файлы push-процессов (crud/destination_logs.py)
    # для дестинаций этого пользователя, прежде чем cleanup_destination_logs
    # их удалит. Верхняя граница — чтобы не превратить поле в "хранить
    # вечно" и не раздувать rtmp_logs volume бесконтрольно.
    log_retention_days = models.PositiveSmallIntegerField(
        default=DEFAULT_LOG_RETENTION_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        verbose_name="Хранить логи дестинаций (дней)",
    )
    # Опт-ин, а не опт-аут — пользователь сам решает, нужны ли ему письма
    # об ошибках пуша (crud.emails.send_push_error_email, отправляется из
    # crud.views.destination_status_hook). По умолчанию выключено: без
    # явного согласия рассылка при первом же сбое площадки была бы для
    # пользователя неожиданной.
    notify_on_push_error = models.BooleanField(
        default=False,
        verbose_name="Уведомлять на email при ошибке пуша",
        help_text="Письмо придёт не чаще раза на инцидент — при переходе "
        "дестинации в статус «Ошибка», а не на каждую повторную попытку.",
    )
    # Заполняется accounts.management.commands.poll_telegram_bot при
    # получении /start <токен> от пользователя (deep-link из личного
    # кабинета) — сам Bot API не даёт написать пользователю первым, пока он
    # не напишет боту, так что chat_id мы не выбираем, а только принимаем.
    # Пусто = Telegram не привязан.
    telegram_chat_id = models.CharField(
        max_length=32, blank=True, verbose_name="Telegram chat ID"
    )
    # Независимый чекбокс от notify_on_push_error (не единый выбор канала)
    # — пользователь может хотеть оба сразу (email как архив, Telegram как
    # мгновенный сигнал) или только один.
    notify_telegram_on_push_error = models.BooleanField(
        default=False,
        verbose_name="Уведомлять в Telegram при ошибке пуша",
        help_text="Нужно сначала привязать Telegram ниже. Тот же принцип "
        "«раз на инцидент», что и у email-уведомлений.",
    )
    # Управляет тем, что crud.management.commands.poll_stream_health делает,
    # обнаружив пропажу Stream.expected_live=True потока из /stat без
    # нажатия «Завершить эфир» (crud:stream_end_broadcast). Включено по
    # умолчанию — большинство пользователей просто закрывают энкодер, не
    # думая о специальной кнопке, и трактовать это как инцидент "по
    # умолчанию" для всех выглядело бы как шум; кто явно хочет отслеживать
    # необъявленные обрывы (например, обрыв сети посреди эфира — не то же
    # самое, что штатное завершение), может выключить эту настройку и
    # получать уведомления через notify_on_push_error/
    # notify_telegram_on_push_error выше.
    auto_end_broadcast_on_drop = models.BooleanField(
        default=True,
        verbose_name="Считать эфир завершённым автоматически при пропадании сигнала",
        help_text="Включено — пропадание сигнала само по себе считается "
        "концом эфира, без уведомления. Выключите, чтобы обрыв связи или "
        "сбой энкодера без нажатия «Завершить эфир» на странице потока "
        "считался инцидентом и уведомлял вас (см. уведомления об ошибке "
        "пуша выше).",
    )
