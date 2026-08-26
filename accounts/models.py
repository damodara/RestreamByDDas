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
    # нажатия «Завершить эфир» (crud:stream_end_broadcast). По умолчанию —
    # считать это необъявленным обрывом и уведомлять (см. notify_on_push_error/
    # notify_telegram_on_push_error выше) — в этом весь смысл фичи. Включив
    # этот флаг, пользователь говорит, что для него любое пропадание сигнала
    # само по себе уже означает "эфир закончился", и нажимать кнопку не
    # обязательно — тогда флаг просто тихо сбрасывается, без уведомления.
    auto_end_broadcast_on_drop = models.BooleanField(
        default=False,
        verbose_name="Считать эфир завершённым автоматически при пропадании сигнала",
        help_text="Если выключено — пропадание сигнала без нажатия «Завершить "
        "эфир» на странице потока считается необъявленным обрывом и "
        "уведомляет вас (см. уведомления об ошибке пуша выше). Если "
        "включено — эфир просто считается законченным, без уведомления.",
    )
