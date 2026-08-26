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
