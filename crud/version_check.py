import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Тот же репозиторий, что и в docker/README.*.md/CLAUDE.md — реальных
# GitHub Releases в проекте не заводят (просто `git tag` + push, см.
# .github/workflows/docker-publish.yml), только сами теги vX.Y.Z, так
# что сверяемся с /tags, а не с несуществующим /releases/latest.
GITHUB_TAGS_URL = "https://api.github.com/repos/damodara/RestreamByDDas/tags"

CACHE_KEY = "restreambyddas_latest_release_tag"
# Анонимные запросы к GitHub API ограничены 60/час на IP, а новый тег
# появляется никак не чаще пары раз в месяц — синхронно ходить на GitHub
# при каждой загрузке страницы смысла не имеет, кэшируем на час.
CACHE_TTL_SECONDS = 3600

_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _parse_version(tag):
    """ "v1.2.3" -> (1, 2, 3); None для не-семверного тега/значения (в том
    числе APP_VERSION="dev" — локальная сборка без релизного тега)."""
    match = _VERSION_RE.match(tag or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def fetch_latest_release_tag():
    """Самый свежий по семверу git-тег vX.Y.Z в репозитории. None, если
    недоступно (сеть, лимит запросов, неожиданный формат ответа) — тот же
    fail-soft, что у остальных внешних интеграций проекта (nginx_stat,
    youtube_chat и т.д.)."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    request = urllib.request.Request(
        GITHUB_TAGS_URL, headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            tags = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        logger.warning(
            "fetch_latest_release_tag: не удалось получить/разобрать %s",
            GITHUB_TAGS_URL,
            exc_info=True,
        )
        return None

    parsed = [
        (version, tag["name"])
        for tag in tags
        if (version := _parse_version(tag.get("name")))
    ]
    if not parsed:
        return None

    latest_tag = max(parsed)[1]
    cache.set(CACHE_KEY, latest_tag, CACHE_TTL_SECONDS)
    return latest_tag


def check_for_update():
    """{"current", "latest", "update_available"} либо None, если сравнение
    невозможно (dev-сборка без релизного APP_VERSION, GitHub недоступен,
    или текущая версия в неожиданном формате)."""
    latest_tag = fetch_latest_release_tag()
    if latest_tag is None:
        return None

    current_version = _parse_version(settings.APP_VERSION)
    latest_version = _parse_version(latest_tag)
    if current_version is None or latest_version is None:
        return None

    return {
        "current": settings.APP_VERSION,
        "latest": latest_tag,
        "update_available": latest_version > current_version,
    }
