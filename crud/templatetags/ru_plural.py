from django import template

register = template.Library()


@register.filter
def ru_days(value):
    """Русское склонение "день/дня/дней" по числу — Django's built-in
    |pluralize поддерживает только 2 формы (англ. singular/plural) и молча
    рендерит пустую строку при 3 через запятую (день,дня,дней), не ошибка,
    просто не то поведение, что нужно для русского."""
    try:
        n = abs(int(value))
    except (TypeError, ValueError):
        return "дней"
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"
