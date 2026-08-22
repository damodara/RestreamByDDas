from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY)


class EncryptedCharField(models.CharField):
    """Хранит значение зашифрованным (Fernet) — для полей с реальными
    credential-ами (RTMP-ключ дестинации), а не просто идентификаторами.

    Fernet не детерминирован (каждое шифрование даёт новый ciphertext даже
    для одного и того же значения), поэтому по этому полю нельзя фильтровать
    напрямую в БД (`.filter(field=value)` не найдёт совпадение) и нельзя
    держать на нём DB-level unique — сравнение уникальности делается на
    уровне приложения после расшифровки (см. DestinationForm)."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Значения, записанные до перехода на шифрование этого поля —
            # отдаём как есть, чтобы не терять данные при чтении.
            return value
