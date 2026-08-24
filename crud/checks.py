from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, register


@register()
def field_encryption_key_check(app_configs, **kwargs):
    """Fernet(settings.FIELD_ENCRYPTION_KEY) is only ever called lazily,
    from crud.fields.EncryptedCharField, when an Rtmp row is actually
    read/written — so a missing/invalid key otherwise passes an empty
    install (login, /admin/ browsing) silently and only blows up later,
    with a cryptic ValueError, the first time someone adds a destination.
    Surfacing it here makes `manage.py migrate` (first thing the entrypoint
    runs) fail loudly and immediately instead."""
    if not settings.FIELD_ENCRYPTION_KEY:
        return [
            Error(
                "FIELD_ENCRYPTION_KEY is not set.",
                hint='Generate one: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())" and set it as '
                "FIELD_ENCRYPTION_KEY in .env.",
                id="crud.E001",
            )
        ]
    try:
        Fernet(settings.FIELD_ENCRYPTION_KEY)
    except Exception:
        return [
            Error(
                "FIELD_ENCRYPTION_KEY is not a valid Fernet key.",
                hint='Generate one: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())" and set it as '
                "FIELD_ENCRYPTION_KEY in .env.",
                id="crud.E002",
            )
        ]
    return []


@register()
def allowed_hosts_check(app_configs, **kwargs):
    """Django only enforces ALLOWED_HOSTS at request time (DisallowedHost),
    not at startup — so an empty value otherwise passes an empty install
    silently and only breaks once real traffic (including the nginx/srt
    hooks) arrives. Surfacing it here makes the failure show up immediately
    in `docker compose logs django` instead."""
    if not settings.DEBUG and not settings.ALLOWED_HOSTS:
        return [
            Error(
                "ALLOWED_HOSTS is empty while DEBUG=False.",
                hint="Set ALLOWED_HOSTS in .env to the server's public "
                "IP/domain (no scheme, no path), e.g. "
                "ALLOWED_HOSTS=example.com,1.2.3.4 — docker-compose.yml/"
                'docker-compose.prod.yml append ",django" automatically so '
                "the nginx/srt hooks can reach Django.",
                id="crud.E003",
            )
        ]
    return []
