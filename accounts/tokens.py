from django.core import signing

DECISION_MAX_AGE = 60 * 60 * 24 * 7  # 7 дней

# Короче, чем DECISION_MAX_AGE — новый email мог быть введён по ошибке или
# принадлежать не тому, кто его ввёл, так что ссылка не должна оставаться
# рабочей неделями.
EMAIL_CHANGE_MAX_AGE = 60 * 60 * 24  # 1 день

# Короткий — ссылка живёт ровно на время "открыть Telegram и нажать
# /start", не на потом; истёкшую просто перегенерирует следующая загрузка
# страницы профиля (см. accounts.views.profile).
TELEGRAM_LINK_MAX_AGE = 60 * 15  # 15 минут


def make_decision_token(user, action):
    return signing.dumps({"user_id": user.pk}, salt=f"accounts-decision-{action}")


def read_decision_token(token, action):
    """Возвращает user_id или None, если токен невалиден/просрочен."""
    try:
        data = signing.loads(
            token, salt=f"accounts-decision-{action}", max_age=DECISION_MAX_AGE
        )
    except signing.BadSignature:
        return None
    return data.get("user_id")


def make_email_change_token(user, new_email):
    return signing.dumps(
        {"user_id": user.pk, "email": new_email}, salt="accounts-email-change"
    )


def read_email_change_token(token):
    """Возвращает {"user_id":, "email":} или None, если токен невалиден/просрочен."""
    try:
        return signing.loads(
            token, salt="accounts-email-change", max_age=EMAIL_CHANGE_MAX_AGE
        )
    except signing.BadSignature:
        return None


def make_telegram_link_token(user):
    return signing.dumps({"user_id": user.pk}, salt="accounts-telegram-link")


def read_telegram_link_token(token):
    """Возвращает user_id или None, если токен невалиден/просрочен."""
    try:
        data = signing.loads(
            token, salt="accounts-telegram-link", max_age=TELEGRAM_LINK_MAX_AGE
        )
    except signing.BadSignature:
        return None
    return data.get("user_id")
