from django.core import signing

DECISION_MAX_AGE = 60 * 60 * 24 * 7  # 7 дней


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
