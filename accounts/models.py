from django.contrib.auth.models import AbstractUser
from django.db import models


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
